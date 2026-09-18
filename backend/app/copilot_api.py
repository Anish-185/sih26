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

from app.copilot import CAPABILITIES, QUESTION_MAX, InspectionCopilot
from app.db import get_session
from app.inspection import InspectionAnalysisOut
from app.openrouter import CopilotUnavailable, OpenRouterLLM
from app.records import INSPECTION_ID_PATTERN, final_result, get_inspection

router = APIRouter(prefix="/copilot", tags=["copilot"])

CapabilityLiteral = Literal[
    "EXPLAIN_INSPECTION", "SUMMARIZE", "EXPLAIN_ESCALATION", "EXPLAIN_CHECKS",
    "EXPLAIN_EVIDENCE", "EXPLAIN_UNCERTAINTY", "EXPLAIN_HALLMARK",
    "MANUAL_VERIFICATION", "QUESTION",
]

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


class CopilotRequest(BaseModel):
    """Strict: exactly one evidence source, and no field that could carry a result."""

    model_config = ConfigDict(extra="forbid")

    capability: CapabilityLiteral = "EXPLAIN_INSPECTION"
    question: str = Field(default="", max_length=QUESTION_MAX)
    inspection_id: str | None = Field(default=None, description="A saved inspection to explain.")
    analysis: InspectionAnalysisOut | None = Field(
        default=None, description="The analysis currently on screen, exactly as /inspection/analyze returned it."
    )
    rule_id: str | None = Field(default=None, max_length=80, description="Focus the answer on one check.")


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
    evidence_scope: Literal["SAVED_RECORD", "LIVE_ANALYSIS"]
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
    """Explain one finished inspection. Never decides, never writes, never recomputes."""
    if (body.inspection_id is None) == (body.analysis is None):
        raise HTTPException(
            status_code=422,
            detail="Send exactly one of 'inspection_id' (a saved inspection) or 'analysis' "
                   "(the inspection currently on screen).",
        )

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
