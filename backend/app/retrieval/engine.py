"""Deterministic lexical retrieval over the BIS knowledge base.

No LLM, no embeddings, no external search engine. Given a natural-language query
this module:

  1. normalizes and tokenizes the query (see text.py),
  2. scores every knowledge item with a transparent weighted sum,
  3. ranks them,
  4. classifies retrieval confidence,
  5. abstains when there is no meaningful match.

Every point that a result scores is recorded as a `MatchReason`, so a later phase
can build a "Why this result?" explanation from real matching signals.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path

from app.knowledge.loader import load_knowledge_base
from app.knowledge.schema import KnowledgeItem
from app.retrieval.text import (
    find_standard_numbers,
    normalize,
    standard_number_key,
    tokenize,
)

# Confidence levels, ordered weakest -> strongest.
CONFIDENCE_ORDER = ("none", "low", "medium", "high")


@dataclass(frozen=True)
class RetrievalConfig:
    """All tunable numbers in one place. Defaults are explained in the README."""

    # How much a matched query term is worth, per field it matches in.
    weight_standard_number_exact: float = 12.0  # number + year both match
    weight_standard_number: float = 8.0  # primary number matches
    weight_title: float = 4.0
    weight_keyword: float = 3.0
    weight_document_name: float = 1.5
    weight_reference: float = 1.0
    weight_content: float = 1.0  # only counted if not already in title/keywords
    weight_category_hint: float = 2.0

    # Confidence thresholds, applied to the top result's raw score.
    # Reference points: title match = 4, keyword match = 3, category hint = 2,
    # buried content mention = 1, primary standard-number match = 8.
    #   high   >= 7.5  -> at least a title + keyword match, or a standard number
    #   medium >= 4.0  -> at least a full title match
    #   low    >= 1.0  -> only a keyword or a buried content mention
    #   none   <  1.0  -> abstain
    threshold_high: float = 7.5
    threshold_medium: float = 4.0
    threshold_low: float = 1.0

    # If the top result matches fewer than this fraction of the query terms,
    # confidence is capped at "low" (the query is only partly covered).
    coverage_floor: float = 0.34

    # "high" is meant to mean a title AND a keyword match (see the thresholds
    # above) — two pieces of evidence, not one word counted twice in two fields.
    # A single common word ("oil", "cement", "steel") can otherwise reach 7.5 on
    # its own and name one arbitrary standard out of many that share it, so a
    # one-term match is capped at "medium" unless the term is a standard number.
    min_terms_for_high: int = 2

    # How many results to return.
    top_k: int = 5

    # Queries shorter than this (after normalization) are rejected up front.
    min_query_chars: int = 2


# Query word -> the category it points at. Small and explicit on purpose.
CATEGORY_HINTS: dict[str, str] = {
    "certification": "certification",
    "certificate": "certification",
    "certified": "certification",
    "isi": "certification",
    "licence": "certification",
    "license": "certification",
    "qco": "certification",
    "crs": "certification",
    "registration": "certification",
    "hallmark": "hallmarking",
    "hallmarking": "hallmarking",
    "hallmarked": "hallmarking",
    "huid": "hallmarking",
    "gold": "hallmarking",
    "silver": "hallmarking",
    "jewellery": "hallmarking",
    "jeweller": "hallmarking",
    "jewelry": "hallmarking",
    "karat": "hallmarking",
    "carat": "hallmarking",
    "purity": "hallmarking",
    "assaying": "hallmarking",
    "lab": "laboratories",
    "labs": "laboratories",
    "laboratory": "laboratories",
    "laboratories": "laboratories",
    "testing": "testing",
    "tested": "testing",
    "consumer": "consumer_information",
    "complaint": "consumer_information",
    "grievance": "consumer_information",
    "faq": "faqs",
    "faqs": "faqs",
}


@dataclass(frozen=True)
class MatchReason:
    """One reason a result scored: a query term matched a specific field."""

    field: str  # "title", "keywords", "content", "standard_number", "category", ...
    term: str
    weight: float
    detail: str = ""


@dataclass(frozen=True)
class RetrievalResult:
    """A single ranked knowledge item plus why it matched."""

    item: KnowledgeItem
    score: float
    confidence: str
    matched_terms: list[str]
    reasons: list[MatchReason]

    # Convenience copies so callers/JSON always carry provenance.
    @property
    def source_url(self) -> str | None:
        return self.item.source_url

    @property
    def verification_status(self) -> str:
        return self.item.verification_status

    @property
    def category(self) -> str:
        return self.item.category


@dataclass(frozen=True)
class SearchOutcome:
    """The full answer to one query."""

    query: str
    normalized_query: str
    query_terms: list[str]
    query_standard_numbers: list[str]
    results: list[RetrievalResult]
    confidence: str
    abstained: bool
    note: str = ""


@dataclass
class _IndexedItem:
    """Pre-lowercased fields for one knowledge item, built once at load time."""

    item: KnowledgeItem
    title: str
    content: str
    document_name: str
    reference: str
    keyword_set: set[str]
    keyword_blob: str
    standard_key: tuple[str, str] | None


def _cap_confidence(level: str, ceiling: str) -> str:
    if CONFIDENCE_ORDER.index(level) <= CONFIDENCE_ORDER.index(ceiling):
        return level
    return ceiling


class SearchEngine:
    """Loads the knowledge base once and answers queries against it."""

    def __init__(
        self,
        knowledge_dir: Path | None = None,
        config: RetrievalConfig | None = None,
    ) -> None:
        self.config = config or RetrievalConfig()
        load = load_knowledge_base(knowledge_dir)
        self.load_errors = load.errors
        # Clause records (Phase 7) and Quality Control Order records (Phase 9) are
        # citation-only: reached through app/clauses.py / app/qco.py after a standard is
        # retrieved, never through this index or ``items``.
        self._items = [it for it in load.items
                       if it.category not in ("standard_clauses", "quality_control_orders")]
        # Only BIS items are searchable: every search feature (Q&A, Product ->
        # Standard, certification, laboratories) presents its results as BIS
        # sources. Legal Metrology items are loaded (see ``items``) for inspection
        # requirements, never mixed into BIS search results.
        self._index: list[_IndexedItem] = [
            self._index_item(it) for it in self._items if it.source_authority == "BIS"
        ]

    # ------------------------------------------------------------------ indexing

    @staticmethod
    def _index_item(item: KnowledgeItem) -> _IndexedItem:
        keyword_set = {normalize(k) for k in item.keywords}
        return _IndexedItem(
            item=item,
            title=normalize(item.title),
            content=normalize(item.content),
            document_name=normalize(item.document_name or ""),
            reference=normalize(item.reference or ""),
            keyword_set=keyword_set,
            keyword_blob=" ".join(sorted(keyword_set)),
            standard_key=standard_number_key(item.standard_number),
        )

    @property
    def size(self) -> int:
        return len(self._index)

    @property
    def items(self) -> list[KnowledgeItem]:
        """Every loaded knowledge item (BIS and Legal Metrology), in load order (read-only use)."""
        return list(self._items)

    # ------------------------------------------------------------------ scoring

    def _score_item(
        self,
        indexed: _IndexedItem,
        terms: list[str],
        query_standards: list[str],
    ) -> tuple[float, list[MatchReason]]:
        cfg = self.config
        reasons: list[MatchReason] = []

        # --- standard-number match (strongest signal) ---
        if indexed.standard_key and query_standards:
            primary, year = indexed.standard_key
            for q in query_standards:
                q_number, _, q_year = q.partition(":")
                if q_number != primary:
                    continue
                if q_year and q_year == year:
                    reasons.append(
                        MatchReason(
                            "standard_number",
                            q,
                            cfg.weight_standard_number_exact,
                            f"query names {indexed.item.standard_number}",
                        )
                    )
                else:
                    reasons.append(
                        MatchReason(
                            "standard_number",
                            q,
                            cfg.weight_standard_number,
                            f"query number {q_number} matches {indexed.item.standard_number}",
                        )
                    )

        # --- per-term field matches ---
        for term in terms:
            in_title = _contains_word(indexed.title, term)
            in_keywords = term in indexed.keyword_set or _contains_word(
                indexed.keyword_blob, term
            )
            in_doc = _contains_word(indexed.document_name, term)
            in_ref = _contains_word(indexed.reference, term)
            in_content = _contains_word(indexed.content, term)

            if in_title:
                reasons.append(MatchReason("title", term, cfg.weight_title))
            if in_keywords:
                reasons.append(MatchReason("keywords", term, cfg.weight_keyword))
            if in_doc:
                reasons.append(
                    MatchReason("document_name", term, cfg.weight_document_name)
                )
            if in_ref:
                reasons.append(MatchReason("reference", term, cfg.weight_reference))
            if in_content and not (in_title or in_keywords):
                reasons.append(MatchReason("content", term, cfg.weight_content))

            hinted = CATEGORY_HINTS.get(term)
            if hinted and hinted == indexed.item.category:
                reasons.append(
                    MatchReason(
                        "category",
                        term,
                        cfg.weight_category_hint,
                        f"query word points at the '{hinted}' category",
                    )
                )

        score = sum(r.weight for r in reasons)
        return score, reasons

    # ------------------------------------------------------------------ search

    def search(self, query: str, limit: int | None = None) -> SearchOutcome:
        cfg = self.config
        limit = cfg.top_k if limit is None else max(1, min(limit, 50))

        normalized = normalize(query or "")
        terms = tokenize(query or "")
        query_standards = find_standard_numbers(query or "")

        if len(normalized) < cfg.min_query_chars or (
            not terms and not query_standards
        ):
            return SearchOutcome(
                query=query or "",
                normalized_query=normalized,
                query_terms=terms,
                query_standard_numbers=query_standards,
                results=[],
                confidence="none",
                abstained=True,
                note="query is empty or has no searchable terms",
            )

        scored: list[RetrievalResult] = []
        for indexed in self._index:
            score, reasons = self._score_item(indexed, terms, query_standards)
            if score <= 0:
                continue
            matched_terms = _distinct([r.term for r in reasons])
            scored.append(
                RetrievalResult(
                    item=indexed.item,
                    score=round(score, 3),
                    confidence="none",  # filled in below
                    matched_terms=matched_terms,
                    reasons=reasons,
                )
            )

        # Rank: score first, then a stable tiebreak so output is deterministic.
        scored.sort(key=lambda r: (-r.score, r.item.id))

        if not scored:
            return SearchOutcome(
                query=query or "",
                normalized_query=normalized,
                query_terms=terms,
                query_standard_numbers=query_standards,
                results=[],
                confidence="none",
                abstained=True,
                note="no knowledge item matched any query term",
            )

        total_terms = len(terms) + len(query_standards)
        graded = [
            replace(r, confidence=self._confidence(r, total_terms)) for r in scored
        ]
        top_confidence = graded[0].confidence
        abstained = top_confidence == "none"

        return SearchOutcome(
            query=query or "",
            normalized_query=normalized,
            query_terms=terms,
            query_standard_numbers=query_standards,
            results=[] if abstained else graded[:limit],
            confidence=top_confidence,
            abstained=abstained,
            note="" if not abstained else "matches were too weak to be confident",
        )

    # ------------------------------------------------------------------ confidence

    def _confidence(self, result: RetrievalResult, total_terms: int) -> str:
        cfg = self.config
        score = result.score
        if score >= cfg.threshold_high:
            level = "high"
        elif score >= cfg.threshold_medium:
            level = "medium"
        elif score >= cfg.threshold_low:
            level = "low"
        else:
            return "none"

        if total_terms > 0:
            coverage = len(result.matched_terms) / total_terms
            if coverage < cfg.coverage_floor:
                level = _cap_confidence(level, "low")

        names_standard = any(r.field == "standard_number" for r in result.reasons)
        if len(result.matched_terms) < cfg.min_terms_for_high and not names_standard:
            level = _cap_confidence(level, "medium")
        return level


# --------------------------------------------------------------------- helpers


def _contains_word(haystack: str, needle: str) -> bool:
    """Whole-token containment on already-normalized (space-separated) text.

    Tries a simple trailing-'s' plural in both directions ('bulb' <-> 'bulbs')
    so a query written in either form still meets a knowledge-base keyword
    written in the other — the same conservative stemming
    app/product_identification.py already uses for phrase matching. Phase 9.1:
    -ches / -shes / -xes / -sses / -zes plurals also drop "es" ('wrenches' ->
    'wrench', 'boxes' -> 'box', 'glasses' -> 'glass'), tried IN ADDITION to the
    old '-s' form, so nothing that matched before stops matching; a singular reaches
    its "-es" plural for -ch / -sh / -x / -z ('wrench' -> 'wrenches'), not -ss. The query term
    itself is never rewritten; only this containment check is plural-insensitive.
    """
    if not haystack or not needle:
        return False
    hay = f" {haystack} "
    if f" {needle} " in hay:
        return True
    if len(needle) > 3 and needle.endswith(("ches", "shes", "xes", "sses", "zes")) \
            and f" {needle[:-2]} " in hay:
        return True
    if len(needle) > 3 and needle.endswith("s") and not needle.endswith("ss"):
        return f" {needle[:-1]} " in hay
    # Singular -> "-es" plural, but not for -ss: "process" reaching "processes" made
    # "certification process" confidently match welding clothing "for … allied
    # processes" (test_certification caught it; the eval set has no such query).
    if needle.endswith(("ch", "sh", "x", "z")) and f" {needle}es " in hay:
        return True
    if not needle.endswith("s"):
        return f" {needle}s " in hay
    return False


def _distinct(values: list[str]) -> list[str]:
    seen: list[str] = []
    for v in values:
        if v not in seen:
            seen.append(v)
    return seen
