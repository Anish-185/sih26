"""HTTP layer for retrieval, grounded question answering, and product discovery.

Endpoints:
  - GET /search
  - POST /search
  - POST /ask
  - POST /product-standard
  - POST /certification-guidance
  - POST /laboratory-search
"""

from __future__ import annotations

import os
import re
from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app import lab_registry
from app import language as lang
from app.boundary import Boundary
from app.certification import CertificationGuidanceService
from app.certification_journey import (
    CertificationJourneyOut,
    CertificationJourneyService,
    journey_out as _journey_out,
)
from app.laboratory import LaboratorySearchService
from app.llm import LLMError, LocalLLM
from app.lab_registry import LabRegistry, load_laboratories
from app.openrouter import DEFAULT_MODEL, OpenRouterLLM
from app.product import ProductStandardFinder
from app.product_context import ProductContextOut, build_from_query, context_out
from app.rag import BISQuestionAnswerer
from app.retrieval import RetrievalResult, SearchEngine, SearchOutcome
from app.standard_currency import CurrencyOut, currency_for

router = APIRouter(tags=["search"])


# ---------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_engine() -> SearchEngine:
    return SearchEngine()


@lru_cache(maxsize=1)
def get_grounded_llm() -> OpenRouterLLM:
    """The OpenRouter model for /ask (including Hallmarking, which has no
    dedicated endpoint) and Certification explanations. Pinned to its own
    OPENROUTER_GROUNDED_MODEL — independent of the copilot's OPENROUTER_MODEL
    (app/copilot_api.py::get_copilot()), even though they may share a value
    today. One shared instance/quota for both features."""
    return OpenRouterLLM(model=os.environ.get("OPENROUTER_GROUNDED_MODEL") or DEFAULT_MODEL)


@lru_cache(maxsize=1)
def get_answerer() -> BISQuestionAnswerer:
    return BISQuestionAnswerer(
        search_engine=get_engine(),
        llm=get_grounded_llm(),
    )


@lru_cache(maxsize=1)
def get_product_finder() -> ProductStandardFinder:
    return ProductStandardFinder(
        search_engine=get_engine(),
    )


@lru_cache(maxsize=1)
def get_certification_service() -> CertificationGuidanceService:
    return CertificationGuidanceService(
        search_engine=get_engine(),
        product_finder=get_product_finder(),
        llm=get_grounded_llm(),
    )


@lru_cache(maxsize=1)
def get_certification_journey_service() -> CertificationJourneyService:
    return CertificationJourneyService(
        search_engine=get_engine(),
        product_finder=get_product_finder(),
    )


@lru_cache(maxsize=1)
def get_lab_registry() -> LabRegistry:
    """The verified BIS LIMS snapshot, loaded once. Read-only, no network."""
    return load_laboratories()


@lru_cache(maxsize=1)
def get_laboratory_service() -> LaboratorySearchService:
    return LaboratorySearchService(
        search_engine=get_engine(),
        llm=LocalLLM(),
        # Milestone 18: product -> standard reuses the existing finder, so there
        # is no second product classifier.
        product_finder=get_product_finder(),
    )


# ---------------------------------------------------------------------
# Catalogue identity (Phase 4)
# ---------------------------------------------------------------------
#
# The catalogue title and the route its text came from are stored inside each
# record's `content` — one source of truth, no schema change. They are read back
# out here so the UI can show the provenance, which is not optional: BIS SELLS
# these standards, so text taken from a third-party mirror must never be
# presented as though it came from bis.gov.in.

_CATALOGUE_TITLE = re.compile(r'Catalogue title[^:]*:\s*"(?P<title>[^"]+)"')
_DAMAGED = "looks damaged"


class CatalogueOut(BaseModel):
    """The standard's real catalogue identity, and where the text came from."""

    title: str
    # "bis"     — BIS's own Know Your Standards catalogue (official, primary)
    # "archive" — the Public.Resource.Org mirror on the Internet Archive (fallback)
    source_route: str
    source_label: str
    official: bool
    # True when the source returned damaged text. It is shown as recorded and was
    # never repaired, so the reader can see that it is the source that is wrong.
    title_suspect: bool = False


def _catalogue_out(content: str) -> CatalogueOut | None:
    found = _CATALOGUE_TITLE.search(content or "")
    if not found:
        return None
    mirrored = "MIRROR of the Indian Standards on the Internet Archive" in content
    return CatalogueOut(
        title=found.group("title"),
        source_route="archive" if mirrored else "bis",
        source_label=(
            "Public.Resource.Org mirror on the Internet Archive — not a BIS publication"
            if mirrored else
            "BIS Know Your Standards catalogue (services.bis.gov.in)"
        ),
        official=not mirrored,
        title_suspect=_DAMAGED in content[:found.end() + 200],
    )


# ---------------------------------------------------------------------
# Coverage boundary (Phase 3)
# ---------------------------------------------------------------------

class WeakMatchOut(BaseModel):
    """A record reached by a partial word match only.

    Shown as evidence of what the search did — NEVER as an answer. Every surface
    that renders it says so.
    """

    standard_number: str | None = None
    title: str
    confidence: str
    matched_terms: list[str]
    source_url: str | None = None


class BoundaryOut(BaseModel):
    """MetrIQ's own explanation of why it did not answer.

    Written by code, in the user's language (app/language.py), never by a model.
    It never claims that no Indian Standard exists for the product.
    """

    language: str
    heading: str
    lines: list[str]
    next_step: str
    next_step_url: str
    weak_heading: str = ""
    weak_note: str = ""
    weak_matches: list[WeakMatchOut] = Field(default_factory=list)


def _boundary_out(boundary: Boundary | None) -> BoundaryOut | None:
    if boundary is None:
        return None
    return BoundaryOut(
        language=boundary.language,
        heading=boundary.heading,
        lines=boundary.lines,
        next_step=boundary.next_step,
        next_step_url=boundary.next_step_url,
        weak_heading=boundary.weak_heading,
        weak_note=boundary.weak_note,
        weak_matches=[
            WeakMatchOut(
                standard_number=match.standard_number,
                title=match.title,
                confidence=match.confidence,
                matched_terms=match.matched_terms,
                source_url=match.source_url,
            )
            for match in boundary.weak_matches
        ],
    )


# ---------------------------------------------------------------------
# Common models
# ---------------------------------------------------------------------

class ReasonOut(BaseModel):
    field: str
    term: str
    weight: float
    detail: str = ""


class ResultOut(BaseModel):
    id: str
    title: str
    category: str
    content: str
    score: float
    confidence: str
    matched_terms: list[str]
    reasons: list[ReasonOut]
    standard_number: str | None = None
    source_organization: str
    source_url: str | None = None
    document_name: str | None = None
    reference: str | None = None
    verification_status: str
    last_verified: str | None = None


class SearchResponse(BaseModel):
    query: str
    normalized_query: str
    query_terms: list[str]
    query_standard_numbers: list[str]
    confidence: str
    abstained: bool
    note: str = ""
    count: int
    results: list[ResultOut]


class SearchRequest(BaseModel):
    query: str = Field(
        default="",
        description="Natural-language question",
    )
    limit: int | None = Field(
        default=None,
        ge=1,
        le=50,
    )


# ---------------------------------------------------------------------
# Ask models
# ---------------------------------------------------------------------

class SourceOut(BaseModel):
    id: str
    title: str
    category: str
    standard_number: str | None = None
    score: float
    confidence: str
    matched_terms: list[str]
    source_organization: str
    source_url: str | None = None
    document_name: str | None = None
    reference: str | None = None
    verification_status: str
    last_verified: str | None = None


class ConversationContextIn(BaseModel):
    """Phase 6: the context an earlier /ask answer returned, echoed back.

    A WHITELIST with extra="ignore", like the copilot's feature payloads: the
    page may post the whole context object and only `product` is read. It is
    never trusted either — /ask re-derives it through Product -> Standard and
    ignores it unless the new question refers back and names nothing of its own.
    """

    model_config = ConfigDict(extra="ignore")

    product: str = Field(default="", max_length=120)


class ConversationContextOut(BaseModel):
    """What this answer resolved, for the next question to refer back to."""

    product: str
    standard_numbers: list[str] = Field(description="Exactly as stored, edition year included.")
    category: str


class AskRequest(BaseModel):
    question: str = Field(
        default="",
        description="Question about BIS standards or BIS information",
    )
    language: str = Field(
        default=lang.AUTO,
        description='Answer language: "auto" (detect from the query), "en", "hi" or "te"',
    )
    # Phase 6: optional. A request without it behaves exactly as before.
    context: ConversationContextIn | None = None


class AskResponse(BaseModel):
    question: str
    answer: str
    grounded: bool
    source_count: int
    sources: list[SourceOut]
    # Milestone 17: the language the answer is actually written in. Never
    # "auto" — always the resolved code.
    language: str = lang.EN
    # Canonical English terms the query's non-English wording was mapped to for
    # retrieval. Empty when nothing needed rewriting.
    matched_concepts: list[str] = Field(default_factory=list)
    # False when the explanation provider was unreachable and the answer is the
    # retrieved records rendered by MetrIQ's own code. The evidence and the
    # sources are unchanged; only the prose differs.
    explained: bool = True
    # Phase 3: present only when MetrIQ abstained — its own account of what the
    # verified data covers and where to look next.
    boundary: BoundaryOut | None = None
    # Phase 6: the entities this answer resolved (null on abstention or when no
    # product was confidently identified), and the product this question
    # inherited from the previous one (null when nothing was inherited).
    context: ConversationContextOut | None = None
    inherited: str | None = None


# ---------------------------------------------------------------------
# Product -> Standard models
# ---------------------------------------------------------------------

class ProductStandardRequest(BaseModel):
    product: str = Field(
        default="",
        description="Natural-language product description",
    )
    limit: int = Field(
        default=5,
        ge=1,
        le=50,
    )
    language: str = Field(
        default=lang.AUTO,
        description='Language for MetrIQ\'s own messages: "auto", "en", "hi" or "te". '
                    "Evidence is identical in every language.",
    )


class WhyOut(BaseModel):
    """Deterministic 'Why this result?' explanation (Phase 9).

    Derived from the retrieval engine's MatchReason data - no LLM involved.
    """

    standard_number: str
    strength: str
    signals: list[str]
    summary: str


class ProductStandardResultOut(BaseModel):
    id: str
    title: str
    standard_number: str
    score: float
    confidence: str
    matched_terms: list[str]
    reasons: list[ReasonOut]
    why: WhyOut
    # Phase 4: the real catalogue identity, with the route its text came from.
    catalogue: CatalogueOut | None = None
    # Phase 5: is the cited edition the newest one MetrIQ's evidence shows?
    currency: CurrencyOut | None = None
    source_organization: str
    source_url: str | None = None
    document_name: str | None = None
    reference: str | None = None
    verification_status: str
    last_verified: str | None = None


class ProductStandardResponse(BaseModel):
    product: str
    results: list[ProductStandardResultOut]
    grounded: bool
    confidence: str
    note: str = ""
    # Phase 3: present only when MetrIQ abstained.
    boundary: BoundaryOut | None = None


# ---------------------------------------------------------------------
# Certification-guidance models
# ---------------------------------------------------------------------

class CertificationGuidanceRequest(BaseModel):
    question: str = Field(
        default="",
        description="Question about BIS certification",
    )
    product: str = Field(
        default="",
        description="Optional product description to give the question context",
    )
    standard_number: str = Field(
        default="",
        description="Optional Indian Standard number to build the journey for directly",
    )
    explain: bool = Field(
        default=True,
        description="If false, skip the LLM and return the deterministic journey only",
    )
    language: str = Field(
        default=lang.AUTO,
        description='Answer language: "auto" (detect from the query), "en", "hi" or "te"',
    )


class CertificationGuidanceResponse(BaseModel):
    question: str
    product_context: str | None = None
    answer: str
    grounded: bool
    confidence: str
    source_count: int
    sources: list[SourceOut]
    note: str = ""
    journey: CertificationJourneyOut | None = None
    language: str = lang.EN


# ---------------------------------------------------------------------
# Laboratory-search models
# ---------------------------------------------------------------------

class LaboratorySearchRequest(BaseModel):
    query: str = Field(
        default="",
        description="Laboratory-related question (e.g. 'BIS recognised lab for steel')",
    )
    standard: str = Field(
        default="",
        description="Optional Indian Standard or product to give the query context",
    )
    explain: bool = Field(
        default=True,
        description="If false, skip the LLM and return a deterministic summary",
    )
    language: str = Field(
        default=lang.AUTO,
        description='Answer language: "auto" (detect from the query), "en", "hi" or "te"',
    )
    standard_number: str = Field(
        default="",
        description="Optional Indian Standard number to find laboratories for directly",
    )


class LabWhyOut(BaseModel):
    """Deterministic 'Why this laboratory?' — never a quality judgement."""

    signals: list[str]
    summary: str


class LaboratoryRecordOut(BaseModel):
    """One laboratory as BIS LIMS listed it. Every field is from the record;
    a value the record does not hold is null, never filled in."""

    lab_name: str
    osl_code: str | None = None
    city: str | None = None
    standard_as_listed: str
    product_as_listed: str | None = None
    grade_or_type: str | None = None
    # Recognition validity AS AT THE SNAPSHOT — never "currently valid".
    validity_date: str | None = None
    validity_status: str
    remark: str | None = None
    source_url: str
    source_organization: str
    document_name: str
    retrieved_on: str
    why: LabWhyOut


class LaboratoryCoverageOut(BaseModel):
    """Honest coverage of the laboratory snapshot."""

    records: int
    laboratories: int
    standards: int
    retrieved_on: str | None = None
    note: str


class LaboratorySearchResponse(BaseModel):
    query: str
    standard_context: str | None = None
    answer: str
    grounded: bool
    confidence: str
    source_count: int
    sources: list[SourceOut]
    note: str = ""
    language: str = lang.EN
    # Milestone 18 — laboratories BIS's own LIMS listing supports. Empty when
    # nothing matched; never padded.
    laboratories: list[LaboratoryRecordOut] = Field(default_factory=list)
    laboratory_count: int = 0
    laboratory_standard: str | None = None
    laboratory_standard_source: str | None = None
    other_editions: list[str] = Field(default_factory=list)
    coverage: LaboratoryCoverageOut | None = None
    no_match_note: str | None = None


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------

def _result_to_out(result: RetrievalResult) -> ResultOut:
    item = result.item

    return ResultOut(
        id=item.id,
        title=item.title,
        category=item.category,
        content=item.content,
        score=result.score,
        confidence=result.confidence,
        matched_terms=result.matched_terms,
        reasons=[
            ReasonOut(
                field=reason.field,
                term=reason.term,
                weight=reason.weight,
                detail=reason.detail,
            )
            for reason in result.reasons
        ],
        standard_number=item.standard_number,
        source_organization=item.source_organization,
        source_url=item.source_url,
        document_name=item.document_name,
        reference=item.reference,
        verification_status=item.verification_status,
        last_verified=(
            item.last_verified.isoformat()
            if item.last_verified
            else None
        ),
    )


def _outcome_to_response(
    outcome: SearchOutcome,
) -> SearchResponse:
    return SearchResponse(
        query=outcome.query,
        normalized_query=outcome.normalized_query,
        query_terms=outcome.query_terms,
        query_standard_numbers=outcome.query_standard_numbers,
        confidence=outcome.confidence,
        abstained=outcome.abstained,
        note=outcome.note,
        count=len(outcome.results),
        results=[
            _result_to_out(result)
            for result in outcome.results
        ],
    )


def _laboratory_out(match) -> LaboratoryRecordOut:
    record = match.record
    status, iso = record.validity()
    return LaboratoryRecordOut(
        lab_name=record.lab_name,
        osl_code=record.osl_code or None,
        city=record.city,
        standard_as_listed=record.standard_as_listed,
        product_as_listed=record.product_as_listed or None,
        grade_or_type=record.grade_or_type,
        validity_date=iso,
        validity_status=status,
        remark=record.remark,
        source_url=record.source_url,
        source_organization=record.source_organization,
        document_name=record.document_name,
        retrieved_on=record.retrieved_on,
        why=LabWhyOut(signals=match.why.signals, summary=match.why.summary),
    )


def _laboratory_coverage() -> LaboratoryCoverageOut:
    registry = get_laboratory_service().registry
    numbers = registry.coverage()
    return LaboratoryCoverageOut(
        records=numbers["records"],
        laboratories=numbers["laboratories"],
        standards=numbers["standards"],
        retrieved_on=numbers["retrieved_on"],
        note=lab_registry.SNAPSHOT_NOTE,
    )


def _result_to_source(
    result: RetrievalResult,
) -> SourceOut:
    item = result.item

    return SourceOut(
        id=item.id,
        title=item.title,
        category=item.category,
        standard_number=item.standard_number,
        score=result.score,
        confidence=result.confidence,
        matched_terms=result.matched_terms,
        source_organization=item.source_organization,
        source_url=item.source_url,
        document_name=item.document_name,
        reference=item.reference,
        verification_status=item.verification_status,
        last_verified=(
            item.last_verified.isoformat()
            if item.last_verified
            else None
        ),
    )


# ---------------------------------------------------------------------
# Search routes
# ---------------------------------------------------------------------

@router.get(
    "/search",
    response_model=SearchResponse,
)
def search_get(
    q: Annotated[
        str,
        Query(description="Natural-language question"),
    ] = "",
    limit: Annotated[
        int | None,
        Query(ge=1, le=50),
    ] = None,
) -> SearchResponse:
    return _outcome_to_response(
        get_engine().search(q, limit)
    )


@router.post(
    "/search",
    response_model=SearchResponse,
)
def search_post(
    request: SearchRequest,
) -> SearchResponse:
    return _outcome_to_response(
        get_engine().search(
            request.query,
            request.limit,
        )
    )


# ---------------------------------------------------------------------
# Grounded Ask route
# ---------------------------------------------------------------------

@router.post(
    "/ask",
    response_model=AskResponse,
)
def ask_post(
    request: AskRequest,
) -> AskResponse:
    question = request.question.strip()

    if not question:
        # With no question there is nothing to detect, so an explicit choice is
        # the only signal; "auto" falls back to English.
        empty_language = lang.resolve("", request.language)
        return AskResponse(
            question="",
            answer=lang.empty_question(empty_language),
            grounded=False,
            source_count=0,
            sources=[],
            language=empty_language,
        )

    # No 503 path: if the explanation provider is unreachable, the answerer
    # renders the retrieved verified records itself (app/rag.render_evidence), so
    # a provider outage degrades the prose and never the evidence.
    result = get_answerer().ask(
        question, language=request.language,
        context_product=request.context.product if request.context else None,
    )

    return AskResponse(
        question=question,
        answer=result.answer,
        grounded=bool(result.results),
        source_count=len(result.results),
        sources=[
            _result_to_source(result_item)
            for result_item in result.results
        ],
        language=result.language,
        matched_concepts=result.concepts,
        explained=result.explained,
        boundary=_boundary_out(result.boundary),
        context=ConversationContextOut(**vars(result.context)) if result.context else None,
        inherited=result.inherited,
    )


# ---------------------------------------------------------------------
# Product -> Standard route
# ---------------------------------------------------------------------

@router.post(
    "/product-standard",
    response_model=ProductStandardResponse,
)
def product_standard_post(
    request: ProductStandardRequest,
) -> ProductStandardResponse:
    product = request.product.strip()

    if not product:
        return ProductStandardResponse(
            product="",
            results=[],
            grounded=False,
            confidence="none",
            note="Please provide a product description.",
        )

    outcome = get_product_finder().find(
        product,
        limit=request.limit,
        language=lang.resolve(product, request.language),
    )

    results = [
        ProductStandardResultOut(
            id=result.item.id,
            title=result.item.title,
            standard_number=result.item.standard_number,
            score=result.score,
            confidence=result.confidence,
            matched_terms=result.matched_terms,
            reasons=[
                ReasonOut(
                    field=reason.field,
                    term=reason.term,
                    weight=reason.weight,
                    detail=reason.detail,
                )
                for reason in result.reasons
            ],
            why=WhyOut(
                standard_number=why.standard_number,
                strength=why.strength,
                signals=why.signals,
                summary=why.summary,
            ),
            catalogue=_catalogue_out(result.item.content),
            currency=currency_for(result.item.standard_number),
            source_organization=result.item.source_organization,
            source_url=result.item.source_url,
            document_name=result.item.document_name,
            reference=result.item.reference,
            verification_status=result.item.verification_status,
            last_verified=(
                result.item.last_verified.isoformat()
                if result.item.last_verified
                else None
            ),
        )
        for result, why in zip(outcome.results, outcome.explanations)
    ]

    return ProductStandardResponse(
        product=outcome.product,
        results=results,
        grounded=outcome.grounded,
        confidence=outcome.confidence,
        note=outcome.note,
        boundary=_boundary_out(outcome.boundary),
    )


# ---------------------------------------------------------------------
# Certification-guidance route
# ---------------------------------------------------------------------

@router.post(
    "/certification-guidance",
    response_model=CertificationGuidanceResponse,
)
def certification_guidance_post(
    request: CertificationGuidanceRequest,
) -> CertificationGuidanceResponse:
    question = request.question.strip()
    product = request.product.strip()
    standard_number = request.standard_number.strip()

    if not question and not standard_number:
        return CertificationGuidanceResponse(
            question="",
            product_context=None,
            answer="Please provide a question about BIS certification.",
            grounded=False,
            confidence="none",
            source_count=0,
            sources=[],
            note="empty question",
        )

    # The optional product description is appended so retrieval has more context.
    combined = f"{question} {product}".strip()

    # Milestone 16: the journey is deterministic and is built first, so it is
    # present whether or not the local model is reachable.
    # Known non-English product terms are rewritten to canonical English so the
    # deterministic journey finds the same standard it would for the English
    # question. The journey's own text stays canonical (it quotes BIS records).
    journey = get_certification_journey_service().build(
        query=lang.normalize_query(combined).query,
        standard_number=standard_number,
    )
    answer_language = lang.resolve(combined, request.language)

    if not request.explain:
        return CertificationGuidanceResponse(
            question=question,
            product_context=journey.product,
            answer=journey.message or (
                "Deterministic certification journey only — no model explanation was requested."
            ),
            grounded=journey.grounded,
            confidence="none",
            source_count=len(journey.sources),
            sources=[],
            note="explanation skipped (explain=false)",
            journey=_journey_out(journey),
            language=answer_language,
        )

    try:
        result = get_certification_service().guide(
            combined or standard_number, language=request.language
        )
    except LLMError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Explanation service unavailable: {exc}",
        ) from exc

    return CertificationGuidanceResponse(
        question=question,
        product_context=result.product_context,
        answer=result.answer,
        grounded=result.grounded,
        confidence=result.confidence,
        source_count=len(result.sources),
        sources=[_result_to_source(item) for item in result.sources],
        note=result.note,
        journey=_journey_out(journey),
        language=answer_language,
    )


# ---------------------------------------------------------------------
# Product-context route (Milestone 21)
# ---------------------------------------------------------------------

class ProductContextRequest(BaseModel):
    """Only text. MetrIQ derives every fact in the response itself."""

    model_config = ConfigDict(extra="forbid")

    product: str = Field(default="", max_length=400, description="Natural-language product description")
    standard_number: str = Field(default="", max_length=64,
                                 description="Build the context for this Indian Standard directly")


@router.post("/product-context", response_model=ProductContextOut)
def product_context_post(request: ProductContextRequest) -> ProductContextOut:
    """The canonical product context for a product that has NOT been inspected.

    SERVER-DERIVED: the request carries only text. MetrIQ runs its own existing
    retrieval, certification journey and laboratory lookup — no client-supplied
    evidence is involved, and nothing new is created. (The context of a finished
    inspection travels on the analysis itself, as `product_context`.)
    """
    product = request.product.strip()
    standard_number = request.standard_number.strip()
    if not product and not standard_number:
        raise HTTPException(
            status_code=422,
            detail="Send a product description or a standard_number to build a product context.",
        )
    return context_out(build_from_query(
        product,
        finder=get_product_finder(),
        journey_service=get_certification_journey_service(),
        registry=get_lab_registry(),
        standard_number=standard_number,
    ))


# ---------------------------------------------------------------------
# Laboratory-search route
# ---------------------------------------------------------------------

@router.post(
    "/laboratory-search",
    response_model=LaboratorySearchResponse,
)
def laboratory_search_post(
    request: LaboratorySearchRequest,
) -> LaboratorySearchResponse:
    query = request.query.strip()
    standard = request.standard.strip()
    standard_number = request.standard_number.strip()

    # A standard number on its own is a complete request: "which laboratories
    # are listed for IS 367:1993?" needs no prose query.
    if not query and not standard_number:
        return LaboratorySearchResponse(
            query="",
            standard_context=None,
            answer="Please provide a laboratory-related question.",
            grounded=False,
            confidence="none",
            source_count=0,
            sources=[],
            note="empty query",
        )

    combined = f"{query} {standard}".strip() or standard_number

    try:
        result = get_laboratory_service().search(
            combined,
            explain=request.explain,
            language=request.language,
            standard_number=standard_number or None,
        )
    except LLMError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Local LLM unavailable: {exc}",
        ) from exc

    return LaboratorySearchResponse(
        query=query,
        standard_context=result.standard_context,
        answer=result.answer,
        grounded=result.grounded,
        confidence=result.confidence,
        source_count=len(result.sources),
        sources=[_result_to_source(item) for item in result.sources],
        note=result.note,
        language=lang.resolve(combined, request.language),
        laboratories=[_laboratory_out(match) for match in result.laboratories],
        laboratory_count=len(result.laboratories),
        laboratory_standard=result.laboratory_standard,
        laboratory_standard_source=result.laboratory_standard_source,
        other_editions=get_laboratory_service().registry.other_editions(
            result.laboratory_standard
        ),
        coverage=_laboratory_coverage(),
        no_match_note=None if result.laboratories else lab_registry.NO_MATCH,
    )
