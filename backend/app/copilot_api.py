"""HTTP layer for the MetrIQ Copilot — the optional grounded explanation layer.

    GET  /copilot/status    is the explanation service configured, and how much
                            of the free daily / per-minute budget is left?
                            (never returns the API key or any part of it)
    POST /copilot/explain   explain ONE finished inspection — either a saved one
                            (`inspection_id`) or the one currently on screen
                            (`analysis`). One user action -> one provider call.

Read-only by construction:
  * the database session is rolled back and never committed;
  * nothing is recomputed — the analysis is read as it was stored;
  * the system result in the response is the record's, never the model's.

A failure here is never a compliance failure: the endpoint returns 429 (free-tier
limit) or 503 (not configured / provider down) with a short message, and every
other part of MetrIQ keeps working.
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app import language as lang
from app.copilot import CAPABILITIES, FEATURE_CAPABILITIES, QUESTION_MAX, InspectionCopilot
from app.certification_journey import CertificationJourneyOut
from app.db import get_session
from app.inspection import InspectionAnalysisOut
from app.openrouter import CopilotUnavailable, OpenRouterLLM
from app.product_context import ProductContextOut
from app.records import INSPECTION_ID_PATTERN, final_result, get_inspection

router = APIRouter(prefix="/copilot", tags=["copilot"])

CapabilityLiteral = Literal[
    "EXPLAIN_INSPECTION", "SUMMARIZE", "EXPLAIN_ESCALATION", "EXPLAIN_CHECKS",
    "EXPLAIN_EVIDENCE", "EXPLAIN_UNCERTAINTY", "EXPLAIN_HALLMARK",
    "EXPLAIN_CERTIFICATION", "EXPLAIN_RESULT", "WHAT_IS_MISSING",
    "EXPLAIN_STANDARD", "EXPLAIN_LABORATORY", "EXPLAIN_PRODUCT_CONTEXT",
    "MANUAL_VERIFICATION", "QUESTION",
]

LanguageLiteral = Literal["auto", "en", "hi", "te"]

# 429 for "come back later", 503 for "the service is not usable right now".
_STATUS_CODE = {"DAILY_LIMIT": 429, "RATE_LIMITED": 429}

_DB_UNAVAILABLE = "The inspection database is unavailable. Check that PostgreSQL is running and migrated."


@lru_cache(maxsize=1)
def get_copilot() -> InspectionCopilot:
    """One copilot per process, so the free-tier usage counter is shared."""
    return InspectionCopilot(OpenRouterLLM())


# ------------------------------------------------------------------- models


class CapabilityOut(BaseModel):
    code: str
    label: str
    question: str


class CopilotStatusOut(BaseModel):
    configured: bool = Field(description="True when the server has an API key. The key is never returned.")
    provider: str
    model: str
    daily_limit: int
    daily_used: int
    daily_remaining: int
    minute_limit: int
    minute_remaining: int
    capabilities: list[CapabilityOut]
    note: str


# ---------------------------------------------------- feature contexts (M20)
#
# A feature page (Standards, Certification, Laboratories) sends back the result
# MetrIQ itself produced, so the copilot can explain it. Each model below is a
# WHITELIST with extra="ignore": the page may post its whole response object,
# and only these fields ever reach the model. Nothing is recomputed and nothing
# from these payloads can change a stored result — there is none here.

class _Loose(BaseModel):
    model_config = ConfigDict(extra="ignore")


class StandardWhyIn(_Loose):
    strength: str = ""
    signals: list[str] = Field(default_factory=list)
    summary: str = ""


class StandardCandidateIn(_Loose):
    id: str = ""
    title: str = ""
    standard_number: str = ""
    confidence: str = ""
    matched_terms: list[str] = Field(default_factory=list)
    why: StandardWhyIn | None = None
    source_url: str | None = None
    document_name: str | None = None
    reference: str | None = None
    verification_status: str = ""


class StandardContextIn(_Loose):
    """A /product-standard response, as the Standards page received it."""

    product: str = ""
    confidence: str = ""
    note: str = ""
    results: list[StandardCandidateIn] = Field(default_factory=list, max_length=20)


class CertificationContextIn(_Loose):
    """A /certification-guidance response. The model's own prose is NOT sent —
    only the deterministic journey, which is what the evidence is."""

    question: str = ""
    product_context: str | None = None
    journey: CertificationJourneyOut | None = None


class LabWhyIn(_Loose):
    signals: list[str] = Field(default_factory=list)
    summary: str = ""


class LabRecordIn(_Loose):
    lab_name: str = ""
    osl_code: str | None = None
    city: str | None = None
    standard_as_listed: str = ""
    product_as_listed: str | None = None
    grade_or_type: str | None = None
    validity_date: str | None = None
    validity_status: str = ""
    remark: str | None = None
    source_url: str = ""
    document_name: str = ""
    retrieved_on: str = ""
    why: LabWhyIn | None = None


class LabCoverageIn(_Loose):
    records: int = 0
    laboratories: int = 0
    standards: int = 0
    retrieved_on: str | None = None
    note: str = ""


class LaboratoryContextIn(_Loose):
    """A /laboratory-search response, as the Laboratories page received it."""

    query: str = ""
    laboratory_standard: str | None = None
    laboratory_standard_source: str | None = None
    other_editions: list[str] = Field(default_factory=list, max_length=20)
    coverage: LabCoverageIn | None = None
    no_match_note: str | None = None
    laboratories: list[LabRecordIn] = Field(default_factory=list, max_length=50)


class FeatureContextIn(BaseModel):
    """Exactly one feature payload, matching `feature`."""

    model_config = ConfigDict(extra="forbid")

    feature: Literal["STANDARD", "CERTIFICATION", "LABORATORY", "PRODUCT"]
    standard: StandardContextIn | None = None
    certification: CertificationContextIn | None = None
    laboratory: LaboratoryContextIn | None = None
    # Milestone 21: MetrIQ's own canonical product context, exactly as
    # POST /product-context or an analysis returned it. Reusing the response
    # model IS the whitelist — an unknown field is dropped before it can reach
    # the model, and a malformed one is a 422.
    product: ProductContextOut | None = None

    def payload(self) -> dict | None:
        chosen = {"STANDARD": self.standard, "CERTIFICATION": self.certification,
                  "LABORATORY": self.laboratory, "PRODUCT": self.product}[self.feature]
        return None if chosen is None else chosen.model_dump(mode="json")


class CopilotRequest(BaseModel):
    """Strict: exactly one evidence source, and no field that could carry a result."""

    model_config = ConfigDict(extra="forbid")

    capability: CapabilityLiteral = "EXPLAIN_INSPECTION"
    question: str = Field(default="", max_length=QUESTION_MAX)
    inspection_id: str | None = Field(default=None, description="A saved inspection to explain.")
    analysis: InspectionAnalysisOut | None = Field(
        default=None, description="The analysis currently on screen, exactly as /inspection/analyze returned it."
    )
    context: FeatureContextIn | None = Field(
        default=None,
        description="Milestone 20: a feature page's own deterministic result (product -> standard, a "
                    "certification journey, or a laboratory lookup) to explain instead of an inspection.",
    )
    rule_id: str | None = Field(default=None, max_length=80, description="Focus the answer on one check.")
    language: LanguageLiteral = Field(
        default="auto",
        description='Answer language: "auto" (detect from the question), "en", "hi" or "te". '
                    "The evidence itself is never translated.",
    )


class EvidenceItemOut(BaseModel):
    claim: str
    source: str


class CopilotSourceOut(BaseModel):
    title: str
    authority: str
    reference: str | None = None
    quote: str | None = None
    document_name: str | None = None
    source_url: str | None = None


class CopilotResponseOut(BaseModel):
    capability: str
    question: str
    evidence_scope: Literal["SAVED_RECORD", "LIVE_ANALYSIS", "FEATURE_CONTEXT"]
    context_type: str = Field(
        default="INSPECTION",
        description="INSPECTION, or the feature whose deterministic result was explained.",
    )
    language: str = Field(default=lang.EN, description="The language the answer is written in.")
    confidence: str = Field(
        default="GROUNDED",
        description="Deterministic, computed by MetrIQ: GROUNDED, UNSTRUCTURED (the model did not "
                    "return structured evidence) or WITHHELD (MetrIQ rejected the generated text). "
                    "Never a self-assessment by the model.",
    )
    inspection_id: str | None
    system_result: str | None = Field(
        description="The deterministic result, read from the record. The explanation cannot change it."
    )
    escalation_required: bool | None
    officer_status: str | None = None
    answer: str
    evidence: list[EvidenceItemOut]
    limitations: list[str]
    sources: list[CopilotSourceOut] = Field(
        description="Verified sources taken from the inspection evidence, not from the generated text."
    )
    grounded: bool = True
    withheld: bool = Field(description="True when MetrIQ rejected the generated text.")
    withheld_reason: str = ""
    structured: bool
    model: str
    usage: dict


# ------------------------------------------------------------------ endpoints


@router.get("/status", response_model=CopilotStatusOut)
def status(copilot: InspectionCopilot = Depends(get_copilot)) -> CopilotStatusOut:
    """What the UI needs to decide whether to offer an explanation. No secrets."""
    state = copilot.status()
    return CopilotStatusOut(
        **state,
        capabilities=[
            CapabilityOut(code=code, label=spec["label"], question=spec["question"])
            for code, spec in CAPABILITIES.items()
        ],
        note=(
            "Explanations are optional and generated only when you ask for one. Every inspection "
            "result, check and source on this site is produced by MetrIQ's deterministic engine."
            if state["configured"]
            else "No explanation service is configured on this server. Every inspection result "
                 "remains available."
        ),
    )


@router.post("/explain", response_model=CopilotResponseOut)
def explain(
    body: CopilotRequest,
    copilot: InspectionCopilot = Depends(get_copilot),
    session: Session = Depends(get_session),
) -> CopilotResponseOut:
    """Explain one finished result. Never decides, never writes, never recomputes."""
    given = [f for f in (body.inspection_id, body.analysis, body.context) if f is not None]
    if len(given) != 1:
        raise HTTPException(
            status_code=422,
            detail="Send exactly one of 'inspection_id' (a saved inspection), 'analysis' (the "
                   "inspection currently on screen) or 'context' (a feature page's result).",
        )

    if body.context is not None:
        return _explain_feature(body, copilot)

    record: dict | None = None
    if body.inspection_id is not None:
        if not INSPECTION_ID_PATTERN.match(body.inspection_id):
            raise HTTPException(
                status_code=422,
                detail=f"'{body.inspection_id}' is not a valid inspection id (INS-YYYYMMDD-XXXXXX).",
            )
        try:
            row = get_inspection(session, body.inspection_id)
            if row is None:
                raise HTTPException(status_code=404, detail=f"Inspection {body.inspection_id} was not found.")
            record = {
                "inspection_id": row.inspection_id,
                "system_result": row.system_result,
                "escalation_required": row.escalation_required,
                "officer_status": row.officer_status,
                "officer_decision": row.officer_decision,
                "officer_result": row.officer_result,
                "officer_note": row.officer_note,
                "final_result": final_result(row),
            }
            analysis = dict(row.analysis)
        except SQLAlchemyError as exc:
            session.rollback()
            raise HTTPException(status_code=503, detail=_DB_UNAVAILABLE) from exc
        finally:
            # Read-only: an explanation must never persist anything.
            session.rollback()
    else:
        analysis = body.analysis.model_dump(mode="json")

    try:
        result = copilot.explain(
            analysis,
            body.capability,
            question=body.question,
            record=record,
            rule_id=body.rule_id,
            language=body.language,
        )
    except CopilotUnavailable as exc:
        raise HTTPException(
            status_code=_STATUS_CODE.get(exc.code, 503),
            detail=str(exc),
            headers={"X-Copilot-Reason": exc.code},
        ) from exc

    return CopilotResponseOut(
        capability=result.capability,
        question=result.question,
        evidence_scope="SAVED_RECORD" if record else "LIVE_ANALYSIS",
        context_type=result.context_type,
        language=result.language,
        confidence=result.confidence,
        inspection_id=analysis.get("inspection_id"),
        system_result=result.system_result,
        escalation_required=result.escalation_required,
        officer_status=(record or {}).get("officer_status"),
        answer=result.answer.answer,
        evidence=[EvidenceItemOut(**e) for e in result.answer.evidence],
        limitations=result.answer.limitations,
        sources=[CopilotSourceOut(**s) for s in result.sources],
        withheld=result.answer.withheld,
        withheld_reason=result.answer.withheld_reason,
        structured=result.answer.structured,
        model=result.model,
        usage=copilot.status(),
    )


def _explain_feature(body: CopilotRequest, copilot: InspectionCopilot) -> CopilotResponseOut:
    """Explain a feature page's deterministic result (Milestone 20).

    No database, no inspection, no system result: the evidence is the response
    MetrIQ's own deterministic retrieval produced, narrowed by the request model.
    """
    feature = body.context.feature
    payload = body.context.payload()
    if payload is None:
        raise HTTPException(
            status_code=422,
            detail=f"context.feature is '{feature}', so context.{feature.lower()} must be supplied.",
        )
    if body.capability not in FEATURE_CAPABILITIES[feature]:
        raise HTTPException(
            status_code=422,
            detail=f"capability '{body.capability}' cannot be asked of a {feature} context "
                   f"(allowed: {', '.join(FEATURE_CAPABILITIES[feature])}).",
        )

    try:
        result = copilot.explain_feature(
            feature,
            payload,
            body.capability,
            question=body.question,
            language=body.language,
        )
    except CopilotUnavailable as exc:
        raise HTTPException(
            status_code=_STATUS_CODE.get(exc.code, 503),
            detail=str(exc),
            headers={"X-Copilot-Reason": exc.code},
        ) from exc

    return CopilotResponseOut(
        capability=result.capability,
        question=result.question,
        evidence_scope="FEATURE_CONTEXT",
        context_type=result.context_type,
        language=result.language,
        confidence=result.confidence,
        inspection_id=None,
        system_result=None,
        escalation_required=None,
        officer_status=None,
        answer=result.answer.answer,
        evidence=[EvidenceItemOut(**e) for e in result.answer.evidence],
        limitations=result.answer.limitations,
        sources=[CopilotSourceOut(**s) for s in result.sources],
        withheld=result.answer.withheld,
        withheld_reason=result.answer.withheld_reason,
        structured=result.answer.structured,
        model=result.model,
        usage=copilot.status(),
    )
