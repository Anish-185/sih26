"""Persisted inspections and the officer review workflow.

Two things are stored side by side and never mixed:

* the SYSTEM RESULT — what the deterministic pipeline concluded when the
  inspection was saved: the BIS compliance result, the Legal Metrology
  package-label result, the combined ``system_result``, their reasons and the
  full analysis (declarations, OCR regions, evidence, sources). Written once, by
  the backend, from its own analysis. A database trigger (see the migration)
  rejects any later change to these columns.
* the ESCALATION — whether the system could resolve the inspection itself
  (``escalation_required``) and every reason it could not (``escalation_reasons``,
  from ``app.escalation``). Also written once, with the system result.
* the OFFICER REVIEW — a human decision recorded later: ``officer_status``,
  ``officer_decision``, ``officer_result`` (only for an override), ``officer_note``
  and the review timestamps.

Combined system result (``app.escalation.system_result``): FAIL if any applicable
evidence system (BIS, Legal Metrology, hallmarking) FAILs; PASS only if all PASS;
otherwise REVIEW. Every underlying result is kept, so the combination never hides
which one decided.

Escalation and review workflow (``OFFICER_TRANSITIONS``):

    system resolved the case     -> NOT_REQUIRED  (final; the system result is the final result)
    system could not resolve it  -> PENDING --START--> IN_REVIEW --COMPLETE--> COMPLETED

COMPLETE records one decision:
    ACCEPT_SYSTEM_RESULT  the officer agrees; the final result is the system result
    OVERRIDE              the officer records a different result (``officer_result``) and a note
    MANUAL_REVIEW         the package needs physical / manual verification; a note is required
A completed review is final: a second START or COMPLETE is rejected.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Integer,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
    select,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from app.db import Base
from app.escalation import assess as assess_escalation

RESULTS = ("PASS", "FAIL", "REVIEW")
OFFICER_STATUSES = ("NOT_REQUIRED", "PENDING", "IN_REVIEW", "COMPLETED")
OFFICER_DECISIONS = ("ACCEPT_SYSTEM_RESULT", "OVERRIDE", "MANUAL_REVIEW")
OFFICER_TRANSITIONS = {"START": ("PENDING", "IN_REVIEW"), "COMPLETE": ("IN_REVIEW", "COMPLETED")}
NOTE_MAX = 2000

INSPECTION_ID_PATTERN = re.compile(r"^INS-\d{8}-[0-9A-F]{6}$")

_MIME = {"PNG": "image/png", "JPEG": "image/jpeg", "JPG": "image/jpeg", "WEBP": "image/webp",
         "GIF": "image/gif", "BMP": "image/bmp", "TIFF": "image/tiff", "MPO": "image/jpeg"}


def _in(column: str, values: tuple[str, ...]) -> str:
    return f"{column} IN ({', '.join(repr(v) for v in values)})"


class InspectionRecord(Base):
    __tablename__ = "inspections"
    __table_args__ = (
        CheckConstraint(_in("bis_result", RESULTS), name="ck_inspections_bis_result"),
        CheckConstraint(_in("legal_metrology_result", RESULTS), name="ck_inspections_legal_metrology_result"),
        CheckConstraint(_in("system_result", RESULTS), name="ck_inspections_system_result"),
        CheckConstraint(_in("officer_status", OFFICER_STATUSES), name="ck_inspections_officer_status"),
        CheckConstraint(f"officer_decision IS NULL OR {_in('officer_decision', OFFICER_DECISIONS)}",
                        name="ck_inspections_officer_decision"),
        CheckConstraint(f"officer_result IS NULL OR {_in('officer_result', RESULTS)}",
                        name="ck_inspections_officer_result"),
        # A decision exists exactly when the review is completed.
        CheckConstraint("(officer_status = 'COMPLETED') = (officer_decision IS NOT NULL "
                        "AND review_completed_at IS NOT NULL)", name="ck_inspections_completed_has_decision"),
        CheckConstraint("officer_status IN ('NOT_REQUIRED', 'PENDING') OR review_started_at IS NOT NULL",
                        name="ck_inspections_review_started"),
        # A case the system resolved is never in the officer queue, and carries no review.
        CheckConstraint("officer_status <> 'NOT_REQUIRED' OR (NOT escalation_required AND review_started_at IS NULL "
                        "AND officer_note IS NULL)", name="ck_inspections_not_required"),
        # Only an override carries its own result, and it must differ from the system result.
        CheckConstraint("(officer_decision = 'OVERRIDE') = (officer_result IS NOT NULL) "
                        "AND (officer_result IS NULL OR officer_result <> system_result)",
                        name="ck_inspections_override_result"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    inspection_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # --- system result: written once from the backend's own analysis ---
    product_status: Mapped[str] = mapped_column(String(16), nullable=False)
    product_name: Mapped[str | None] = mapped_column(Text)
    product_category: Mapped[str | None] = mapped_column(Text)
    standard_number: Mapped[str | None] = mapped_column(String(64))
    bis_result: Mapped[str] = mapped_column(String(8), nullable=False)
    legal_metrology_result: Mapped[str] = mapped_column(String(8), nullable=False)
    system_result: Mapped[str] = mapped_column(String(8), nullable=False)
    system_reasons: Mapped[list] = mapped_column(JSONB, nullable=False)
    sides: Mapped[list] = mapped_column(JSONB, nullable=False)
    analysis: Mapped[dict] = mapped_column(JSONB, nullable=False)  # the full InspectionAnalysisOut
    escalation_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    escalation_reasons: Mapped[list] = mapped_column(JSONB, nullable=False)

    # --- officer review: a separate, later human decision ---
    officer_status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="PENDING")
    officer_decision: Mapped[str | None] = mapped_column(String(32))
    officer_result: Mapped[str | None] = mapped_column(String(8))
    officer_note: Mapped[str | None] = mapped_column(Text)
    review_started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    review_completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))

    images: Mapped[list["InspectionImage"]] = relationship(
        back_populates="inspection", order_by="InspectionImage.position", cascade="all, delete-orphan"
    )


class InspectionImage(Base):
    """An uploaded package photo, stored as uploaded so the evidence can be re-inspected."""

    __tablename__ = "inspection_images"
    __table_args__ = (UniqueConstraint("inspection_pk", "position", name="uq_inspection_images_position"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    inspection_pk: Mapped[int] = mapped_column(ForeignKey("inspections.id", ondelete="CASCADE"), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False)  # 1-based upload order = PackageImageOut.index
    image_id: Mapped[str] = mapped_column(String(32), nullable=False)
    side: Mapped[str] = mapped_column(String(16), nullable=False)
    filename: Mapped[str] = mapped_column(Text, nullable=False)
    content_type: Mapped[str] = mapped_column(String(64), nullable=False)
    data: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)

    inspection: Mapped[InspectionRecord] = relationship(back_populates="images")


# ------------------------------------------------------------------ system result


def system_reasons(analysis) -> list[dict]:
    """One reason per evidence system, from the deterministic results — never written by a client.
    Legal Metrology is listed even when not applied (its reason says so); hallmarking when evaluated."""
    bis, lm = analysis.compliance, analysis.package_label
    out = [
        {"source": "BIS", "result": bis.overall_status, "reason_code": bis.reason_code, "reason": bis.reason},
        {"source": "LEGAL_METROLOGY", "result": lm.overall_status, "reason_code": lm.reason_code, "reason": lm.reason},
    ]
    h = analysis.hallmark
    if h is not None and (h.detected or analysis.inspection_type == "HALLMARK"):
        out.append({"source": "HALLMARKING", "result": h.overall_status, "reason_code": h.reason_code,
                    "reason": h.reason})
    return out


def create_inspection(session: Session, analysis, uploads) -> InspectionRecord:
    """Persist a backend-produced ``InspectionAnalysisOut`` and the photos it was computed from."""
    bis, lm = analysis.compliance.overall_status, analysis.package_label.overall_status
    product = analysis.product
    data = analysis.model_dump(mode="json")
    # Re-assessed from the analysis being stored, so the saved escalation always matches it.
    escalation = assess_escalation(data)
    record = InspectionRecord(
        inspection_id=analysis.inspection_id,
        product_status=product.status,
        product_name=product.name if product.status == "MATCHED" else None,
        product_category=analysis.compliance.coverage.product_category if analysis.compliance.coverage else None,
        standard_number=product.standard_number if product.status == "MATCHED" else None,
        bis_result=bis,
        legal_metrology_result=lm,
        system_result=escalation["system_result"],
        system_reasons=system_reasons(analysis),
        sides=[img.side for img in analysis.images],
        analysis=data,
        escalation_required=escalation["required"],
        escalation_reasons=escalation["reasons"],
        officer_status="PENDING" if escalation["required"] else "NOT_REQUIRED",
    )
    for img, upload in zip(analysis.images, uploads):
        record.images.append(InspectionImage(
            position=img.index, image_id=img.image_id, side=img.side, filename=img.filename,
            content_type=_MIME.get((img.format or "").upper(), "application/octet-stream"), data=upload.data,
        ))
    session.add(record)
    session.commit()
    return record


# ------------------------------------------------------------------ queries


def get_inspection(session: Session, inspection_id: str, for_update: bool = False) -> InspectionRecord | None:
    query = select(InspectionRecord).where(InspectionRecord.inspection_id == inspection_id)
    if for_update:
        query = query.with_for_update()
    return session.scalars(query).first()


def list_inspections(session: Session, officer_statuses: tuple[str, ...] = (), limit: int = 50,
                     offset: int = 0) -> tuple[list[InspectionRecord], int]:
    query = select(InspectionRecord)
    count = select(func.count()).select_from(InspectionRecord)
    if officer_statuses:
        query = query.where(InspectionRecord.officer_status.in_(officer_statuses))
        count = count.where(InspectionRecord.officer_status.in_(officer_statuses))
    rows = session.scalars(query.order_by(InspectionRecord.created_at.desc(), InspectionRecord.id.desc())
                           .limit(limit).offset(offset)).all()
    return list(rows), session.scalar(count) or 0


def get_image(session: Session, inspection_id: str, position: int) -> InspectionImage | None:
    return session.scalars(
        select(InspectionImage).join(InspectionRecord)
        .where(InspectionRecord.inspection_id == inspection_id, InspectionImage.position == position)
    ).first()


def statistics(session: Session) -> dict:
    """Counts straight from the database. System results and officer review states are
    different things and are counted separately."""
    def counts(column, keys):
        found = dict(session.execute(select(column, func.count()).group_by(column)).all())
        return {k: int(found.get(k, 0)) for k in keys}

    return {
        "total": int(session.scalar(select(func.count()).select_from(InspectionRecord)) or 0),
        "system": counts(InspectionRecord.system_result, RESULTS),
        "bis": counts(InspectionRecord.bis_result, RESULTS),
        "legal_metrology": counts(InspectionRecord.legal_metrology_result, RESULTS),
        "officer": counts(InspectionRecord.officer_status, OFFICER_STATUSES),
        "escalated": int(session.scalar(select(func.count()).select_from(InspectionRecord)
                                        .where(InspectionRecord.escalation_required)) or 0),
        "decisions": counts(InspectionRecord.officer_decision, OFFICER_DECISIONS),
    }


# ------------------------------------------------------------------ officer review


class ReviewError(Exception):
    """A review action that is not allowed. ``status`` is the HTTP status to return."""

    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status
        self.message = message


@dataclass(frozen=True)
class ReviewAction:
    action: str  # START | COMPLETE
    decision: str | None = None
    officer_result: str | None = None
    note: str | None = None


def apply_review(session: Session, inspection_id: str, act: ReviewAction) -> InspectionRecord:
    """Validate and apply one review action. Locks the row, so two concurrent
    completions cannot both succeed. Never touches the system result."""
    record = get_inspection(session, inspection_id, for_update=True)
    if record is None:
        session.rollback()
        raise ReviewError(404, f"Inspection {inspection_id} was not found.")
    if record.officer_status == "NOT_REQUIRED":
        session.rollback()
        raise ReviewError(409, f"Inspection {inspection_id} was resolved by the system and was not escalated; "
                               "there is no officer review to record.")

    required, target = OFFICER_TRANSITIONS[act.action]
    if record.officer_status != required:
        session.rollback()
        if record.officer_status == "COMPLETED":
            raise ReviewError(409, f"Inspection {inspection_id} has already been reviewed "
                                   f"({record.officer_decision}); a completed review is final.")
        if act.action == "START":
            raise ReviewError(409, f"Review of {inspection_id} has already started.")
        raise ReviewError(409, f"Start the review of {inspection_id} before recording a decision.")

    now = datetime.now(timezone.utc)
    note = (act.note or "").strip() or None
    if act.action == "START":
        if act.decision or act.officer_result or note:
            session.rollback()
            raise ReviewError(422, "START takes no decision, result or note.")
        record.officer_status, record.review_started_at = target, now
    else:
        problem = _decision_problem(record, act.decision, act.officer_result, note)
        if problem:
            session.rollback()
            raise ReviewError(422, problem)
        record.officer_status, record.officer_decision = target, act.decision
        record.officer_result = act.officer_result if act.decision == "OVERRIDE" else None
        record.officer_note, record.review_completed_at = note, now
    session.commit()
    return record


def _decision_problem(record: InspectionRecord, decision, officer_result, note) -> str | None:
    if decision not in OFFICER_DECISIONS:
        return f"decision must be one of {', '.join(OFFICER_DECISIONS)}."
    if note is not None and len(note) > NOTE_MAX:
        return f"The officer note is limited to {NOTE_MAX} characters."
    if decision == "OVERRIDE":
        if officer_result not in RESULTS:
            return "An override must give the officer's result (PASS, FAIL or REVIEW)."
        if officer_result == record.system_result:
            return (f"The officer result equals the system result ({record.system_result}); "
                    "use ACCEPT_SYSTEM_RESULT instead of OVERRIDE.")
        if not note:
            return "An override needs an officer note explaining the decision."
    elif officer_result is not None:
        return "Only an OVERRIDE records an officer result."
    if decision == "MANUAL_REVIEW" and not note:
        return "MANUAL_REVIEW needs an officer note saying what must be verified."
    return None


def final_result(record: InspectionRecord) -> str | None:
    """What the completed review concluded — never replaces ``system_result``."""
    if record.officer_status == "NOT_REQUIRED":
        return record.system_result  # resolved by the system: its result is final
    if record.officer_status != "COMPLETED":
        return None
    if record.officer_decision == "ACCEPT_SYSTEM_RESULT":
        return record.system_result
    if record.officer_decision == "OVERRIDE":
        return record.officer_result
    return "MANUAL_REVIEW"
