
"""Product-to-Standard discovery using the existing BIS retrieval engine."""

from __future__ import annotations

from dataclasses import dataclass, field

from app import boundary as boundary_module
from app import language as lang
from app.retrieval.engine import RetrievalResult, SearchEngine

# ---------------------------------------------------------------------------
# "Why this result?" (Phase 9)
#
# The deterministic retrieval engine (Phase 3) already decides *which* fields a
# query matched, with what term, and with what weight - every one recorded as a
# MatchReason on the RetrievalResult. Phase 9 only turns those existing facts
# into a short, human-readable sentence. There is NO LLM here and NO second
# ranking or scoring pass: `explain_candidate` is a pure function of the
# RetrievalResult the engine already produced.
# ---------------------------------------------------------------------------

# Fixed display order + phrasing for each MatchReason field. Order matters so
# the explanation is deterministic regardless of the order reasons were added.
_FIELD_PHRASES: dict[str, str] = {
    "standard_number": "the query names this Indian Standard number",
    "category": "the query wording points to this standard's subject area",
    "title": "query terms appear in the standard's title",
    "keywords": "query terms match keywords recorded for this standard",
    "document_name": "query terms appear in the name of the BIS source document",
    "reference": "query terms appear in the standard's BIS reference",
    "content": "query terms appear in the BIS description of this standard",
}
_FIELD_ORDER: list[str] = list(_FIELD_PHRASES)

# Retrieval confidence -> plain word used in the explanation.
_STRENGTH: dict[str, str] = {
    "high": "strong",
    "medium": "moderate",
    "low": "weak",
    "none": "weak",
}


@dataclass(frozen=True)
class WhyThisResult:
    """Deterministic 'Why this result?' explanation for one candidate standard.

    Built entirely from the retrieval engine's MatchReason data - never from an
    LLM. `signals` lists, in a fixed order, each field the query matched in;
    `summary` is a single plain sentence; `strength` mirrors retrieval
    confidence (strong / moderate / weak).
    """

    standard_number: str
    strength: str
    signals: list[str]
    summary: str


def explain_candidate(result: RetrievalResult) -> WhyThisResult:
    """Turn a RetrievalResult's deterministic MatchReasons into an explanation.

    Pure function: same input -> same output, no I/O, no LLM.
    """
    # Group the match reasons by field, keeping the distinct terms in order.
    terms_by_field: dict[str, list[str]] = {}
    for reason in result.reasons:
        bucket = terms_by_field.setdefault(reason.field, [])
        if reason.term not in bucket:
            bucket.append(reason.term)

    signals: list[str] = []
    for field_name in _FIELD_ORDER:
        terms = terms_by_field.get(field_name)
        if not terms:
            continue
        phrase = _FIELD_PHRASES[field_name]
        if field_name == "category":
            signals.append(phrase)
        else:
            signals.append(f"{phrase} ({', '.join(terms)})")

    strength = _STRENGTH.get(result.confidence, "weak")

    if not signals:  # defensive: a scored result always has at least one reason
        joined = "the query matched the BIS evidence for this standard"
    elif len(signals) == 1:
        joined = signals[0]
    elif len(signals) == 2:
        joined = f"{signals[0]} and {signals[1]}"
    else:
        joined = "; ".join(signals[:-1]) + "; and " + signals[-1]

    summary = (
        f"Retrieved as a candidate standard ({strength} match) because {joined}."
    )

    return WhyThisResult(
        standard_number=result.item.standard_number or "",
        strength=strength,
        signals=signals,
        summary=summary,
    )


# Standing caveat attached to a grounded Product -> Standard response so the UI
# never implies a legal decision the retrieval engine did not make.
_GROUNDED_NOTE = (
    "Candidate Indian Standards retrieved from the BIS knowledge base and ranked "
    "by deterministic lexical match. A high match score indicates relevance to "
    "the description, not a legal determination of applicability."
)


@dataclass(frozen=True)
class ProductStandardOutcome:
    """Result of one product-to-standard discovery query."""

    product: str
    results: list[RetrievalResult]
    confidence: str
    grounded: bool
    note: str = ""
    # Phase 9: one deterministic "Why this result?" explanation per entry in
    # `results`, in the same order. Empty when the query abstained.
    explanations: list[WhyThisResult] = field(default_factory=list)
    # Phase 3: on abstention, MetrIQ's own explanation of its coverage boundary —
    # what the verified data holds, what the search did, and where to look next.
    # None whenever there is an answer; there is no boundary to explain then.
    boundary: boundary_module.Boundary | None = None


class ProductStandardFinder:
    """Thin Product -> Standard layer over the existing SearchEngine."""

    def __init__(self, search_engine: SearchEngine) -> None:
        self.search_engine = search_engine
        # Counted once from the loaded knowledge base, so the numbers MetrIQ
        # quotes about itself can never drift away from the data.
        self.coverage = boundary_module.measure(search_engine.items)

    def find(
        self,
        product: str,
        limit: int = 5,
        language: str = lang.EN,
    ) -> ProductStandardOutcome:
        product = product.strip()

        if not product:
            return ProductStandardOutcome(
                product="",
                results=[],
                confidence="none",
                grounded=False,
                note="product description is empty",
            )

        # Reuse the existing deterministic retrieval and ranking.
        search = self.search_engine.search(product, limit=50)

        # The retrieval engine matches single query words across many fields, so a
        # generic material word ("steel", "water") alone can pull in an unrelated
        # standard (structural steel tubes, packaged drinking water) for a product
        # like "stainless steel water bottle". For Product -> Standard discovery we
        # need the standard to actually describe the product, not just share a word
        # with it. So a candidate is kept only when the retrieved standard matches
        # more than half of the product's search terms, or at least two of them.
        query_terms = set(search.query_terms) | set(search.query_standard_numbers)
        total_terms = len(query_terms)

        def describes_product(result: RetrievalResult) -> bool:
            hits = sum(1 for term in result.matched_terms if term in query_terms)
            if hits >= 2:
                return True
            return total_terms > 0 and hits / total_terms > 0.5

        candidates = [
            result
            for result in search.results
            if result.item.category == "indian_standards"
            and result.item.standard_number
            and result.confidence != "none"
            and describes_product(result)
        ]

        candidates = candidates[: max(1, min(limit, 50))]

        if not candidates:
            # Nothing clearly describes the product. Rather than a dead end, say
            # what the verified data covers, what the search did, and where to
            # look next — and show any partial match as evidence, never as an
            # answer. See app/boundary.py for what this deliberately never claims.
            weak = boundary_module.weak_matches_from([
                result for result in search.results
                if result.item.category == "indian_standards" and result.item.standard_number
            ])
            return ProductStandardOutcome(
                product=product,
                results=[],
                confidence="none",
                grounded=False,
                note=(
                    "no Indian Standard in the knowledge base clearly describes "
                    "this product; only loose single-word matches were found, so "
                    "no recommendation is made"
                ),
                boundary=boundary_module.explain(
                    product, self.coverage, language, weak_matches=weak,
                ),
            )

        return ProductStandardOutcome(
            product=product,
            results=candidates,
            confidence=candidates[0].confidence,
            grounded=True,
            note=_GROUNDED_NOTE,
            explanations=[explain_candidate(result) for result in candidates],
        )
