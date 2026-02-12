"""Add outcome_records, feedback_entries, and calibration_bins tables.

Revision ID: 005_learning_tables
Revises: 004_conversation_states
Create Date: 2026-02-12

Creates three tables in the tenant schema for the learning and feedback
system: outcome_records for tracking agent action outcomes with time-windowed
signal detection, feedback_entries for human feedback on agent behavior,
and calibration_bins for per-action-type confidence calibration. All tables
include RLS policies for tenant isolation and composite indexes for
common query patterns.
"""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "005_learning_tables"
down_revision: Union[str, None] = "004_conversation_states"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Get the actual schema name from -x args
    cmd_kwargs = context.get_x_argument(as_dictionary=True)
    schema = cmd_kwargs.get("schema", "tenant")

    # ── outcome_records ──────────────────────────────────────────────────

    op.create_table(
        "outcome_records",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("conversation_state_id", UUID(as_uuid=True), nullable=False),
        sa.Column("action_type", sa.String(50), nullable=False),
        sa.Column("action_id", sa.String(100), nullable=True),
        sa.Column("predicted_confidence", sa.Float(), nullable=False),
        sa.Column("outcome_type", sa.String(50), nullable=False),
        sa.Column(
            "outcome_status",
            sa.String(20),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column("outcome_score", sa.Float(), nullable=True),
        sa.Column("signal_source", sa.String(20), nullable=True),
        sa.Column("window_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "metadata_json",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema="tenant",
    )

    # RLS for outcome_records
    op.execute(
        f'ALTER TABLE "{schema}".outcome_records ENABLE ROW LEVEL SECURITY'
    )
    op.execute(
        f'ALTER TABLE "{schema}".outcome_records FORCE ROW LEVEL SECURITY'
    )
    op.execute(f"""
        CREATE POLICY tenant_isolation ON "{schema}".outcome_records
        FOR ALL
        USING (tenant_id::text = current_setting('app.current_tenant_id', true))
        WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true))
    """)

    # Indexes for outcome_records
    op.execute(
        f'CREATE INDEX idx_outcome_records_tenant_action_created '
        f'ON "{schema}".outcome_records(tenant_id, action_type, created_at)'
    )
    op.execute(
        f'CREATE INDEX idx_outcome_records_tenant_status_created '
        f'ON "{schema}".outcome_records(tenant_id, outcome_status, created_at)'
    )
    op.execute(
        f'CREATE INDEX idx_outcome_records_tenant_type_status '
        f'ON "{schema}".outcome_records(tenant_id, outcome_type, outcome_status)'
    )

    # ── feedback_entries ─────────────────────────────────────────────────

    op.create_table(
        "feedback_entries",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("outcome_record_id", UUID(as_uuid=True), nullable=True),
        sa.Column("conversation_state_id", UUID(as_uuid=True), nullable=False),
        sa.Column("target_type", sa.String(20), nullable=False),
        sa.Column("target_id", sa.String(100), nullable=False),
        sa.Column("source", sa.String(20), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.String(1000), nullable=True),
        sa.Column("reviewer_id", UUID(as_uuid=True), nullable=False),
        sa.Column("reviewer_role", sa.String(20), nullable=False),
        sa.Column(
            "metadata_json",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        schema="tenant",
    )

    # RLS for feedback_entries
    op.execute(
        f'ALTER TABLE "{schema}".feedback_entries ENABLE ROW LEVEL SECURITY'
    )
    op.execute(
        f'ALTER TABLE "{schema}".feedback_entries FORCE ROW LEVEL SECURITY'
    )
    op.execute(f"""
        CREATE POLICY tenant_isolation ON "{schema}".feedback_entries
        FOR ALL
        USING (tenant_id::text = current_setting('app.current_tenant_id', true))
        WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true))
    """)

    # Indexes for feedback_entries
    op.execute(
        f'CREATE INDEX idx_feedback_entries_tenant_conversation '
        f'ON "{schema}".feedback_entries(tenant_id, conversation_state_id)'
    )
    op.execute(
        f'CREATE INDEX idx_feedback_entries_tenant_reviewer_created '
        f'ON "{schema}".feedback_entries(tenant_id, reviewer_id, created_at)'
    )

    # ── calibration_bins ─────────────────────────────────────────────────

    op.create_table(
        "calibration_bins",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("action_type", sa.String(50), nullable=False),
        sa.Column("bin_index", sa.Integer(), nullable=False),
        sa.Column("bin_lower", sa.Float(), nullable=False),
        sa.Column("bin_upper", sa.Float(), nullable=False),
        sa.Column(
            "sample_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "outcome_sum",
            sa.Float(),
            server_default=sa.text("0.0"),
            nullable=False,
        ),
        sa.Column("actual_rate", sa.Float(), nullable=True),
        sa.Column("brier_contribution", sa.Float(), nullable=True),
        sa.Column("last_updated", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "tenant_id",
            "action_type",
            "bin_index",
            name="uq_calibration_bin_tenant_action_bin",
        ),
        schema="tenant",
    )

    # RLS for calibration_bins
    op.execute(
        f'ALTER TABLE "{schema}".calibration_bins ENABLE ROW LEVEL SECURITY'
    )
    op.execute(
        f'ALTER TABLE "{schema}".calibration_bins FORCE ROW LEVEL SECURITY'
    )
    op.execute(f"""
        CREATE POLICY tenant_isolation ON "{schema}".calibration_bins
        FOR ALL
        USING (tenant_id::text = current_setting('app.current_tenant_id', true))
        WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true))
    """)

    # Index for calibration_bins
    op.execute(
        f'CREATE INDEX idx_calibration_bins_tenant_action '
        f'ON "{schema}".calibration_bins(tenant_id, action_type)'
    )


def downgrade() -> None:
    cmd_kwargs = context.get_x_argument(as_dictionary=True)
    schema = cmd_kwargs.get("schema", "tenant")

    # Drop policies first, then tables
    for table in ["calibration_bins", "feedback_entries", "outcome_records"]:
        op.execute(
            f'DROP POLICY IF EXISTS tenant_isolation '
            f'ON "{schema}".{table}'
        )
        op.drop_table(table, schema="tenant")
