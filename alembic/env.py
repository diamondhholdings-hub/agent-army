"""Alembic environment for multi-tenant schema migrations.

Supports two migration modes via -x argument:
  alembic -x schema=shared upgrade head      -- shared schema only
  alembic -x schema=tenant_skyvera upgrade head  -- specific tenant schema

Each schema gets its own alembic_version table so migrations
are tracked independently per tenant.
"""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import create_engine, pool, text

from src.app.core.database import SharedBase, TenantBase
from src.app.config import get_settings

# Alembic Config object
config = context.config

# Interpret the config file for Python logging
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# Get schema from -x args
cmd_kwargs = context.get_x_argument(as_dictionary=True)
target_schema = cmd_kwargs.get("schema", "shared")

# Select metadata based on schema type
if target_schema == "shared":
    target_metadata = SharedBase.metadata
else:
    target_metadata = TenantBase.metadata


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    settings = get_settings()
    url = settings.DATABASE_URL.replace("+asyncpg", "")

    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        version_table_schema=target_schema,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    settings = get_settings()
    url = settings.DATABASE_URL.replace("+asyncpg", "")

    connectable = create_engine(url, poolclass=pool.NullPool)

    with connectable.connect() as connection:
        # Ensure the target schema exists before Alembic tries to create
        # its version table there
        connection.execute(text(f'CREATE SCHEMA IF NOT EXISTS "{target_schema}"'))
        connection.commit()

        # For tenant schemas, apply schema_translate_map
        if target_schema != "shared":
            schema_translate_map = {"tenant": target_schema}
        else:
            schema_translate_map = None

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            version_table_schema=target_schema,
            include_schemas=True,
            schema_translate_map=schema_translate_map,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
