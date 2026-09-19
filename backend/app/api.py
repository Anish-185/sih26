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

from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from app import language as lang
from app.certification import CertificationGuidanceService
from app.certification_journey import (
    CertificationJourneyOut,
    CertificationJourneyService,
    journey_out as _journey_out,
)
from app.laboratory import LaboratorySearchService
from app.llm import LLMError, LocalLLM
from app.product import ProductStandardFinder
from app.rag import BISQuestionAnswerer
from app.retrieval import RetrievalResult, SearchEngine, SearchOutcome

router = APIRouter(tags=["search"])


# ---------------------------------------------------------------------
# Services
# ---------------------------------------------------------------------

@lru_cache(maxsize=1)
def get_engine() -> SearchEngine:
    return SearchEngine()


@lru_cache(maxsize=1)
def get_answerer() -> BISQuestionAnswerer:
    return BISQuestionAnswerer(
        search_engine=get_engine(),
        llm=LocalLLM(),
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
        llm=LocalLLM(),
    )


@lru_cache(maxsize=1)
def get_certification_journey_service() -> CertificationJourneyService:
    return CertificationJourneyService(
        search_engine=get_engine(),
        product_finder=get_product_finder(),
    )


@lru_cache(maxsize=1)
def get_laboratory_service() -> LaboratorySearchService:
    return LaboratorySearchService(
        search_engine=get_engine(),
        llm=LocalLLM(),
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


class AskRequest(BaseModel):
    question: str = Field(
        default="",
        description="Question about BIS standards or BIS information",
    )
    language: str = Field(
        default=lang.AUTO,
        description='Answer language: "auto" (detect from the query), "en", "hi" or "te"',
    )


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

    try:
        result = get_answerer().ask(question, language=request.language)
    except LLMError as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Local LLM unavailable: {exc}",
        ) from exc

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
            detail=f"Local LLM unavailable: {exc}",
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

    if not query:
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

    combined = f"{query} {standard}".strip()

    try:
        result = get_laboratory_service().search(
            combined, explain=request.explain, language=request.language
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
    )
