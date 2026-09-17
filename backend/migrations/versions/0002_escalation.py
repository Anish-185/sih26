"""Escalation: NOT_REQUIRED officer status and the saved escalation assessment.

Adds ``escalation_required`` and ``escalation_reasons`` (system-owned, protected by
the immutability trigger like the system result) and the ``NOT_REQUIRED`` officer
status for inspections the system resolved without an officer.

Existing inspections are assessed from their saved analysis with the same
deterministic function the API uses (``app.escalation.assess``). An existing
inspection that did not need escalation and was never reviewed becomes
NOT_REQUIRED; one an officer already reviewed keeps its review.

Revision ID: 0002_escalation
Revises: 0001_inspection_records
Create Date: 2026-09-17
"""

import json

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from app.escalation import assess

revision = "0002_escalation"
down_revision = "0001_inspection_records"
branch_labels = None
depends_on = None

SYSTEM_COLUMNS = (
    "inspection_id", "created_at", "product_status", "product_name", "product_category", "standard_number",
    "bis_result", "legal_metrology_result", "system_result", "system_reasons", "sides", "analysis",
)
ESCALATION_COLUMNS = ("escalation_required", "escalation_reasons")


def _protect_function(columns) -> str:
    changed = " OR ".join(f"NEW.{c} IS DISTINCT FROM OLD.{c}" for c in columns)
    return f"""
        CREATE OR REPLACE FUNCTION inspections_protect_system_result() RETURNS trigger AS $$
        BEGIN
            IF {changed} THEN
                RAISE EXCEPTION 'The system result of inspection % is immutable', OLD.inspection_id
                    USING ERRCODE = 'check_violation';
            END IF;
            IF OLD.officer_status = 'NOT_REQUIRED' AND NEW.officer_status IS DISTINCT FROM OLD.officer_status THEN
                RAISE EXCEPTION 'Inspection % was resolved by the system and is not in the officer queue',
                    OLD.inspection_id USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """


def upgrade() -> None:
    bind = op.get_bind()
    op.execute("ALTER TABLE inspections DISABLE TRIGGER inspections_system_result_immutable")
    op.add_column("inspections", sa.Column("escalation_required", sa.Boolean(), nullable=True))
    op.add_column("inspections", sa.Column("escalation_reasons", postgresql.JSONB(), nullable=True))
    # Allow NOT_REQUIRED before existing rows are assessed.
    op.drop_constraint("ck_inspections_officer_status", "inspections", type_="check")
    op.create_check_constraint("ck_inspections_officer_status", "inspections",
                               "officer_status IN ('NOT_REQUIRED', 'PENDING', 'IN_REVIEW', 'COMPLETED')")
    op.drop_constraint("ck_inspections_review_started", "inspections", type_="check")
    op.create_check_constraint("ck_inspections_review_started", "inspections",
                               "officer_status IN ('NOT_REQUIRED', 'PENDING') OR review_started_at IS NOT NULL")

    rows = bind.execute(sa.text("SELECT id, analysis, officer_status FROM inspections")).all()
    for row_id, analysis, status in rows:
        result = assess(analysis)
        new_status = "NOT_REQUIRED" if not result["required"] and status == "PENDING" else status
        bind.execute(
            sa.text("UPDATE inspections SET escalation_required = :req, escalation_reasons = CAST(:reasons AS jsonb), "
                    "officer_status = :status WHERE id = :id"),
            {"req": result["required"], "reasons": json.dumps(result["reasons"]), "status": new_status, "id": row_id},
        )

    op.alter_column("inspections", "escalation_required", nullable=False)
    op.alter_column("inspections", "escalation_reasons", nullable=False)
    op.create_check_constraint("ck_inspections_not_required", "inspections",
                               "officer_status <> 'NOT_REQUIRED' OR (NOT escalation_required "
                               "AND review_started_at IS NULL AND officer_note IS NULL)")
    op.create_index("ix_inspections_escalation_required", "inspections", ["escalation_required"])

    op.execute(_protect_function(SYSTEM_COLUMNS + ESCALATION_COLUMNS))
    op.execute("ALTER TABLE inspections ENABLE TRIGGER inspections_system_result_immutable")


def downgrade() -> None:
    op.execute("ALTER TABLE inspections DISABLE TRIGGER inspections_system_result_immutable")
    op.drop_index("ix_inspections_escalation_required", table_name="inspections")
    op.drop_constraint("ck_inspections_not_required", "inspections", type_="check")
    op.execute("UPDATE inspections SET officer_status = 'PENDING' WHERE officer_status = 'NOT_REQUIRED'")
    op.drop_constraint("ck_inspections_review_started", "inspections", type_="check")
    op.create_check_constraint("ck_inspections_review_started", "inspections",
                               "officer_status = 'PENDING' OR review_started_at IS NOT NULL")
    op.drop_constraint("ck_inspections_officer_status", "inspections", type_="check")
    op.create_check_constraint("ck_inspections_officer_status", "inspections",
                               "officer_status IN ('PENDING', 'IN_REVIEW', 'COMPLETED')")
    op.drop_column("inspections", "escalation_reasons")
    op.drop_column("inspections", "escalation_required")
    changed = " OR ".join(f"NEW.{c} IS DISTINCT FROM OLD.{c}" for c in SYSTEM_COLUMNS)
    op.execute(f"""
        CREATE OR REPLACE FUNCTION inspections_protect_system_result() RETURNS trigger AS $$
        BEGIN
            IF {changed} THEN
                RAISE EXCEPTION 'The system result of inspection % is immutable', OLD.inspection_id
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("ALTER TABLE inspections ENABLE TRIGGER inspections_system_result_immutable")
