"""BIS testing laboratory search (Phase 7, extended in Milestone 18).

Two kinds of evidence, kept separate:

  1. BIS *guidance* — the `laboratories` / `testing` knowledge records: the
     Laboratory Recognition Scheme, where BIS publishes its lists, the LIMS
     portal. This is prose, retrieved by the Phase 3 SearchEngine. (Phase 7.)
  2. BIS *laboratory records* — a verified snapshot of BIS's own LIMS "IS-wise
     test facilities" listing (`app/lab_registry.py`). This is what makes
     standard -> laboratory real: a laboratory is relevant to a standard
     because BIS ITSELF LISTS IT there, never because of its name or city.
     (Milestone 18.)

The product -> standard step reuses the existing ProductStandardFinder; there is
no second product classifier. If that mapping is not confident, the laboratory
lookup does not proceed as if it were — it simply returns no standard-backed
laboratories.

So this service:

  1. runs deterministic retrieval over the `laboratories` and `testing`
     categories (Phase 3 SearchEngine, unchanged),
  2. identifies an Indian Standard / product context if the query names one,
  3. checks the evidence is strong enough to say anything useful,
  4. optionally asks the local LLM to explain ONLY that evidence,
  5. returns a structured result: the matched laboratory records (when any),
     the BIS guidance evidence, and BIS's official laboratory directories.

The LLM never decides which laboratories are relevant — retrieval does, before
the model is called, and the model may only name laboratories that are already
in its context. When nothing matches, the service says so rather than fabricate.
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from app import language as lang
from app.lab_registry import (
    CURRENTNESS_NOTE,
    SNAPSHOT_NOTE,
    LabMatch,
    LabRegistry,
    load_laboratories,
)
from app.llm import LocalLLM
from app.product import ProductStandardFinder
from app.rag import _build_context
from app.retrieval import RetrievalResult, SearchEngine
from app.retrieval.text import find_standard_numbers, standard_number_key

# Knowledge-base categories that carry BIS laboratory / testing information.
LAB_CATEGORIES = ("laboratories", "testing")

# A laboratory-evidence item must score at least this much in retrieval to
# count towards sufficiency (keyword = 3, title = 4, category hint = 2), so a
# single stray generic-word match cannot look like real evidence.
LAB_EVIDENCE_MIN_SCORE = 5.0

NO_LAB_RECORDS_NOTE = (
    "This assistant does not hold individual BIS laboratory records (names, "
    "addresses, recognition or accreditation status, or IS-wise testing "
    "scope). For those, use the official BIS list of recognised / empanelled "
    "laboratories and the BIS LIMS portal (lims.bis.gov.in) cited in the "
    "sources below."
)

INSUFFICIENT_EVIDENCE_ANSWER = (
    "The available BIS knowledge base does not contain sufficient verified "
    "information to answer this laboratory question."
)

LAB_SYSTEM_PROMPT = """You are the BIS Assistant for an evidence-backed Indian
Standards information system, answering a question about BIS-recognized testing
laboratories.

Rules:
1. Use ONLY the BIS evidence supplied by the application. Do not use pretrained
   knowledge as evidence.
2. Do NOT invent laboratory names, addresses, cities, contact details, BIS
   recognition or accreditation status, NABL numbers, supported standards,
   testing scope, validity dates or operational status.
   You may name a laboratory ONLY if it appears in the MATCHED LABORATORY
   RECORDS section of the supplied evidence, and only with the details given
   there. Never add a laboratory that is not in that section, and never say a
   laboratory is accredited, approved, currently operating, or best/recommended
   — the evidence establishes only that BIS's LIMS listing lists it against the
   stated Indian Standard, as at the snapshot date.
   If no laboratory records are supplied, name no laboratory at all.
3. You may explain, only as far as the evidence states, that BIS operates a
   Laboratory Recognition Scheme, where BIS publishes its recognised /
   empanelled-laboratory lists, and that the LIMS portal (lims.bis.gov.in)
   gives IS-wise test facilities and testing charges.
4. You explain the evidence. You do NOT make recognition or accreditation
   determinations, and you do not rank or recommend laboratories.
5. If the supplied evidence does not answer the question, say that the
   available verified evidence is insufficient. Do not fill the gap.
6. Be concise and directly address the question.
"""


@dataclass(frozen=True)
class LaboratorySearch:
    """The full answer to one laboratory query."""

    query: str
    standard_context: str | None
    answer: str
    grounded: bool
    confidence: str
    sources: list[RetrievalResult]
    note: str = ""
    # Milestone 18: laboratories BIS's own LIMS listing supports. Empty when
    # nothing matched — never padded to look fuller.
    laboratories: list[LabMatch] = dataclass_field(default_factory=list)
    # The standard the laboratories were matched on, when one was established.
    laboratory_standard: str | None = None
    # How that standard was established: "query" (the user named it),
    # "product" (product -> standard retrieval), or None.
    laboratory_standard_source: str | None = None


def _beyond_category_hint(result: RetrievalResult) -> bool:
    """True when the result matched real text, not only a category-hint word."""
    return any(reason.field != "category" for reason in result.reasons)


def _dedupe(results: list[RetrievalResult]) -> list[RetrievalResult]:
    seen: set[str] = set()
    out: list[RetrievalResult] = []
    for result in results:
        if result.item.id in seen:
            continue
        seen.add(result.item.id)
        out.append(result)
    return out


def _matched_note(registry: LabRegistry) -> str:
    """What the matched records do and do not establish."""
    retrieved = registry.source.get("retrieved_on") or "an earlier date"
    return (
        f"These laboratories come from a snapshot of BIS's own LIMS IS-wise test-facility "
        f"listing (lims.bis.gov.in) taken on {retrieved}. For the complete and current picture, "
        f"use the BIS LIMS portal and BIS's official recognised / empanelled laboratory lists. "
        f"{SNAPSHOT_NOTE} {CURRENTNESS_NOTE}"
    )


def _deterministic_summary(
    sources: list[RetrievalResult],
    laboratories: list[LabMatch] | None = None,
    standard: str | None = None,
) -> str:
    """A plain, no-LLM answer built only from retrieved evidence."""
    lines: list[str] = []
    laboratories = laboratories or []
    if laboratories:
        head = (f"BIS's LIMS listing records {len(laboratories)} laboratory record(s) for "
                f"{standard}:" if standard
                else f"{len(laboratories)} matching laboratory record(s) were found:")
        lines.append(head)
        lines.extend(f"- {m.record.lab_name}" for m in laboratories[:10])
        if len(laboratories) > 10:
            lines.append(f"- … and {len(laboratories) - 10} more in the full result.")
        lines.append("")
    if sources:
        lines.append("Related official BIS guidance:")
        lines.extend(f"- {r.item.title}" for r in sources)
        lines.append("")
    lines.append(NO_LAB_RECORDS_NOTE if not laboratories else f"{SNAPSHOT_NOTE} {CURRENTNESS_NOTE}")
    return "\n".join(lines)


def _laboratory_context(laboratories: list[LabMatch]) -> str:
    """The matched records, as the ONLY laboratories the model may name."""
    if not laboratories:
        return (
            "\nMATCHED LABORATORY RECORDS:\n(none — no verified laboratory record matched "
            "this query, so you must not name any laboratory)\n"
        )
    lines = ["\nMATCHED LABORATORY RECORDS (the only laboratories you may name):"]
    for match in laboratories[:15]:
        record = match.record
        status, iso = record.validity()
        lines.append(
            f"- NAME: {record.lab_name}\n"
            f"  OSL CODE: {record.osl_code or 'not stated'}\n"
            f"  CITY: {record.city or 'not stated in the record'}\n"
            f"  LISTED FOR: {record.standard_as_listed} — {record.product_as_listed}\n"
            f"  RECOGNITION VALID UNTIL: {iso or 'not stated'} ({status}, as at the snapshot)\n"
            f"  BIS REMARK: {record.remark or 'none'}"
        )
    lines.append("(These are BIS LIMS listings as at the snapshot date. They do not establish "
                 "accreditation, current scope, availability or operational status.)\n")
    return "\n".join(lines)


class LaboratorySearchService:
    """Deterministic retrieval, then an optional grounded explanation."""

    def __init__(
        self,
        search_engine: SearchEngine,
        llm: LocalLLM,
        retrieval_limit: int = 10,
        max_sources: int = 6,
        registry: LabRegistry | None = None,
        product_finder: ProductStandardFinder | None = None,
        max_laboratories: int = 25,
    ) -> None:
        self.search_engine = search_engine
        self.llm = llm
        self.retrieval_limit = retrieval_limit
        self.max_sources = max_sources
        # Milestone 18. Both optional: without them this service behaves exactly
        # as it did in Phase 7, which is what the Phase 7 tests assert.
        self.registry = registry if registry is not None else load_laboratories()
        self.product_finder = product_finder
        self.max_laboratories = max_laboratories

    # ------------------------------------------------ laboratories (no LLM)

    def find_laboratories(
        self, query: str, standard_number: str | None = None
    ) -> tuple[list[LabMatch], str | None, str | None]:
        """(matches, standard, how the standard was established). Deterministic.

        Order of evidence, strongest first:
          1. a standard given by the caller or named in the query,
          2. product -> standard, via the EXISTING ProductStandardFinder, and
             only when that retrieval is confident — an uncertain product is
             not carried forward as if it were certain,
          3. a plain laboratory-name / city / product-text lookup.
        """
        if standard_number:
            matches = self.registry.for_standard(standard_number)
            if matches:
                return matches[: self.max_laboratories], standard_number, "standard"

        named = [value for value in find_standard_numbers(query)]
        if named:
            matches = self.registry.for_standard(query)
            if matches:
                return matches[: self.max_laboratories], matches[0].matched_standard, "query"

        if self.product_finder is not None:
            outcome = self.product_finder.find(query, limit=3)
            # Only a confident product -> standard mapping may drive a
            # laboratory claim. Anything weaker is left alone.
            if outcome.grounded and outcome.results:
                top = outcome.results[0]
                if top.confidence in {"medium", "high"} and top.item.standard_number:
                    matches = self.registry.for_standard(top.item.standard_number)
                    if matches:
                        return (matches[: self.max_laboratories],
                                top.item.standard_number, "product")

        matches = self.registry.search(query)
        return matches[: self.max_laboratories], None, ("text" if matches else None)

    # ---------------------------------------------------------- evidence (no LLM)

    def gather(
        self, query: str
    ) -> tuple[list[RetrievalResult], str | None]:
        """Retrieve laboratory evidence and any Indian Standard context.

        Deterministic. No LLM call.
        """
        outcome = self.search_engine.search(query, limit=self.retrieval_limit)

        lab_evidence = [
            result
            for result in outcome.results
            if result.item.category in LAB_CATEGORIES
            and _beyond_category_hint(result)
            and result.score >= LAB_EVIDENCE_MIN_SCORE
        ]

        # A standard the query explicitly names (e.g. "test IS 1786") is context
        # regardless of its retrieval confidence; otherwise only a confidently
        # retrieved product/standard counts.
        query_numbers = {
            value.split(":")[0] for value in find_standard_numbers(query)
        }
        standard_context: str | None = None
        for result in outcome.results:
            if (
                result.item.category != "indian_standards"
                or not result.item.standard_number
            ):
                continue
            key = standard_number_key(result.item.standard_number)
            named = bool(query_numbers) and key is not None and key[0] in query_numbers
            if named or result.confidence in {"medium", "high"}:
                standard_context = result.item.title
                break

        return lab_evidence, standard_context

    @staticmethod
    def _is_sufficient(lab_evidence: list[RetrievalResult]) -> bool:
        if len(lab_evidence) >= 2:
            return True
        if len(lab_evidence) == 1:
            return lab_evidence[0].confidence in {"medium", "high"}
        return False

    # --------------------------------------------------------------- full search

    def search(self, query: str, explain: bool = True,
               language: str = lang.AUTO,
               standard_number: str | None = None) -> LaboratorySearch:
        query = query.strip()
        # Milestone 17: language of the answer only. Retrieval sees known
        # non-English terms rewritten to canonical English; the evidence,
        # its sources and this service's own logic are unchanged.
        answer_language = lang.resolve(query, language)

        if not query:
            return LaboratorySearch(
                query="",
                standard_context=None,
                answer="Please provide a laboratory-related question.",
                grounded=False,
                confidence="none",
                sources=[],
                note="empty query",
            )

        retrieval_query = lang.normalize_query(query).query
        lab_evidence, standard_context = self.gather(retrieval_query)

        # Milestone 18: deterministic laboratory records, found BEFORE any model
        # call. The LLM never decides which laboratories are relevant.
        laboratories, lab_standard, lab_source = self.find_laboratories(
            retrieval_query, standard_number
        )

        # Matched laboratory records are evidence in their own right: a query
        # that finds them is grounded even when the prose guidance is thin.
        if not laboratories and not self._is_sufficient(lab_evidence):
            return LaboratorySearch(
                query=query,
                standard_context=standard_context,
                answer=INSUFFICIENT_EVIDENCE_ANSWER,
                grounded=False,
                confidence="none",
                sources=[],
                note=(
                    "no verified BIS laboratory or testing evidence was "
                    "retrieved for this query"
                ),
            )

        sources = _dedupe(lab_evidence)[: self.max_sources]

        if explain:
            context = _build_context(sources)
            records = _laboratory_context(laboratories)
            user_prompt = f"""Answer the user's BIS laboratory question using
ONLY the BIS evidence below.

USER QUESTION:
{query}

BIS EVIDENCE:
{context}
{records}
Give a concise, grounded answer. Name a laboratory only if it appears in the
MATCHED LABORATORY RECORDS section above, and only with the details given there.
Do not rank or recommend laboratories, and do not state accreditation or current
operational status.
"""
            answer = self.llm.generate(
                system_prompt=lang.apply(LAB_SYSTEM_PROMPT, answer_language),
                user_prompt=user_prompt,
                temperature=0.1,
            )
        else:
            answer = _deterministic_summary(sources, laboratories, lab_standard)

        return LaboratorySearch(
            query=query,
            standard_context=standard_context,
            answer=answer,
            grounded=True,
            confidence=lab_evidence[0].confidence if lab_evidence else "medium",
            sources=sources,
            note=NO_LAB_RECORDS_NOTE if not laboratories else _matched_note(self.registry),
            laboratories=laboratories,
            laboratory_standard=lab_standard,
            laboratory_standard_source=lab_source,
        )
