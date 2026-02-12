"""Add conversation_states table for sales agent state persistence.

Revision ID: 004_conversation_states
Revises: 002_initial_tenant
Create Date: 2026-02-12

Creates the conversation_states table in tenant schema for persisting
sales conversation state including deal stage, qualification data (BANT/MEDDIC
as JSON), interaction tracking, and escalation status. Includes indexes
on (tenant_id, account_id) for fast lookup and (tenant_id, deal_stage)
for pipeline queries.
"""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "004_conversation_states"
down_revision: Union[str, None] = "002_initial_tenant"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Get the actual schema name from -x args
    cmd_kwargs = context.get_x_argument(as_dictionary=True)
    schema = cmd_kwargs.get("schema", "tenant")

    op.create_table(
        "conversation_states",
        sa.Column(
            "id",
            UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("account_id", sa.String(100), nullable=False),
        sa.Column("contact_id", sa.String(100), nullable=False),
        sa.Column("contact_email", sa.String(255), nullable=False),
        sa.Column("contact_name", sa.String(200), nullable=True),
        sa.Column(
            "deal_stage",
            sa.String(50),
            server_default=sa.text("'prospecting'"),
            nullable=False,
        ),
        sa.Column(
            "persona_type",
            sa.String(20),
            server_default=sa.text("'manager'"),
            nullable=False,
        ),
        sa.Column(
            "qualification_data",
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
        sa.Column("last_channel", sa.String(20), nullable=True),
        sa.Column(
            "escalated",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column("escalation_reason", sa.String(500), nullable=True),
        sa.Column(
            "confidence_score",
            sa.Float(),
            server_default=sa.text("0.5"),
            nullable=False,
        ),
        sa.Column(
            "next_actions",
            sa.JSON(),
            server_default=sa.text("'[]'::json"),
            nullable=False,
        ),
        sa.Column("follow_up_scheduled", sa.DateTime(timezone=True), nullable=True),
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
            "contact_id",
            name="uq_conversation_state_tenant_account_contact",
        ),
        schema="tenant",
    )

    # Enable and FORCE Row Level Security
    op.execute(
        f'ALTER TABLE "{schema}".conversation_states ENABLE ROW LEVEL SECURITY'
    )
    op.execute(
        f'ALTER TABLE "{schema}".conversation_states FORCE ROW LEVEL SECURITY'
    )

    # Create RLS policy for tenant isolation
    op.execute(f"""
        CREATE POLICY tenant_isolation ON "{schema}".conversation_states
        FOR ALL
        USING (tenant_id::text = current_setting('app.current_tenant_id', true))
        WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true))
    """)

    # Index for fast lookup by tenant + account
    op.execute(
        f'CREATE INDEX idx_conv_states_tenant_account '
        f'ON "{schema}".conversation_states(tenant_id, account_id)'
    )

    # Index for pipeline queries by tenant + deal stage
    op.execute(
        f'CREATE INDEX idx_conv_states_tenant_stage '
        f'ON "{schema}".conversation_states(tenant_id, deal_stage)'
    )


def downgrade() -> None:
    cmd_kwargs = context.get_x_argument(as_dictionary=True)
    schema = cmd_kwargs.get("schema", "tenant")

    op.execute(
        f'DROP POLICY IF EXISTS tenant_isolation '
        f'ON "{schema}".conversation_states'
    )
    op.drop_table("conversation_states", schema="tenant")
