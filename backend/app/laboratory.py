"""BIS-recognized laboratory search (Phase 7).

The curated knowledge base does NOT contain individual laboratory records
(names, addresses, recognition status, NABL numbers, IS-wise testing scope).
What it holds is verified BIS information about the Laboratory Recognition
Scheme, where BIS publishes its recognised/empanelled-laboratory lists, and the
LIMS portal for IS-wise test facilities.

So this service:

  1. runs deterministic retrieval over the `laboratories` and `testing`
     categories (Phase 3 SearchEngine, unchanged),
  2. identifies an Indian Standard / product context if the query names one,
  3. checks the evidence is strong enough to say anything useful,
  4. optionally asks the local LLM to explain ONLY that evidence,
  5. returns a structured result pointing to BIS's official laboratory
     directories.

It never names an individual laboratory, and it abstains rather than fabricate
laboratory data when no relevant evidence is retrieved.
"""

from __future__ import annotations

from dataclasses import dataclass

from app import language as lang
from app.llm import LocalLLM
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
   recognition or accreditation status, NABL numbers, supported standards, or
   testing scope. The supplied evidence does NOT name individual laboratories,
   so you must not name any laboratory.
3. You may explain, only as far as the evidence states, that BIS operates a
   Laboratory Recognition Scheme, where BIS publishes its recognised /
   empanelled-laboratory lists, and that the LIMS portal (lims.bis.gov.in)
   gives IS-wise test facilities and testing charges.
4. You explain the evidence. You do NOT make recognition or accreditation
   determinations.
5. Be concise and directly address the question.
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


def _deterministic_summary(sources: list[RetrievalResult]) -> str:
    """A plain, no-LLM answer built only from retrieved evidence titles."""
    lines = [
        "Based on official BIS information, the relevant guidance is:",
        *(f"- {r.item.title}" for r in sources),
        "",
        NO_LAB_RECORDS_NOTE,
    ]
    return "\n".join(lines)


class LaboratorySearchService:
    """Deterministic retrieval, then an optional grounded explanation."""

    def __init__(
        self,
        search_engine: SearchEngine,
        llm: LocalLLM,
        retrieval_limit: int = 10,
        max_sources: int = 6,
    ) -> None:
        self.search_engine = search_engine
        self.llm = llm
        self.retrieval_limit = retrieval_limit
        self.max_sources = max_sources

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
               language: str = lang.AUTO) -> LaboratorySearch:
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

        lab_evidence, standard_context = self.gather(lang.normalize_query(query).query)

        if not self._is_sufficient(lab_evidence):
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
            user_prompt = f"""Answer the user's BIS laboratory question using
ONLY the BIS evidence below.

USER QUESTION:
{query}

BIS EVIDENCE:
{context}

Give a concise, grounded answer. Do not name any individual laboratory; the
evidence does not contain laboratory names.
"""
            answer = self.llm.generate(
                system_prompt=lang.apply(LAB_SYSTEM_PROMPT, answer_language),
                user_prompt=user_prompt,
                temperature=0.1,
            )
        else:
            answer = _deterministic_summary(sources)

        return LaboratorySearch(
            query=query,
            standard_context=standard_context,
            answer=answer,
            grounded=True,
            confidence=lab_evidence[0].confidence,
            sources=sources,
            note=NO_LAB_RECORDS_NOTE,
        )
