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

import logging
import re
from dataclasses import dataclass, field

from app import boundary as boundary_module
from app import clauses as clauses_module
from app import language as lang
from app import qco as qco_module
from app.knowledge.schema import KnowledgeItem
from app.llm import LLMError, LocalLLM
from app.openrouter import CopilotUnavailable, OpenRouterLLM
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
   procedures, or legal claims. Reproduce Indian Standard numbers, clause
   numbers and page references (for example "Clause 9, PDF page 14") exactly as
   supplied, and cite a clause only if it appears in the supplied context.
   Clause text marked as OCR comes from a scanned document and may contain
   character errors: never state a numeric limit from it as confirmed — say it
   should be checked against the named PDF page.
4. If the supplied context is insufficient, say so clearly.
5. Do not make a final legal or enforcement decision.
6. Do not claim to verify, authenticate, or state the status of a specific
   physical item (for example a particular article's HUID, hallmark, licence, or
   BIS registration). Explain what the evidence says and point the user to the
   official BIS tool or page. Never output a HUID or similar identifier that is
   not present in the supplied context.
7. Keep the answer concise and directly address the user's question.
8. A general statement from an FAQ or general BIS record (for example what a
   Quality Control Order does, or when certification is mandatory) must not be
   applied to a specific product unless a supplied record names that product or
   its standard. Being on a compulsory-certification listing and being covered by
   a Quality Control Order are different claims; state only the one the records
   make for that product.
9. Describe what a source page or document contains only by using that
   source's supplied text. Do not say a page lists, includes or provides anything
   the supplied text does not show.
10. Say a product or standard is under a Quality Control Order ONLY from a
   supplied QUALITY CONTROL ORDER RECORD for it, quoting its ministry, product
   wording, Indian Standard and enforcement date exactly as printed. That table
   lists orders due for implementation: never say the order is in force, never
   say whether an enforcement date took effect, and never say what the user's
   own item must do. The same holds for a supplied LISTING ORDER RECORD: it
   says which orders BIS's compulsory-certification listing NAMES for a product;
   quote its S.O. numbers and dates exactly, never say an order is in force or
   applies, and when the record says its cell also records a rescission,
   withdrawal, suspension or supersession, say so and do not interpret it.
11. Attribute every statement about a Quality Control Order or any other order
   to the source it comes from ("BIS's table of upcoming QCOs lists …",
   "BIS's Scheme I listing names …"). Never state it as a bare fact about the
   product ("there is a QCO for …", "X is covered by …").
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
    # Phase 8: clause text of the retrieved standards, attached only to a confident
    # answer (see app/clauses.py), and which path produced ``answer``.
    clauses: list[KnowledgeItem] = field(default_factory=list)
    fallback_reason: str = "MODEL"
    # Phase 9: Quality Control Order rows for the same confidently retrieved
    # standards clauses attach to (see app/qco.py).
    qco: list[KnowledgeItem] = field(default_factory=list)
    # Phase 9.1: the orders BIS's listing names for those same standards.
    listing_orders: list = field(default_factory=list)


logger = logging.getLogger(__name__)


class _Guard(Exception):
    """A deterministic check rejected the model's text. ``rule`` names the check."""

    def __init__(self, rule: str) -> None:
        super().__init__(rule)
        self.rule = rule


def _fallback_reason(exc: Exception) -> str:
    """MODEL | RATE_LIMITED | NOT_CONFIGURED | PROVIDER_ERROR | GUARD:<rule>."""
    if isinstance(exc, _Guard):
        return f"GUARD:{exc.rule}"
    code = getattr(exc, "code", "") if isinstance(exc, CopilotUnavailable) else ""
    if code in ("RATE_LIMITED", "DAILY_LIMIT"):
        return "RATE_LIMITED"
    if code == "NOT_CONFIGURED":
        return "NOT_CONFIGURED"
    return "PROVIDER_ERROR"


# A Quality Control Order, a ministry or a year (an enforcement date) may appear
# in an answer only when a retrieved record holds it. MetrIQ holds no QCO data
# for individual products, so "is it mandatory?" must not be answered from one.
_REGULATORY_TERMS = ("quality control order", "qco", "ministry")
_YEAR = re.compile(r"\b(?:19|20)\d{2}\b")


def unsupported_regulatory_claim(answer: str, evidence: str) -> bool:
    said, held = answer.lower(), evidence.lower()
    # BIS names these orders "… (Quality Control) Order, 2020"; that bracketed form
    # IS the phrase "quality control order" (Phase 9.1 listing cells).
    held = held.replace("(quality control) order", "quality control order")
    if any(re.search(rf"\b{t}\b", said) and not re.search(rf"\b{t}\b", held)
           for t in _REGULATORY_TERMS):
        return True
    return bool(set(_YEAR.findall(answer)) - set(_YEAR.findall(evidence)))


_QCO = re.compile(r"\bquality control orders?\b|\bqcos?\b", re.IGNORECASE)


def untied_qco_claim(answer: str, results: list[RetrievalResult],
                     context: "ConversationContext | None",
                     qco_rows: list[KnowledgeItem] | None = None,
                     listing_orders: list | None = None) -> bool:
    """A QCO named while discussing a specific product must be tied to it.

    A retrieved FAQ can hold the general QCO sentence, which the check above
    lets through; applied next to "LED bulb" it implies LED bulbs are under a
    QCO. That is allowed only when ONE retrieved record mentions a QCO AND names
    the product or one of its standard numbers — or (Phase 9) when a QCO record
    was attached, which happens only for the standards this answer is about, or
    (Phase 9.1) an order BIS's listing names for one of them.
    """
    if context is None or not _QCO.search(answer) or qco_rows or listing_orders:
        return False
    names = [context.product.lower(), *(n.lower() for n in context.standard_numbers)]
    for result in results:
        item = result.item
        text = " ".join([item.title, item.content, " ".join(item.keywords),
                         item.standard_number or ""]).lower()
        if _QCO.search(text) and any(name in text for name in names):
            return False
    return True


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


def _clause_context(attached: list[KnowledgeItem]) -> str:
    """The attached clauses, each labelled as OCR text with its reference as stored."""
    if not attached:
        return ""
    blocks = []
    for index, item in enumerate(attached, start=1):
        clause = clauses_module.view(item)
        blocks.append(
            f"""CLAUSE {index}
STANDARD: {clause["standard_number"]}
REFERENCE: {clause["reference"]}
HEADING: {clause["heading"]}
TEXT (OCR from a scanned BIS document, via the Public.Resource.Org / Internet Archive
mirror, not verified by a person):
{clause["text"]}
{clause["note"]}
SOURCE URL: {clause["source_url"]}
""")
    return ("\n\nCLAUSE TEXT OF THE RETRIEVED STANDARDS\n" + clauses_module.OCR_LABEL
            + "\n\n" + "\n---\n".join(blocks))


def _qco_context(rows: list[KnowledgeItem]) -> str:
    """The attached QCO rows, verbatim, with MetrIQ's own status sentences."""
    if not rows:
        return ""
    blocks = []
    for index, item in enumerate(rows, start=1):
        status = qco_module.status_for(item.standard_number)
        blocks.append(
            f"""QUALITY CONTROL ORDER RECORD {index}
TABLE: {item.document_name} (read on {item.last_verified})
ROW, AS PRINTED:
{item.content}
METRIQ STATUS: {status.status} — {" ".join(status.statements)}
SOURCE URL: {item.source_url}
"""
        )
    return "\n---\n" + "\n---\n".join(blocks)


def _listing_context(listings: list) -> str:
    """The orders BIS's listing names, cell verbatim, with MetrIQ's own sentences."""
    if not listings:
        return ""
    blocks = []
    for index, (number, out) in enumerate(listings, start=1):
        cells = "\n".join(f"SCHEME {g.scheme} NOTIFICATION CELL, AS PRINTED: {g.notification}"
                          for g in out.groups)
        blocks.append(
            f"""LISTING ORDER RECORD {index}
STANDARD: {number}
{cells}
METRIQ SUMMARY: {" ".join(out.statements)}
SOURCE URL: {out.groups[0].source_url}
"""
        )
    return "\n---\n" + "\n---\n".join(blocks)


def render_evidence(results: list[RetrievalResult], language: str,
                    attached: list[KnowledgeItem] | None = None,
                    qco_rows: list[KnowledgeItem] | None = None,
                    listings: list | None = None) -> str:
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

    for item in attached or []:
        clause = clauses_module.view(item)
        blocks.append("\n".join([
            f"{clause['standard_number']} — {clause['reference']}",
            clauses_module.OCR_LABEL,
            clause["text"],
            clause["note"],
            clause["source_url"],
        ]))

    for item in qco_rows or []:
        status = qco_module.status_for(item.standard_number, language)
        blocks.append("\n".join([status.label, *status.statements,
                                 item.document_name or "", item.source_url or ""]))

    for number, _ in listings or []:
        out = qco_module.listing_orders_for(number, language)
        blocks.append("\n".join([number, *out.statements, out.groups[0].source_url]))

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
            logger.info("/ask fallback_reason=ABSTAINED")
            return GroundedAnswer(
                fallback_reason="ABSTAINED",
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

        # Resolved once, before generation: the guard below needs the product.
        resolved = self.resolve_context(retrieval_text)
        # Phase 8: clause text is attached only to a confident answer, and only to
        # standards retrieval already found — it never decides which standard. A
        # standard qualifies when Product -> Standard confidently identified it, or
        # when the question names it by number: a single shared word ("solar" ->
        # solar water heaters, at medium confidence) is not enough to quote a clause.
        eligible = [r for r in outcome.results
                    if (resolved and r.item.standard_number in resolved.standard_numbers)
                    or any(reason.field == "standard_number" for reason in r.reasons)]
        confident = outcome.confidence in ("high", "medium")
        attached = clauses_module.attach(eligible, retrieval_text) if confident else []
        # Phase 9: QCO rows attach by the same rule, to the same standards.
        qco_rows = list({row.id: row for r in eligible if confident
                         for row in qco_module.qco_for(r.item.standard_number)}.values())
        # Phase 9.1: the orders BIS's listing names, same rule, same standards.
        listings = [(r.item.standard_number, found) for r in eligible if confident
                    if (found := qco_module.listing_orders_for(r.item.standard_number))]
        context = (_build_context(outcome.results) + _clause_context(attached)
                   + _qco_context(qco_rows) + _listing_context(listings))

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
            explained, fallback_reason = True, "MODEL"
            if mentions_withdrawal(answer):
                # MetrIQ has no withdrawal data: fall back to its own text.
                raise _Guard("WITHDRAWAL_CLAIM")
            if unsupported_regulatory_claim(answer, context):
                raise _Guard("UNSUPPORTED_REGULATORY_CLAIM")
            if untied_qco_claim(answer, outcome.results, resolved, qco_rows, listings):
                raise _Guard("UNTIED_QCO_CLAIM")
            if qco_module.unsupported_order_numbers(answer, context):
                # An S.O. / G.S.R. number MetrIQ never supplied, withheld like an
                # invented IS number.
                raise _Guard("UNSUPPORTED_ORDER_NUMBER")
            if clauses_module.unsupported_citations(answer, context):
                # Withheld like an invented IS number: a clause MetrIQ never supplied.
                raise _Guard("UNSUPPORTED_CLAUSE")
        except (LLMError, _Guard) as exc:
            # The provider is down, rate-limited or unconfigured. The retrieval
            # above already succeeded, so MetrIQ has the evidence and renders it
            # itself rather than failing the request. Deterministic, and
            # explicitly labelled as evidence without an AI explanation.
            answer = render_evidence(outcome.results, answer_language, attached, qco_rows, listings)
            explained, fallback_reason = False, _fallback_reason(exc)
        # Logged so a fallback is never a mystery (the Phase 6.1 re-run hit one).
        logger.log(logging.INFO if fallback_reason == "MODEL" else logging.WARNING,
                   "/ask fallback_reason=%s", fallback_reason)

        return GroundedAnswer(
            answer=answer,
            results=outcome.results,
            language=answer_language,
            concepts=normalized.concepts,
            explained=explained,
            context=resolved,
            inherited=inherited,
            clauses=attached,
            fallback_reason=fallback_reason,
            qco=qco_rows,
            listing_orders=listings,
        )
