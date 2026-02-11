"""Initial tenant schema: users table with RLS.

Revision ID: 002_initial_tenant
Revises:
Create Date: 2026-02-11

Note: This migration uses schema="tenant" placeholder. When run via
schema_translate_map, "tenant" is replaced with the actual tenant schema.
However, for RLS and index DDL we use the actual schema name from -x args.
"""

from typing import Sequence, Union

from alembic import context, op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "002_initial_tenant"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = ("tenant",)
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Get the actual schema name from -x args
    cmd_kwargs = context.get_x_argument(as_dictionary=True)
    schema = cmd_kwargs.get("schema", "tenant")

    # Create the users table (schema_translate_map handles the schema)
    op.create_table(
        "users",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("email", sa.String(255), nullable=False),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column("role", sa.String(50), server_default=sa.text("'member'"), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        schema="tenant",
    )

    # Enable and FORCE Row Level Security
    op.execute(f'ALTER TABLE "{schema}".users ENABLE ROW LEVEL SECURITY')
    op.execute(f'ALTER TABLE "{schema}".users FORCE ROW LEVEL SECURITY')

    # Create RLS policy for tenant isolation
    op.execute(f"""
        CREATE POLICY tenant_isolation ON "{schema}".users
        FOR ALL
        USING (tenant_id::text = current_setting('app.current_tenant_id', true))
        WITH CHECK (tenant_id::text = current_setting('app.current_tenant_id', true))
    """)

    # Performance index on tenant_id
    op.execute(f'CREATE INDEX idx_users_tenant ON "{schema}".users(tenant_id)')

    # Unique constraint scoped to tenant (prevents cross-tenant data leakage)
    op.execute(f'CREATE UNIQUE INDEX idx_users_email_tenant ON "{schema}".users(tenant_id, lower(email))')


def downgrade() -> None:
    cmd_kwargs = context.get_x_argument(as_dictionary=True)
    schema = cmd_kwargs.get("schema", "tenant")

    op.execute(f'DROP POLICY IF EXISTS tenant_isolation ON "{schema}".users')
    op.drop_table("users", schema="tenant")
