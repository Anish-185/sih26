"""BIS certification guidance (Phase 6).

This module does NOT decide what the law requires. It:

  1. identifies the product / Indian Standard the question is about, reusing the
     Phase 5 ProductStandardFinder (deterministic),
  2. retrieves certification-related BIS evidence with the Phase 3 SearchEngine
     (deterministic),
  3. checks whether that evidence is strong enough to say anything useful,
  4. only then asks the local LLM to explain ONLY that evidence,
  5. returns a structured answer together with its BIS sources.

If the knowledge base does not hold enough certification evidence, the service
abstains instead of guessing.
"""

from __future__ import annotations

from dataclasses import dataclass

from app import language as lang
from app.llm import LocalLLM
from app.product import ProductStandardFinder, ProductStandardOutcome
from app.rag import _build_context
from app.retrieval import RetrievalResult, SearchEngine

# Knowledge-base categories that carry BIS certification information.
CERT_CATEGORIES = ("certification", "faqs", "testing")

# A certification-evidence item must score at least this much in retrieval to
# count towards sufficiency. Roughly a keyword or title match plus a little more
# (keyword = 3, title = 4, category hint = 2), so a single stray generic-word
# match cannot make weak evidence look sufficient.
CERT_EVIDENCE_MIN_SCORE = 5.0

INSUFFICIENT_EVIDENCE_ANSWER = (
    "The available BIS knowledge base does not contain sufficient verified "
    "information to answer this certification question."
)

CERT_SYSTEM_PROMPT = """You are the BIS Assistant for an evidence-backed Indian
Standards information system, answering a question about BIS certification.

Rules:
1. Use ONLY the BIS evidence supplied by the application. Do not use pretrained
   knowledge as evidence.
2. Do not invent standards, schemes, clauses, fees, timelines, application
   steps, required documents, testing requirements, or legal obligations. If the
   evidence does not state something, say it is not covered by the available
   information.
3. Keep this distinction explicit: an Indian Standard existing for a product is
   NOT the same as BIS certification being mandatory. Only say certification is
   mandatory or compulsory for a product if the evidence says so.
4. You explain the evidence. You do NOT make the final legal or enforcement
   decision. Where appropriate, suggest the user confirm with BIS.
5. Be concise and directly address the question.
"""


@dataclass(frozen=True)
class CertificationGuidance:
    """The full answer to one certification question."""

    question: str
    product_context: str | None
    answer: str
    grounded: bool
    confidence: str
    sources: list[RetrievalResult]
    note: str = ""


def _beyond_category_hint(result: RetrievalResult) -> bool:
    """True when the result matched real text (title/keywords/content/standard
    number), not only a category-hint word such as 'certification'."""
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


class CertificationGuidanceService:
    """Deterministic evidence gathering, then grounded local generation."""

    def __init__(
        self,
        search_engine: SearchEngine,
        product_finder: ProductStandardFinder,
        llm: LocalLLM,
        retrieval_limit: int = 10,
        max_sources: int = 6,
    ) -> None:
        self.search_engine = search_engine
        self.product_finder = product_finder
        self.llm = llm
        self.retrieval_limit = retrieval_limit
        self.max_sources = max_sources

    # ---------------------------------------------------------- evidence (no LLM)

    def gather(
        self, question: str
    ) -> tuple[list[RetrievalResult], ProductStandardOutcome]:
        """Retrieve certification evidence and product/standard context.

        Deterministic. No LLM call. Separated out so the abstention decision can
        be tested on its own.
        """
        outcome = self.search_engine.search(question, limit=self.retrieval_limit)
        cert_evidence = [
            result
            for result in outcome.results
            if result.item.category in CERT_CATEGORIES
            and _beyond_category_hint(result)
            and result.score >= CERT_EVIDENCE_MIN_SCORE
        ]
        product_outcome = self.product_finder.find(question)
        return cert_evidence, product_outcome

    @staticmethod
    def _is_sufficient(
        cert_evidence: list[RetrievalResult], product_grounded: bool
    ) -> bool:
        if len(cert_evidence) >= 2:
            return True
        if len(cert_evidence) == 1:
            return (
                cert_evidence[0].confidence in {"medium", "high"}
                or product_grounded
            )
        return False

    @staticmethod
    def _confidence(
        cert_evidence: list[RetrievalResult], product_grounded: bool
    ) -> str:
        if not cert_evidence:
            return "none"
        if product_grounded and len(cert_evidence) >= 2:
            return "high"
        if len(cert_evidence) >= 2 or product_grounded:
            return "medium"
        return "low"

    # --------------------------------------------------------------- full guide

    def guide(self, question: str, language: str = lang.AUTO) -> CertificationGuidance:
        question = question.strip()
        # Milestone 17: language of the explanation only. The deterministic
        # certification journey, its quotes and its sources stay canonical.
        answer_language = lang.resolve(question, language)

        if not question:
            return CertificationGuidance(
                question="",
                product_context=None,
                answer="Please provide a question about BIS certification.",
                grounded=False,
                confidence="none",
                sources=[],
                note="empty question",
            )

        cert_evidence, product_outcome = self.gather(lang.normalize_query(question).query)
        product_context = (
            product_outcome.results[0].item.title
            if product_outcome.grounded and product_outcome.results
            else None
        )

        if not self._is_sufficient(cert_evidence, product_outcome.grounded):
            return CertificationGuidance(
                question=question,
                product_context=product_context,
                answer=INSUFFICIENT_EVIDENCE_ANSWER,
                grounded=False,
                confidence="none",
                sources=_dedupe(
                    list(product_outcome.results) + cert_evidence
                )[: self.max_sources],
                note=(
                    "not enough certification-specific BIS evidence was "
                    "retrieved to answer this reliably"
                ),
            )

        # Product/standard records first (their content states whether the
        # product is under compulsory certification), then the process evidence.
        sources = _dedupe(
            list(product_outcome.results) + cert_evidence
        )[: self.max_sources]
        context = _build_context(sources)

        user_prompt = f"""Answer the user's BIS certification question using ONLY
the BIS evidence below.

USER QUESTION:
{question}

BIS EVIDENCE:
{context}

Give a concise, grounded answer. If the evidence does not confirm whether
certification is mandatory for this specific product, say so explicitly.
"""

        answer = self.llm.generate(
            system_prompt=lang.apply(CERT_SYSTEM_PROMPT, answer_language),
            user_prompt=user_prompt,
            temperature=0.1,
        )

        note = ""
        if product_context is None:
            note = (
                "No specific product or Indian Standard was confidently "
                "identified from the question; this is general BIS certification "
                "information."
            )

        return CertificationGuidance(
            question=question,
            product_context=product_context,
            answer=answer,
            grounded=True,
            confidence=self._confidence(cert_evidence, product_outcome.grounded),
            sources=sources,
            note=note,
        )
