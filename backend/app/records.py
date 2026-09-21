"""Persisted inspections: the evidence MetrIQ established and its resolution.

An inspection record is written once and never changes. Two things are stored
side by side:

* the EVIDENCE — what the deterministic pipeline established when the
  inspection was saved: the identified product/standard and the full analysis
  (declarations, OCR regions, evidence, sources). Written by the backend from
  its own analysis. A database trigger (see the migration) rejects any later
  change to these columns. MetrIQ produces no automatic legal/compliance
  verdict — there is no PASS/FAIL/REVIEW result stored here.
* the RESOLUTION — whether the deterministic system could establish the
  inspection's evidence chain from the photographed evidence alone
  (``escalation_required``) and every reason it could not (``escalation_reasons``,
  from ``app.escalation``). Written once, with the evidence.

There is no human decision workflow here: MetrIQ records what it established
and, where it could not, says so and why. Nothing in this module can change a
stored record.

Legacy columns: databases migrated before this module dropped the review
workflow and the compliance-verdict columns (``bis_result``,
``legal_metrology_result``, ``system_result``, ``system_reasons``) still carry
them. They are not mapped, so they are simply ignored when a record is loaded.
"""

from __future__ import annotations

import re
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Boolean,
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

INSPECTION_ID_PATTERN = re.compile(r"^INS-\d{8}-[0-9A-F]{6}$")

_MIME = {"PNG": "image/png", "JPEG": "image/jpeg", "JPG": "image/jpeg", "WEBP": "image/webp",
         "GIF": "image/gif", "BMP": "image/bmp", "TIFF": "image/tiff", "MPO": "image/jpeg"}


class InspectionRecord(Base):
    __tablename__ = "inspections"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    inspection_id: Mapped[str] = mapped_column(String(32), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())

    # --- evidence: written once from the backend's own analysis ---
    product_status: Mapped[str] = mapped_column(String(16), nullable=False)
    product_name: Mapped[str | None] = mapped_column(Text)
    product_category: Mapped[str | None] = mapped_column(Text)
    standard_number: Mapped[str | None] = mapped_column(String(64))
    sides: Mapped[list] = mapped_column(JSONB, nullable=False)
    analysis: Mapped[dict] = mapped_column(JSONB, nullable=False)  # the full InspectionAnalysisOut
    escalation_required: Mapped[bool] = mapped_column(Boolean, nullable=False)
    escalation_reasons: Mapped[list] = mapped_column(JSONB, nullable=False)

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


def create_inspection(session: Session, analysis, uploads) -> InspectionRecord:
    """Persist a backend-produced ``InspectionAnalysisOut`` and the photos it was computed from."""
    product = analysis.product
    data = analysis.model_dump(mode="json")
    # Re-assessed from the analysis being stored, so the saved escalation always matches it.
    escalation = assess_escalation(data)
    record = InspectionRecord(
        inspection_id=analysis.inspection_id,
        product_status=product.status,
        product_name=product.name if product.status == "MATCHED" else None,
        product_category=product.modelled_product_category,
        standard_number=product.standard_number if product.status == "MATCHED" else None,
        sides=[img.side for img in analysis.images],
        analysis=data,
        escalation_required=escalation["required"],
        escalation_reasons=escalation["reasons"],
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


def get_inspection(session: Session, inspection_id: str) -> InspectionRecord | None:
    return session.scalars(
        select(InspectionRecord).where(InspectionRecord.inspection_id == inspection_id)
    ).first()


def list_inspections(session: Session, escalated: bool | None = None, limit: int = 50,
                     offset: int = 0) -> tuple[list[InspectionRecord], int]:
    query = select(InspectionRecord)
    count = select(func.count()).select_from(InspectionRecord)
    if escalated is not None:
        query = query.where(InspectionRecord.escalation_required == escalated)
        count = count.where(InspectionRecord.escalation_required == escalated)
    rows = session.scalars(query.order_by(InspectionRecord.created_at.desc(), InspectionRecord.id.desc())
                           .limit(limit).offset(offset)).all()
    return list(rows), session.scalar(count) or 0


def get_image(session: Session, inspection_id: str, position: int) -> InspectionImage | None:
    return session.scalars(
        select(InspectionImage).join(InspectionRecord)
        .where(InspectionRecord.inspection_id == inspection_id, InspectionImage.position == position)
    ).first()


def statistics(session: Session) -> dict:
    """Counts straight from the database. No compliance verdict is counted here —
    only whether the deterministic system established the evidence chain."""
    total = int(session.scalar(select(func.count()).select_from(InspectionRecord)) or 0)
    escalated = int(session.scalar(select(func.count()).select_from(InspectionRecord)
                                   .where(InspectionRecord.escalation_required)) or 0)
    return {"total": total, "escalated": escalated, "resolved": total - escalated}

