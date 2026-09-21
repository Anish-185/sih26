"""HTTP layer for persisted inspections.

    POST /inspections                       multipart, same package form as /inspection/analyze
                                            (image | images + sides). The backend runs the analysis
                                            itself and saves it — a client never sends a result.
    GET  /inspections                       newest first; ?escalated=true|false filters on whether the
                                            deterministic system could resolve the inspection itself
    GET  /inspections/stats                 counts from the database
    GET  /inspections/{inspection_id}       the full record: system result + evidence + analysis
    GET  /inspections/{inspection_id}/images/{index}   a stored package photo (1-based upload order)
    GET  /inspections/{inspection_id}/report.pdf       evidence-backed PDF report of the saved record (read-only)

A saved record is read-only: there is no endpoint that changes a stored result,
and the database refuses changes to the system columns as well.
"""

from __future__ import annotations

from datetime import datetime, timezone
from functools import partial
from typing import Literal

from fastapi import APIRouter, Depends, File, Form, HTTPException, Path, Query, Request, Response, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from app.db import get_session
from app.report import render_report
from app.inspection import EscalationReasonOut, InspectionAnalysisOut, InspectionAnalyzer
from app.inspection_api import _package, _run, get_analyzer
from app.records import (
    INSPECTION_ID_PATTERN,
    InspectionRecord,
    create_inspection,
    get_image,
    get_inspection,
    list_inspections,
    statistics,
)

router = APIRouter(prefix="/inspections", tags=["inspections"])

_PACKAGE_FIELDS = {"image", "side", "images", "sides", "inspection_type", "huid_reference"}
_DB_UNAVAILABLE = "The inspection database is unavailable. Check that PostgreSQL is running and migrated."


# ------------------------------------------------------------------ models


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
    escalation_required: bool = Field(description="False: the deterministic system established the evidence "
                                      "chain from the photographed evidence; nothing further is outstanding.")
    escalation_reasons: list[EscalationReasonOut] = Field(description="Why the system could not establish it.")
    image_count: int
    sides: list[str]


class InspectionRecordOut(InspectionSummaryOut):
    images: list[StoredImageOut]
    analysis: InspectionAnalysisOut = Field(description="The saved deterministic analysis: evidence, sources.")


class InspectionListOut(BaseModel):
    items: list[InspectionSummaryOut]
    total: int


class InspectionStatsOut(BaseModel):
    total: int
    escalated: int = Field(description="Inspections the deterministic system could not establish the evidence "
                           "chain for from the photographed evidence alone.")
    resolved: int = Field(description="Inspections the deterministic system fully established from the photos.")


# ------------------------------------------------------------------ helpers


def _summary_fields(r: InspectionRecord) -> dict:
    return dict(
        inspection_id=r.inspection_id, created_at=r.created_at, product_status=r.product_status,
        product_name=r.product_name, product_category=r.product_category, standard_number=r.standard_number,
        escalation_required=r.escalation_required, escalation_reasons=r.escalation_reasons,
        image_count=len(r.sides), sides=list(r.sides),
    )


def _record_out(r: InspectionRecord) -> InspectionRecordOut:
    return InspectionRecordOut(
        **_summary_fields(r),
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
    """Analyse the package photos on the server and save the inspection and its evidence."""
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
    escalated: bool | None = Query(default=None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    session: Session = Depends(get_session),
) -> InspectionListOut:
    try:
        rows, total = list_inspections(session, escalated, limit, offset)
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

