"""Persisted inspections, stored package photos and the officer review.

The system-result columns and stored photos are protected by triggers: once an
inspection is saved, only the officer review columns can change.

Revision ID: 0001_inspection_records
Revises:
Create Date: 2026-09-17
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "0001_inspection_records"
down_revision = None
branch_labels = None
depends_on = None

RESULTS = "('PASS', 'FAIL', 'REVIEW')"

# Columns written once from the backend's analysis. The officer review columns are not listed.
SYSTEM_COLUMNS = (
    "inspection_id", "created_at", "product_status", "product_name", "product_category", "standard_number",
    "bis_result", "legal_metrology_result", "system_result", "system_reasons", "sides", "analysis",
)


def upgrade() -> None:
    op.create_table(
        "inspections",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("inspection_id", sa.String(32), nullable=False, unique=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("product_status", sa.String(16), nullable=False),
        sa.Column("product_name", sa.Text()),
        sa.Column("product_category", sa.Text()),
        sa.Column("standard_number", sa.String(64)),
        sa.Column("bis_result", sa.String(8), nullable=False),
        sa.Column("legal_metrology_result", sa.String(8), nullable=False),
        sa.Column("system_result", sa.String(8), nullable=False),
        sa.Column("system_reasons", postgresql.JSONB(), nullable=False),
        sa.Column("sides", postgresql.JSONB(), nullable=False),
        sa.Column("analysis", postgresql.JSONB(), nullable=False),
        sa.Column("officer_status", sa.String(16), nullable=False, server_default="PENDING"),
        sa.Column("officer_decision", sa.String(32)),
        sa.Column("officer_result", sa.String(8)),
        sa.Column("officer_note", sa.Text()),
        sa.Column("review_started_at", sa.DateTime(timezone=True)),
        sa.Column("review_completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(f"bis_result IN {RESULTS}", name="ck_inspections_bis_result"),
        sa.CheckConstraint(f"legal_metrology_result IN {RESULTS}", name="ck_inspections_legal_metrology_result"),
        sa.CheckConstraint(f"system_result IN {RESULTS}", name="ck_inspections_system_result"),
        sa.CheckConstraint("officer_status IN ('PENDING', 'IN_REVIEW', 'COMPLETED')",
                           name="ck_inspections_officer_status"),
        sa.CheckConstraint("officer_decision IS NULL OR officer_decision IN "
                           "('ACCEPT_SYSTEM_RESULT', 'OVERRIDE', 'MANUAL_REVIEW')",
                           name="ck_inspections_officer_decision"),
        sa.CheckConstraint(f"officer_result IS NULL OR officer_result IN {RESULTS}",
                           name="ck_inspections_officer_result"),
        sa.CheckConstraint("(officer_status = 'COMPLETED') = (officer_decision IS NOT NULL "
                           "AND review_completed_at IS NOT NULL)", name="ck_inspections_completed_has_decision"),
        sa.CheckConstraint("officer_status = 'PENDING' OR review_started_at IS NOT NULL",
                           name="ck_inspections_review_started"),
        sa.CheckConstraint("(officer_decision = 'OVERRIDE') = (officer_result IS NOT NULL) "
                           "AND (officer_result IS NULL OR officer_result <> system_result)",
                           name="ck_inspections_override_result"),
    )
    op.create_index("ix_inspections_created_at", "inspections", ["created_at"])
    op.create_index("ix_inspections_officer_status", "inspections", ["officer_status"])

    op.create_table(
        "inspection_images",
        sa.Column("id", sa.BigInteger(), primary_key=True),
        sa.Column("inspection_pk", sa.BigInteger(), sa.ForeignKey("inspections.id", ondelete="CASCADE"),
                  nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("image_id", sa.String(32), nullable=False),
        sa.Column("side", sa.String(16), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("content_type", sa.String(64), nullable=False),
        sa.Column("data", sa.LargeBinary(), nullable=False),
        sa.UniqueConstraint("inspection_pk", "position", name="uq_inspection_images_position"),
    )

    changed = " OR ".join(f"NEW.{c} IS DISTINCT FROM OLD.{c}" for c in SYSTEM_COLUMNS)
    op.execute(f"""
        CREATE FUNCTION inspections_protect_system_result() RETURNS trigger AS $$
        BEGIN
            IF {changed} THEN
                RAISE EXCEPTION 'The system result of inspection % is immutable', OLD.inspection_id
                    USING ERRCODE = 'check_violation';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER inspections_system_result_immutable
        BEFORE UPDATE ON inspections
        FOR EACH ROW EXECUTE FUNCTION inspections_protect_system_result();
    """)
    op.execute("""
        CREATE FUNCTION inspection_images_immutable() RETURNS trigger AS $$
        BEGIN
            RAISE EXCEPTION 'Stored inspection images are immutable' USING ERRCODE = 'check_violation';
        END;
        $$ LANGUAGE plpgsql;
    """)
    op.execute("""
        CREATE TRIGGER inspection_images_no_update
        BEFORE UPDATE ON inspection_images
        FOR EACH ROW EXECUTE FUNCTION inspection_images_immutable();
    """)


def downgrade() -> None:
    op.execute("DROP TRIGGER IF EXISTS inspection_images_no_update ON inspection_images")
    op.execute("DROP FUNCTION IF EXISTS inspection_images_immutable()")
    op.execute("DROP TRIGGER IF EXISTS inspections_system_result_immutable ON inspections")
    op.execute("DROP FUNCTION IF EXISTS inspections_protect_system_result()")
    op.drop_table("inspection_images")
    op.drop_index("ix_inspections_officer_status", table_name="inspections")
    op.drop_index("ix_inspections_created_at", table_name="inspections")
    op.drop_table("inspections")
