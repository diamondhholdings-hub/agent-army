"""Add deal management tables for accounts, opportunities, stakeholders, and plans.

Revision ID: 006_deal_management
Revises: 005_learning_tables
Create Date: 2026-02-12

Creates five tables in the tenant schema for deal lifecycle management:
- accounts: Company accounts being pursued
- opportunities: Individual deals/opportunities within accounts
- stakeholders: Contacts with political mapping scores
- account_plans: Strategic account plans (JSON document)
- opportunity_plans: Tactical opportunity plans (JSON document)

All tables include RLS policies for tenant isolation and composite indexes
for common query patterns. No foreign key constraints (application-level
referential integrity via repository, consistent with existing pattern).
"""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "006_deal_management"
down_revision: Union[str, None] = "005_learning_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Get the actual schema name from -x args
    cmd_kwargs = context.get_x_argument(as_dictionary=True)
    schema = cmd_kwargs.get("schema", "tenant")

    # ── accounts table ──────────────────────────────────────────────────

    op.create_table(
        "accounts",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("account_name", sa.String(300), nullable=False),
        sa.Column("industry", sa.String(100), nullable=True),
        sa.Column("company_size", sa.String(50), nullable=True),
        sa.Column("website", sa.String(500), nullable=True),
        sa.Column("region", sa.String(50), nullable=True),
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
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "tenant_id", "account_name", name="uq_account_tenant_name"
        ),
        schema="tenant",
    )

    op.execute(f'ALTER TABLE "{schema}".accounts ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{schema}".accounts FORCE ROW LEVEL SECURITY')
    op.execute(f"""
        CREATE POLICY tenant_isolation ON "{schema}".accounts
        FOR ALL
        USING (tenant_id::text = current_setting('app.current_tenant_id', true))
        WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true))
    """)
    op.execute(
        f'CREATE INDEX idx_accounts_tenant_name '
        f'ON "{schema}".accounts(tenant_id, account_name)'
    )

    # ── opportunities table ─────────────────────────────────────────────

    op.create_table(
        "opportunities",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", UUID(as_uuid=True), nullable=False),
        sa.Column("external_id", sa.String(200), nullable=True),
        sa.Column("name", sa.String(300), nullable=False),
        sa.Column("product_line", sa.String(200), nullable=True),
        sa.Column(
            "deal_stage",
            sa.String(50),
            server_default=sa.text("'prospecting'"),
            nullable=False,
        ),
        sa.Column("estimated_value", sa.Float(), nullable=True),
        sa.Column(
            "probability",
            sa.Float(),
            server_default=sa.text("0.1"),
            nullable=False,
        ),
        sa.Column("close_date", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "detection_confidence",
            sa.Float(),
            server_default=sa.text("0.0"),
            nullable=False,
        ),
        sa.Column(
            "source",
            sa.String(50),
            server_default=sa.text("'agent_detected'"),
            nullable=False,
        ),
        sa.Column(
            "qualification_snapshot",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
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
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("synced_at", sa.DateTime(timezone=True), nullable=True),
        schema="tenant",
    )

    op.execute(
        f'ALTER TABLE "{schema}".opportunities ENABLE ROW LEVEL SECURITY'
    )
    op.execute(
        f'ALTER TABLE "{schema}".opportunities FORCE ROW LEVEL SECURITY'
    )
    op.execute(f"""
        CREATE POLICY tenant_isolation ON "{schema}".opportunities
        FOR ALL
        USING (tenant_id::text = current_setting('app.current_tenant_id', true))
        WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true))
    """)
    op.execute(
        f'CREATE INDEX idx_opportunities_tenant_stage '
        f'ON "{schema}".opportunities(tenant_id, deal_stage)'
    )
    op.execute(
        f'CREATE INDEX idx_opportunities_tenant_account '
        f'ON "{schema}".opportunities(tenant_id, account_id)'
    )

    # ── stakeholders table ──────────────────────────────────────────────

    op.create_table(
        "stakeholders",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", UUID(as_uuid=True), nullable=False),
        sa.Column("contact_name", sa.String(200), nullable=False),
        sa.Column("contact_email", sa.String(255), nullable=True),
        sa.Column("title", sa.String(200), nullable=True),
        sa.Column(
            "roles",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
        sa.Column(
            "decision_power",
            sa.Integer(),
            server_default=sa.text("5"),
            nullable=False,
        ),
        sa.Column(
            "influence_level",
            sa.Integer(),
            server_default=sa.text("5"),
            nullable=False,
        ),
        sa.Column(
            "relationship_strength",
            sa.Integer(),
            server_default=sa.text("3"),
            nullable=False,
        ),
        sa.Column(
            "score_sources",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
        sa.Column(
            "score_evidence",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
        sa.Column(
            "interaction_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("last_interaction", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
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
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint(
            "tenant_id",
            "account_id",
            "contact_email",
            name="uq_stakeholder_tenant_account_email",
        ),
        schema="tenant",
    )

    op.execute(
        f'ALTER TABLE "{schema}".stakeholders ENABLE ROW LEVEL SECURITY'
    )
    op.execute(
        f'ALTER TABLE "{schema}".stakeholders FORCE ROW LEVEL SECURITY'
    )
    op.execute(f"""
        CREATE POLICY tenant_isolation ON "{schema}".stakeholders
        FOR ALL
        USING (tenant_id::text = current_setting('app.current_tenant_id', true))
        WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true))
    """)
    op.execute(
        f'CREATE INDEX idx_stakeholders_tenant_account '
        f'ON "{schema}".stakeholders(tenant_id, account_id)'
    )

    # ── account_plans table ─────────────────────────────────────────────

    op.create_table(
        "account_plans",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "plan_data",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
        sa.Column(
            "version",
            sa.Integer(),
            server_default=sa.text("1"),
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
            "tenant_id", "account_id", name="uq_account_plan_tenant_account"
        ),
        schema="tenant",
    )

    op.execute(
        f'ALTER TABLE "{schema}".account_plans ENABLE ROW LEVEL SECURITY'
    )
    op.execute(
        f'ALTER TABLE "{schema}".account_plans FORCE ROW LEVEL SECURITY'
    )
    op.execute(f"""
        CREATE POLICY tenant_isolation ON "{schema}".account_plans
        FOR ALL
        USING (tenant_id::text = current_setting('app.current_tenant_id', true))
        WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true))
    """)
    op.execute(
        f'CREATE INDEX idx_account_plans_tenant_account '
        f'ON "{schema}".account_plans(tenant_id, account_id)'
    )

    # ── opportunity_plans table ─────────────────────────────────────────

    op.create_table(
        "opportunity_plans",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("opportunity_id", UUID(as_uuid=True), nullable=False),
        sa.Column(
            "plan_data",
            sa.JSON(),
            server_default=sa.text("'{}'::json"),
            nullable=False,
        ),
        sa.Column(
            "version",
            sa.Integer(),
            server_default=sa.text("1"),
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
            "tenant_id",
            "opportunity_id",
            name="uq_opportunity_plan_tenant_opportunity",
        ),
        schema="tenant",
    )

    op.execute(
        f'ALTER TABLE "{schema}".opportunity_plans ENABLE ROW LEVEL SECURITY'
    )
    op.execute(
        f'ALTER TABLE "{schema}".opportunity_plans FORCE ROW LEVEL SECURITY'
    )
    op.execute(f"""
        CREATE POLICY tenant_isolation ON "{schema}".opportunity_plans
        FOR ALL
        USING (tenant_id::text = current_setting('app.current_tenant_id', true))
        WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true))
    """)
    op.execute(
        f'CREATE INDEX idx_opportunity_plans_tenant_opportunity '
        f'ON "{schema}".opportunity_plans(tenant_id, opportunity_id)'
    )


def downgrade() -> None:
    cmd_kwargs = context.get_x_argument(as_dictionary=True)
    schema = cmd_kwargs.get("schema", "tenant")

    # Drop policies then tables in reverse order

    op.execute(
        f'DROP POLICY IF EXISTS tenant_isolation '
        f'ON "{schema}".opportunity_plans'
    )
    op.drop_table("opportunity_plans", schema="tenant")

    op.execute(
        f'DROP POLICY IF EXISTS tenant_isolation '
        f'ON "{schema}".account_plans'
    )
    op.drop_table("account_plans", schema="tenant")

    op.execute(
        f'DROP POLICY IF EXISTS tenant_isolation '
        f'ON "{schema}".stakeholders'
    )
    op.drop_table("stakeholders", schema="tenant")

    op.execute(
        f'DROP POLICY IF EXISTS tenant_isolation '
        f'ON "{schema}".opportunities'
    )
    op.drop_table("opportunities", schema="tenant")

    op.execute(
        f'DROP POLICY IF EXISTS tenant_isolation '
        f'ON "{schema}".accounts'
    )
    op.drop_table("accounts", schema="tenant")
