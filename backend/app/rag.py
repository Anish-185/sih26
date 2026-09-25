"""Grounded BIS question answering.

Retrieval remains deterministic and is performed by SearchEngine.
The LLM only receives the retrieved BIS context.

Milestone 17 — the answer can be written in English, Hindi or Telugu. The
language layer (``app/language.py``) sits AROUND this pipeline, never inside it:
it rewrites known non-English product and BIS terms into canonical English
before retrieval, and appends a language clause to the system prompt afterwards.
The knowledge base, the retrieval engine, its scoring and the evidence objects
are untouched — the language of interaction changes, the source of truth does not.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app import boundary as boundary_module
from app import language as lang
from app.llm import LLMError, LocalLLM
from app.openrouter import OpenRouterLLM
from app.product import ProductStandardFinder
from app.retrieval import RetrievalResult, SearchEngine
from app.retrieval.text import tokenize
from app.standard_currency import mentions_withdrawal


SYSTEM_PROMPT = """You are the BIS Assistant for an evidence-backed Indian
Standards information system.

Rules:
1. Answer ONLY using the BIS context supplied by the application.
2. Do not use pretrained knowledge as evidence.
3. Do not invent standards, clauses, requirements, dates, numbers, fees,
   procedures, or legal claims.
4. If the supplied context is insufficient, say so clearly.
5. Do not make a final legal or enforcement decision.
6. Do not claim to verify, authenticate, or state the status of a specific
   physical item (for example a particular article's HUID, hallmark, licence, or
   BIS registration). Explain what the evidence says and point the user to the
   official BIS tool or page. Never output a HUID or similar identifier that is
   not present in the supplied context.
7. Keep the answer concise and directly address the user's question.
"""


@dataclass(frozen=True)
class ConversationContext:
    """Phase 6: what an answer resolved, so a follow-up can refer back to it.

    Derived by MetrIQ from its own Product -> Standard retrieval; never by a
    model. Several standards are carried exactly as stored and never narrowed:
    only the product phrase is inherited, so MetrIQ never picks one for the user.
    """

    product: str                  # the product phrase the retrieval matched
    standard_numbers: list[str]   # as stored, edition year included where present
    category: str                 # knowledge-base category of those records


@dataclass(frozen=True)
class GroundedAnswer:
    answer: str
    results: list[RetrievalResult]
    # Milestone 17: the language the answer is written in ("en" / "hi" / "te"),
    # after an explicit request or deterministic detection.
    language: str = lang.EN
    # The canonical English terms the query's non-English wording was mapped to
    # for retrieval. Empty when nothing needed rewriting.
    concepts: list[str] = field(default_factory=list)
    # False when the explanation provider was unreachable and MetrIQ rendered the
    # retrieved records itself (see `render_evidence`). The evidence is the same
    # either way; only the prose around it differs.
    explained: bool = True
    # Phase 3: on abstention, MetrIQ's own explanation of its coverage boundary.
    # None whenever there is an answer.
    boundary: boundary_module.Boundary | None = None
    # Phase 6: what this answer resolved (None on abstention or when no product
    # was confidently identified), and the product inherited from the previous
    # question, if any.
    context: ConversationContext | None = None
    inherited: str | None = None


# A Quality Control Order, a ministry or a year (an enforcement date) may appear
# in an answer only when a retrieved record holds it. MetrIQ holds no QCO data
# for individual products, so "is it mandatory?" must not be answered from one.
_REGULATORY_TERMS = ("quality control order", "qco", "ministry")
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")


def unsupported_regulatory_claim(answer: str, evidence: str) -> bool:
    said, held = answer.lower(), evidence.lower()
    if any(re.search(rf"\b{t}\b", said) and not re.search(rf"\b{t}\b", held)
           for t in _REGULATORY_TERMS):
        return True
    return bool(set(_YEAR.findall(answer)) - set(_YEAR.findall(evidence)))


def _build_context(results: list[RetrievalResult]) -> str:
    blocks: list[str] = []

    for index, result in enumerate(results, start=1):
        item = result.item

        blocks.append(
            f"""SOURCE {index}
ID: {item.id}
TITLE: {item.title}
CATEGORY: {item.category}
STANDARD: {item.standard_number or "N/A"}

CONTENT:
{item.content}

SOURCE ORGANIZATION: {item.source_organization}
DOCUMENT: {item.document_name or "N/A"}
REFERENCE: {item.reference or "N/A"}
VERIFICATION STATUS: {item.verification_status}
SOURCE URL: {item.source_url or "N/A"}
"""
        )

    return "\n---\n".join(blocks)


def render_evidence(results: list[RetrievalResult], language: str) -> str:
    """The retrieved records as plain prose, written by MetrIQ's own code.

    Used when the explanation provider is unreachable. No model is involved, so
    there is nothing to invent: every line below is either MetrIQ's own fixed
    sentence (translated, like the abstention message) or a field copied
    verbatim out of a verified record. Record text stays in its stored English —
    the knowledge base is never translated.
    """
    blocks = [lang.evidence_only(language)]

    for index, result in enumerate(results, start=1):
        item = result.item
        heading = f"{index}. {item.title}"
        if item.standard_number:
            heading = f"{index}. {item.standard_number} — {item.title}"

        trail = " · ".join(
            part for part in (
                item.source_organization,
                item.document_name,
                item.source_url,
            ) if part
        )
        blocks.append("\n".join(part for part in (heading, item.content, trail) if part))

    return "\n\n".join(blocks)


class BISQuestionAnswerer:
    """Deterministic retrieval followed by grounded generation.

    ``llm`` is injected — any client exposing ``generate(system_prompt=, user_prompt=)``
    works (``LocalLLM``/LM Studio, ``OpenRouterLLM``, or a test stub). This module
    never decides which provider to use; the caller does (see ``app/api.py``).
    """

    def __init__(
        self,
        search_engine: SearchEngine,
        llm: LocalLLM | OpenRouterLLM,
        retrieval_limit: int = 5,
    ) -> None:
        self.search_engine = search_engine
        self.llm = llm
        self.retrieval_limit = retrieval_limit
        # Counted once from the loaded knowledge base (see app/boundary.py).
        self.coverage = boundary_module.measure(search_engine.items)
        self.product_finder = ProductStandardFinder(search_engine)

    def resolve_context(self, text: str) -> ConversationContext | None:
        """The product this text confidently names, from Product -> Standard.

        Only a grounded high/medium outcome counts: an abstention, a coverage
        boundary and its weak matches never become context ("solar panel" must
        not hand "solar water heater" to the next question). The phrase is the
        text's own words that the top standard matched in its title or keywords.
        """
        outcome = self.product_finder.find(text)
        if not outcome.grounded or outcome.confidence not in ("high", "medium"):
            return None
        top = outcome.results[0]
        terms = {r.term for r in top.reasons if r.field in ("title", "keywords")}
        words: list[str] = []
        for word in re.findall(r"[A-Za-z0-9]+", text):
            # A process word ("testing", "compulsory") is never the product.
            if (word.lower() in terms and word.lower() not in lang.FOLLOW_UP_WORDS
                    and word.lower() not in (w.lower() for w in words)):
                words.append(word)
        if not words:
            return None
        return ConversationContext(
            product=" ".join(words),
            standard_numbers=[r.item.standard_number for r in outcome.results],
            category=top.item.category,
        )

    def _inherit(self, question: str, normalized: lang.Normalized,
                 context_product: str | None) -> str | None:
        """A fixed rule, not a judgement: inherit only when the question refers
        back AND names nothing of its own. Any leftover word (a known product, an
        unknown one like "shampoo", a city) means the context is ignored."""
        product = (context_product or "").strip()[:80]
        if not product or not lang.refers_back(question):
            return None
        # FILLER too: normalize_query keeps an all-filler question unchanged.
        if [t for t in tokenize(normalized.query)
                if t not in lang.FOLLOW_UP_WORDS and t not in lang.FILLER]:
            return None
        if lang.native_leftovers(normalized.query):
            return None
        # The client echoed this back; re-derive it rather than trust it.
        validated = self.resolve_context(product)
        return validated.product if validated else None

    def ask(self, question: str, language: str = lang.AUTO,
            context_product: str | None = None) -> GroundedAnswer:
        # The language to answer in. An explicit choice wins; "auto" detects the
        # script. This never affects which evidence is retrieved.
        answer_language = lang.resolve(question, language)

        # Retrieval sees known Hindi / Telugu terms rewritten to their canonical
        # English, because the retrieval normalizer is ASCII-only. Everything
        # else reaches retrieval exactly as the user typed it.
        normalized = lang.normalize_query(question)

        # Phase 6: a follow-up ("is it mandatory?") gets the previous product
        # added to its RETRIEVAL text only — the question itself is untouched.
        inherited = self._inherit(question, normalized, context_product)
        # An inheriting question names nothing of its own (that is the rule), so
        # its retrieval text is the product plus the follow-up words it asked with.
        retrieval_text = (" ".join([inherited, *(t for t in tokenize(normalized.query)
                                                 if t in lang.FOLLOW_UP_WORDS)])
                          if inherited else normalized.query)

        outcome = self.search_engine.search(
            retrieval_text,
            limit=self.retrieval_limit,
        )

        # Retrieval abstention means the LLM receives no context. Rather than a
        # dead end, MetrIQ states its own boundary: what the verified data covers,
        # what the search did, and where to look next (app/boundary.py).
        if outcome.abstained or not outcome.results:
            return GroundedAnswer(
                answer=lang.insufficient(answer_language),
                results=[],
                language=answer_language,
                concepts=normalized.concepts,
                boundary=boundary_module.explain(
                    question, self.coverage, answer_language,
                    weak_matches=boundary_module.weak_matches_from(outcome.results),
                ),
                inherited=inherited,
            )

        context = _build_context(outcome.results)

        # The model sees the question exactly as the user wrote it — the
        # rewritten form is for retrieval only.
        user_prompt = f"""Answer the user's question using ONLY the BIS evidence
below.

USER QUESTION:
{question}
{f"(The question refers to {inherited}, from the user's previous question.){chr(10)}" if inherited else ""}
BIS EVIDENCE:
{context}

Give a concise answer grounded in the supplied evidence.
"""

        try:
            answer = self.llm.generate(
                # Adds nothing for English, so English behaviour is unchanged.
                system_prompt=lang.apply(SYSTEM_PROMPT, answer_language),
                user_prompt=user_prompt,
                temperature=0.1,
            )
            explained = True
            if mentions_withdrawal(answer):
                # MetrIQ has no withdrawal data: fall back to its own text.
                raise LLMError("the explanation claimed a withdrawal")
            if unsupported_regulatory_claim(answer, context):
                raise LLMError("the explanation named an order, ministry or date not in the evidence")
        except LLMError:
            # The provider is down, rate-limited or unconfigured. The retrieval
            # above already succeeded, so MetrIQ has the evidence and renders it
            # itself rather than failing the request. Deterministic, and
            # explicitly labelled as evidence without an AI explanation.
            answer = render_evidence(outcome.results, answer_language)
            explained = False

        return GroundedAnswer(
            answer=answer,
            results=outcome.results,
            language=answer_language,
            concepts=normalized.concepts,
            explained=explained,
            context=self.resolve_context(retrieval_text),
            inherited=inherited,
        )
