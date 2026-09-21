"""Drop NOT NULL on the retired compliance-verdict columns.

MetrIQ no longer produces an automatic PASS/FAIL/REVIEW compliance verdict, so
``bis_result``, ``legal_metrology_result``, ``system_result`` and
``system_reasons`` are no longer written by the application (``app.records``
stopped mapping them). They were declared NOT NULL, so a normal insert would
otherwise fail; this migration only relaxes that constraint so the columns can
be left unset going forward. The columns themselves, their CHECK constraints
(which pass trivially for NULL) and the immutability trigger are left in place
— they are legacy, physically-present data, not dropped.

Revision ID: 0003_drop_compliance_verdicts
Revises: 0002_escalation
Create Date: 2026-09-20
"""

from alembic import op

revision = "0003_drop_compliance_verdicts"
down_revision = "0002_escalation"
branch_labels = None
depends_on = None

COLUMNS = ("bis_result", "legal_metrology_result", "system_result")


def upgrade() -> None:
    for column in (*COLUMNS, "system_reasons"):
        op.alter_column("inspections", column, nullable=True)


def downgrade() -> None:
    # Rows saved after this migration have NULL here (the application stopped
    # writing them); backfill a safe placeholder before restoring NOT NULL so
    # the downgrade itself never fails on real data. These columns are
    # protected by the immutability trigger, so the backfill runs with it
    # disabled, exactly as migration 0002 does for its own backfill.
    op.execute("ALTER TABLE inspections DISABLE TRIGGER inspections_system_result_immutable")
    for column in COLUMNS:
        op.execute(f"UPDATE inspections SET {column} = 'REVIEW' WHERE {column} IS NULL")
        op.alter_column("inspections", column, nullable=False)
    op.execute("UPDATE inspections SET system_reasons = '[]' WHERE system_reasons IS NULL")
    op.alter_column("inspections", "system_reasons", nullable=False)
    op.execute("ALTER TABLE inspections ENABLE TRIGGER inspections_system_result_immutable")
