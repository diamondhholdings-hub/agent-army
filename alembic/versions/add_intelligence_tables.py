"""Add intelligence and autonomy tables for Phase 7.

Revision ID: 008_intelligence_tables
Revises: 007_meeting_tables
Create Date: 2026-02-16

Creates five tables in the tenant schema for intelligence & autonomy:
- agent_clones: Persona configuration per agent clone
- insights: Detected patterns and alerts for human review
- goals: Revenue targets and activity metrics
- autonomous_actions: Audit trail of autonomous decisions
- alert_feedback: Feedback on alert usefulness for threshold tuning

All tables include RLS policies for tenant isolation and indexes
for common query patterns. No foreign key constraints (application-level
referential integrity via repository, consistent with Phase 5/6 pattern).
"""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "008_intelligence_tables"
down_revision: Union[str, None] = "007_meeting_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Get the actual schema name from -x args
    cmd_kwargs = context.get_x_argument(as_dictionary=True)
    schema = cmd_kwargs.get("schema", "tenant")

    # ── agent_clones table ────────────────────────────────────────────────

    op.create_table(
        "agent_clones",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("clone_name", sa.String(200), nullable=False),
        sa.Column("owner_id", sa.String(100), nullable=False),
        sa.Column(
            "persona_config",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
        sa.Column(
            "active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "tenant_id", "clone_name", name="uq_clone_tenant_name"
        ),
        schema="tenant",
    )

    op.execute(f'ALTER TABLE "{schema}".agent_clones ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{schema}".agent_clones FORCE ROW LEVEL SECURITY')
    op.execute(f"""
        CREATE POLICY tenant_isolation ON "{schema}".agent_clones
        FOR ALL
        USING (tenant_id::text = current_setting('app.current_tenant_id', true))
        WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true))
    """)
    op.execute(
        f'CREATE INDEX idx_agent_clones_tenant_active '
        f'ON "{schema}".agent_clones(tenant_id, active)'
    )

    # ── insights table ────────────────────────────────────────────────────

    op.create_table(
        "insights",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", sa.String(100), nullable=False),
        sa.Column("pattern_type", sa.String(50), nullable=False),
        sa.Column(
            "pattern_data",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column(
            "severity",
            sa.String(20),
            server_default=sa.text("'medium'"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(20),
            server_default=sa.text("'pending'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("acted_at", sa.DateTime(timezone=True), nullable=True),
        schema="tenant",
    )

    op.execute(f'ALTER TABLE "{schema}".insights ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{schema}".insights FORCE ROW LEVEL SECURITY')
    op.execute(f"""
        CREATE POLICY tenant_isolation ON "{schema}".insights
        FOR ALL
        USING (tenant_id::text = current_setting('app.current_tenant_id', true))
        WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true))
    """)
    op.execute(
        f'CREATE INDEX idx_insights_tenant_status_created '
        f'ON "{schema}".insights(tenant_id, status, created_at)'
    )
    op.execute(
        f'CREATE INDEX idx_insights_tenant_account '
        f'ON "{schema}".insights(tenant_id, account_id)'
    )
    # GIN index for JSONB pattern_data queries
    op.execute(
        f'CREATE INDEX idx_insights_pattern_data_gin '
        f'ON "{schema}".insights USING gin (pattern_data)'
    )

    # ── goals table ───────────────────────────────────────────────────────

    op.create_table(
        "goals",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("clone_id", UUID(as_uuid=True), nullable=True),
        sa.Column("goal_type", sa.String(50), nullable=False),
        sa.Column("target_value", sa.Float(), nullable=False),
        sa.Column(
            "current_value",
            sa.Float(),
            server_default=sa.text("0.0"),
            nullable=False,
        ),
        sa.Column("period_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("period_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "status",
            sa.String(20),
            server_default=sa.text("'active'"),
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

    op.execute(f'ALTER TABLE "{schema}".goals ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{schema}".goals FORCE ROW LEVEL SECURITY')
    op.execute(f"""
        CREATE POLICY tenant_isolation ON "{schema}".goals
        FOR ALL
        USING (tenant_id::text = current_setting('app.current_tenant_id', true))
        WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true))
    """)
    op.execute(
        f'CREATE INDEX idx_goals_tenant_status '
        f'ON "{schema}".goals(tenant_id, status)'
    )
    op.execute(
        f'CREATE INDEX idx_goals_tenant_clone '
        f'ON "{schema}".goals(tenant_id, clone_id)'
    )

    # ── autonomous_actions table ──────────────────────────────────────────

    op.create_table(
        "autonomous_actions",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("action_type", sa.String(50), nullable=False),
        sa.Column("account_id", sa.String(100), nullable=False),
        sa.Column(
            "action_data",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
        sa.Column(
            "proposed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("executed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("execution_result", sa.JSON(), nullable=True),
        sa.Column("approval_status", sa.String(20), nullable=True),
        sa.Column("approved_by", sa.String(100), nullable=True),
        sa.Column("approved_at", sa.DateTime(timezone=True), nullable=True),
        schema="tenant",
    )

    op.execute(
        f'ALTER TABLE "{schema}".autonomous_actions ENABLE ROW LEVEL SECURITY'
    )
    op.execute(
        f'ALTER TABLE "{schema}".autonomous_actions FORCE ROW LEVEL SECURITY'
    )
    op.execute(f"""
        CREATE POLICY tenant_isolation ON "{schema}".autonomous_actions
        FOR ALL
        USING (tenant_id::text = current_setting('app.current_tenant_id', true))
        WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true))
    """)
    op.execute(
        f'CREATE INDEX idx_actions_tenant_approval_proposed '
        f'ON "{schema}".autonomous_actions(tenant_id, approval_status, proposed_at)'
    )
    op.execute(
        f'CREATE INDEX idx_actions_tenant_account '
        f'ON "{schema}".autonomous_actions(tenant_id, account_id)'
    )
    # GIN index for JSONB action_data queries
    op.execute(
        f'CREATE INDEX idx_actions_action_data_gin '
        f'ON "{schema}".autonomous_actions USING gin (action_data)'
    )

    # ── alert_feedback table ──────────────────────────────────────────────

    op.create_table(
        "alert_feedback",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("insight_id", UUID(as_uuid=True), nullable=False),
        sa.Column("feedback", sa.String(20), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column(
            "submitted_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("submitted_by", sa.String(100), nullable=False),
        schema="tenant",
    )

    op.execute(
        f'ALTER TABLE "{schema}".alert_feedback ENABLE ROW LEVEL SECURITY'
    )
    op.execute(
        f'ALTER TABLE "{schema}".alert_feedback FORCE ROW LEVEL SECURITY'
    )
    op.execute(f"""
        CREATE POLICY tenant_isolation ON "{schema}".alert_feedback
        FOR ALL
        USING (tenant_id::text = current_setting('app.current_tenant_id', true))
        WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true))
    """)
    op.execute(
        f'CREATE INDEX idx_feedback_tenant_feedback '
        f'ON "{schema}".alert_feedback(tenant_id, feedback)'
    )
    op.execute(
        f'CREATE INDEX idx_feedback_tenant_insight '
        f'ON "{schema}".alert_feedback(tenant_id, insight_id)'
    )


def downgrade() -> None:
    cmd_kwargs = context.get_x_argument(as_dictionary=True)
    schema = cmd_kwargs.get("schema", "tenant")

    # Drop policies then tables in reverse order

    op.execute(
        f'DROP POLICY IF EXISTS tenant_isolation '
        f'ON "{schema}".alert_feedback'
    )
    op.drop_table("alert_feedback", schema="tenant")

    op.execute(
        f'DROP POLICY IF EXISTS tenant_isolation '
        f'ON "{schema}".autonomous_actions'
    )
    op.drop_table("autonomous_actions", schema="tenant")

    op.execute(
        f'DROP POLICY IF EXISTS tenant_isolation '
        f'ON "{schema}".goals'
    )
    op.drop_table("goals", schema="tenant")

    op.execute(
        f'DROP POLICY IF EXISTS tenant_isolation '
        f'ON "{schema}".insights'
    )
    op.drop_table("insights", schema="tenant")

    op.execute(
        f'DROP POLICY IF EXISTS tenant_isolation '
        f'ON "{schema}".agent_clones'
    )
    op.drop_table("agent_clones", schema="tenant")
