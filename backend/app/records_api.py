"""HTTP layer for persisted inspections and the officer review.

    POST /inspections                       multipart, same package form as /inspection/analyze
                                            (image | images + sides). The backend runs the analysis
                                            itself and saves it — a client never sends a result.
    GET  /inspections                       newest first; ?officer_status=PENDING&officer_status=IN_REVIEW
                                            (officer_status NOT_REQUIRED = resolved by the system, never queued)
    GET  /inspections/stats                 counts from the database (system results and officer
                                            review states counted separately)
    GET  /inspections/{inspection_id}       the full record: system result + analysis + officer review
    GET  /inspections/{inspection_id}/images/{index}   a stored package photo (1-based upload order)
    GET  /inspections/{inspection_id}/report.pdf       evidence-backed PDF report of the saved record (read-only)
    POST /inspections/{inspection_id}/review           JSON: {"action": "START"} or
                                            {"action": "COMPLETE", "decision": ..., "officer_result": ..., "note": ...}

The review body is strict (unknown fields are rejected), so a request that tries
to send ``system_result`` or any other system field gets 422. The database
refuses changes to the system columns as well.
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import partial
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, Query, Request, Response, UploadFile
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import get_session
from app.report import render_report
from app.inspection import EscalationReasonOut, InspectionAnalysisOut, InspectionAnalyzer
from app.inspection_api import _package, _run, get_analyzer
from app.records import (
    INSPECTION_ID_PATTERN,
    NOTE_MAX,
    InspectionRecord,
    ReviewAction,
    ReviewError,
    apply_review,
    create_inspection,
    final_result,
    get_image,
    get_inspection,
    list_inspections,
    statistics,
)

router = APIRouter(prefix="/inspections", tags=["inspections"])

ResultLiteral = Literal["PASS", "FAIL", "REVIEW"]
OfficerStatusLiteral = Literal["NOT_REQUIRED", "PENDING", "IN_REVIEW", "COMPLETED"]
_PACKAGE_FIELDS = {"image", "side", "images", "sides", "inspection_type", "huid_reference"}
_DB_UNAVAILABLE = "The inspection database is unavailable. Check that PostgreSQL is running and migrated."


# ------------------------------------------------------------------ models


class SystemReasonOut(BaseModel):
    source: Literal["BIS", "LEGAL_METROLOGY", "HALLMARKING"]
    result: ResultLiteral
    reason_code: str
    reason: str


class StoredImageOut(BaseModel):
    index: int
    image_id: str
    side: str
    filename: str
    content_type: str
    url: str = Field(description="Path of the stored photo, relative to the API root.")


class InspectionSummaryOut(BaseModel):
    inspection_id: str
    created_at: datetime
    product_status: str
    product_name: str | None
    product_category: str | None
    standard_number: str | None
    bis_result: ResultLiteral
    legal_metrology_result: ResultLiteral
    system_result: ResultLiteral = Field(description="Deterministic result when saved. Never changed by a review.")
    escalation_required: bool = Field(description="False: the system resolved the case and its result is final.")
    escalation_reasons: list[EscalationReasonOut] = Field(description="Why the system could not resolve it.")
    officer_status: OfficerStatusLiteral = Field(
        description="NOT_REQUIRED (resolved by the system) | PENDING (in the officer queue) | IN_REVIEW | COMPLETED"
    )
    officer_decision: Literal["ACCEPT_SYSTEM_RESULT", "OVERRIDE", "MANUAL_REVIEW"] | None
    officer_result: ResultLiteral | None = Field(description="Set only by an OVERRIDE.")
    final_result: Literal["PASS", "FAIL", "REVIEW", "MANUAL_REVIEW"] | None = Field(
        description="The system result when no review was required; otherwise what the completed officer "
        "review concluded, null until it is completed."
    )
    review_started_at: datetime | None
    review_completed_at: datetime | None
    image_count: int
    sides: list[str]


class InspectionRecordOut(InspectionSummaryOut):
    system_reasons: list[SystemReasonOut]
    officer_note: str | None
    images: list[StoredImageOut]
    analysis: InspectionAnalysisOut = Field(description="The saved deterministic analysis: evidence, checks, sources.")


class InspectionListOut(BaseModel):
    items: list[InspectionSummaryOut]
    total: int


class CountsOut(BaseModel):
    PASS: int
    FAIL: int
    REVIEW: int


class OfficerCountsOut(BaseModel):
    NOT_REQUIRED: int
    PENDING: int
    IN_REVIEW: int
    COMPLETED: int


class DecisionCountsOut(BaseModel):
    ACCEPT_SYSTEM_RESULT: int
    OVERRIDE: int
    MANUAL_REVIEW: int


class InspectionStatsOut(BaseModel):
    total: int
    system: CountsOut
    bis: CountsOut
    legal_metrology: CountsOut
    escalated: int = Field(description="Inspections the system could not resolve (sent to the officer queue).")
    officer: OfficerCountsOut
    decisions: DecisionCountsOut


class ReviewIn(BaseModel):
    """An officer review action. Strict: any other field (e.g. system_result) is rejected."""

    model_config = ConfigDict(extra="forbid")

    action: Literal["START", "COMPLETE"]
    decision: Literal["ACCEPT_SYSTEM_RESULT", "OVERRIDE", "MANUAL_REVIEW"] | None = None
    officer_result: ResultLiteral | None = None
    note: str | None = Field(default=None, max_length=NOTE_MAX)


# ------------------------------------------------------------------ helpers


def _summary_fields(r: InspectionRecord) -> dict:
    return dict(
        inspection_id=r.inspection_id, created_at=r.created_at, product_status=r.product_status,
        product_name=r.product_name, product_category=r.product_category, standard_number=r.standard_number,
        bis_result=r.bis_result, legal_metrology_result=r.legal_metrology_result, system_result=r.system_result,
        escalation_required=r.escalation_required, escalation_reasons=r.escalation_reasons,
        officer_status=r.officer_status, officer_decision=r.officer_decision, officer_result=r.officer_result,
        final_result=final_result(r), review_started_at=r.review_started_at,
        review_completed_at=r.review_completed_at, image_count=len(r.sides), sides=list(r.sides),
    )


def _record_out(r: InspectionRecord) -> InspectionRecordOut:
    return InspectionRecordOut(
        **_summary_fields(r),
        system_reasons=r.system_reasons, officer_note=r.officer_note,
        images=[StoredImageOut(index=i.position, image_id=i.image_id, side=i.side, filename=i.filename,
                               content_type=i.content_type,
                               url=f"/inspections/{r.inspection_id}/images/{i.position}") for i in r.images],
        analysis=InspectionAnalysisOut.model_validate(r.analysis),
    )


def _checked_id(inspection_id: str) -> str:
    if not INSPECTION_ID_PATTERN.match(inspection_id):
        raise HTTPException(status_code=422, detail=f"'{inspection_id}' is not a valid inspection id (INS-YYYYMMDD-XXXXXX).")
    return inspection_id


def _db_error(session: Session, exc: SQLAlchemyError) -> HTTPException:
    session.rollback()
    return HTTPException(status_code=503, detail=_DB_UNAVAILABLE)


# ------------------------------------------------------------------ endpoints


@router.post("", response_model=InspectionRecordOut, status_code=201)
async def create(
    request: Request,
    image: UploadFile | None = File(None),
    side: str | None = Form(None),
    images: list[UploadFile] | None = File(None),
    sides: list[str] | None = Form(None),
    inspection_type: Literal["PACKAGE", "HALLMARK"] = Form("PACKAGE"),
    huid_reference: str | None = Form(None),
    analyzer: InspectionAnalyzer = Depends(get_analyzer),
    session: Session = Depends(get_session),
) -> InspectionRecordOut:
    """Analyse the package photos on the server and save the inspection with officer status PENDING."""
    extra = sorted(set((await request.form()).keys()) - _PACKAGE_FIELDS)
    if extra:
        raise HTTPException(
            status_code=422,
            detail=f"Unexpected field(s): {', '.join(extra)}. Only the package photos and sides are accepted; "
                   "the system result is computed by the backend.",
        )
    uploads = await _package(image, side, images, sides)
    # Only non-default options are bound, so a caller that never uses them sees
    # exactly the signature it saw before this field existed.
    options = {}
    if inspection_type != "PACKAGE":
        options["inspection_type"] = inspection_type
    if huid_reference:
        options["huid_reference"] = huid_reference
    analyze = partial(analyzer.analyze_package, **options) if options else analyzer.analyze_package
    analysis = _run(analyze, uploads)
    try:
        record = create_inspection(session, analysis, uploads)
        return _record_out(record)
    except SQLAlchemyError as exc:
        raise _db_error(session, exc) from exc


@router.get("", response_model=InspectionListOut)
def index(
    officer_status: list[OfficerStatusLiteral] = Query(default=[]),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
) -> InspectionListOut:
    try:
        rows, total = list_inspections(session, tuple(officer_status), limit, offset)
        return InspectionListOut(items=[InspectionSummaryOut(**_summary_fields(r)) for r in rows], total=total)
    except SQLAlchemyError as exc:
        raise _db_error(session, exc) from exc


@router.get("/stats", response_model=InspectionStatsOut)
def stats(session: Session = Depends(get_session)) -> InspectionStatsOut:
    try:
        return InspectionStatsOut(**statistics(session))
    except SQLAlchemyError as exc:
        raise _db_error(session, exc) from exc


@router.get("/{inspection_id}", response_model=InspectionRecordOut)
def detail(inspection_id: str, session: Session = Depends(get_session)) -> InspectionRecordOut:
    _checked_id(inspection_id)
    try:
        record = get_inspection(session, inspection_id)
    except SQLAlchemyError as exc:
        raise _db_error(session, exc) from exc
    if record is None:
        raise HTTPException(status_code=404, detail=f"Inspection {inspection_id} was not found.")
    return _record_out(record)


@router.get("/{inspection_id}/images/{index}")
def stored_image(inspection_id: str, index: int = Path(ge=1), session: Session = Depends(get_session)) -> Response:
    _checked_id(inspection_id)
    try:
        img = get_image(session, inspection_id, index)
    except SQLAlchemyError as exc:
        raise _db_error(session, exc) from exc
    if img is None:
        raise HTTPException(status_code=404, detail=f"Inspection {inspection_id} has no stored image {index}.")
    return Response(content=img.data, media_type=img.content_type,
                    headers={"Cache-Control": "private, max-age=86400"})


@router.get("/{inspection_id}/report.pdf", response_class=Response,
            responses={200: {"content": {"application/pdf": {}}}})
def report(inspection_id: str, session: Session = Depends(get_session)) -> Response:
    """The evidence-backed inspection report, built from the stored record and photos.
    Read-only: nothing is recomputed, no model is called, the session is never committed."""
    _checked_id(inspection_id)
    try:
        record = get_inspection(session, inspection_id)
        if record is None:
            raise HTTPException(status_code=404, detail=f"Inspection {inspection_id} was not found.")
        data = _record_out(record).model_dump(mode="json")
        images = {i.position: i.data for i in record.images}
    except SQLAlchemyError as exc:
        raise _db_error(session, exc) from exc
    finally:
        session.rollback()  # read-only: never persist anything from report generation
    pdf = render_report(data, images, datetime.now(timezone.utc))
    return Response(content=pdf, media_type="application/pdf", headers={
        "Content-Disposition": f'inline; filename="metriq-report-{inspection_id}.pdf"',
        "Cache-Control": "no-store",
    })


@router.post("/{inspection_id}/review", response_model=InspectionRecordOut)
def review(inspection_id: str, body: ReviewIn, session: Session = Depends(get_session)) -> InspectionRecordOut:
    """Record an officer review action. The system result is never changed."""
    _checked_id(inspection_id)
    try:
        record = apply_review(session, inspection_id, ReviewAction(body.action, body.decision, body.officer_result, body.note))
        return _record_out(record)
    except ReviewError as exc:
        raise HTTPException(status_code=exc.status, detail=exc.message) from exc
    except SQLAlchemyError as exc:
        raise _db_error(session, exc) from exc

