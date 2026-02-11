"""Multi-tenant migration helpers.

Provides functions to run Alembic migrations across all tenant schemas
or for a specific tenant schema.
"""

from __future__ import annotations

from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, text

from src.app.config import get_settings


def _get_alembic_config() -> Config:
    """Create an Alembic Config pointing to our alembic.ini."""
    config = Config("alembic.ini")
    return config


def migrate_tenant(schema_name: str, direction: str = "upgrade", revision: str = "head") -> None:
    """Run migration for a single tenant schema.

    Args:
        schema_name: The tenant schema name (e.g., "tenant_skyvera")
        direction: "upgrade" or "downgrade"
        revision: Target revision (default: "head")
    """
    config = _get_alembic_config()
    config.set_main_option("x", f"schema={schema_name}")

    if direction == "upgrade":
        command.upgrade(config, revision, x=[f"schema={schema_name}"])
    elif direction == "downgrade":
        command.downgrade(config, revision, x=[f"schema={schema_name}"])
    else:
        raise ValueError(f"Invalid direction: {direction}")


def migrate_all_tenants(direction: str = "upgrade", revision: str = "head") -> list[str]:
    """Run migrations for all active tenant schemas.

    Queries the shared.tenants table, iterates over all active tenant schemas,
    and runs Alembic migration for each.

    Returns:
        List of schema names that were migrated.
    """
    settings = get_settings()
    sync_url = settings.DATABASE_URL.replace("+asyncpg", "")
    engine = create_engine(sync_url)

    migrated = []
    with engine.connect() as conn:
        result = conn.execute(
            text("SELECT schema_name FROM shared.tenants WHERE is_active = true")
        )
        schemas = [row[0] for row in result]

    for schema_name in schemas:
        migrate_tenant(schema_name, direction, revision)
        migrated.append(schema_name)

    engine.dispose()
    return migrated
