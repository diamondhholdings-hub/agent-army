"""Initial shared schema: tenants table.

Revision ID: 001_initial_shared
Revises:
Create Date: 2026-02-11

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID, JSON

# revision identifiers, used by Alembic.
revision: str = "001_initial_shared"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = ("shared",)
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create the shared schema
    op.execute("CREATE SCHEMA IF NOT EXISTS shared")

    # Create the tenants table in shared schema
    op.create_table(
        "tenants",
        sa.Column("id", UUID(as_uuid=True), primary_key=True, server_default=sa.text("gen_random_uuid()")),
        sa.Column("slug", sa.String(50), unique=True, nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("schema_name", sa.String(100), unique=True, nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("config", JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        schema="shared",
    )


def downgrade() -> None:
    op.drop_table("tenants", schema="shared")
    op.execute("DROP SCHEMA IF EXISTS shared CASCADE")
