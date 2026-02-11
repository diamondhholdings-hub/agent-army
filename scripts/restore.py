#!/usr/bin/env python3
"""Per-tenant restore script using pg_restore.

Usage:
    uv run python scripts/restore.py --file ./backups/skyvera_20260210_120000.dump --tenant skyvera
    uv run python scripts/restore.py --file ./backups/skyvera_20260210_120000.dump --tenant skyvera --yes

Restores a tenant's schema from a custom-format pg_dump backup file.
Safety check: prompts for confirmation before restoring (bypass with --yes).
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from urllib.parse import urlparse

# Ensure project root is on sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))

import structlog  # noqa: E402

logger = structlog.get_logger(__name__)


def find_pg_tool(tool_name: str) -> str:
    """Find a PostgreSQL CLI tool (pg_dump, pg_restore) in PATH or common locations."""
    import shutil

    path = shutil.which(tool_name)
    if path:
        return path

    # Check common Homebrew locations
    for prefix in ["/opt/homebrew", "/usr/local"]:
        import glob

        matches = glob.glob(f"{prefix}/Cellar/postgresql*/*/bin/{tool_name}")
        matches += glob.glob(f"{prefix}/opt/postgresql*/bin/{tool_name}")
        if matches:
            return sorted(matches)[-1]  # Use latest version

    return tool_name  # Fall back to bare name (will fail with clear error)


def parse_database_url(database_url: str) -> dict:
    """Parse DATABASE_URL into connection parameters."""
    url = database_url.replace("postgresql+asyncpg://", "postgresql://")
    parsed = urlparse(url)
    return {
        "host": parsed.hostname or "localhost",
        "port": str(parsed.port or 5432),
        "user": parsed.username or "agent_army",
        "password": parsed.password or "",
        "dbname": parsed.path.lstrip("/") or "agent_army",
    }


async def drop_schema(database_url: str, schema_name: str) -> bool:
    """Drop existing schema with CASCADE before restore."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as conn:
            await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema_name}" CASCADE'))
        logger.info("Dropped existing schema", schema=schema_name)
        return True
    except Exception as e:
        logger.error("Failed to drop schema", schema=schema_name, error=str(e))
        return False
    finally:
        await engine.dispose()


def run_pg_restore(conn_params: dict, backup_file: str) -> bool:
    """Run pg_restore from a custom-format dump file."""
    env = os.environ.copy()
    env["PGPASSWORD"] = conn_params["password"]

    cmd = [
        find_pg_tool("pg_restore"),
        "-h", conn_params["host"],
        "-p", conn_params["port"],
        "-U", conn_params["user"],
        "-d", conn_params["dbname"],
        "--no-owner",        # Don't restore ownership
        "--no-privileges",   # Don't restore privileges (re-apply via provisioning)
        backup_file,
    ]

    try:
        result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=600)
        if result.returncode != 0:
            # pg_restore returns non-zero for warnings too; check stderr
            if "ERROR" in result.stderr:
                logger.error("pg_restore failed", stderr=result.stderr)
                return False
            else:
                logger.warning("pg_restore completed with warnings", stderr=result.stderr)
        logger.info("pg_restore completed", file=backup_file)
        return True
    except subprocess.TimeoutExpired:
        logger.error("pg_restore timed out")
        return False
    except FileNotFoundError:
        logger.error("pg_restore not found -- install postgresql-client")
        return False


async def verify_rls_policies(database_url: str, schema_name: str) -> bool:
    """Verify RLS policies are intact after restore."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            # Check if RLS is enabled on tables in the schema
            result = await conn.execute(
                text("""
                    SELECT tablename, rowsecurity
                    FROM pg_tables
                    WHERE schemaname = :schema
                """),
                {"schema": schema_name},
            )
            tables = result.fetchall()

            if not tables:
                logger.warning("No tables found in schema", schema=schema_name)
                return False

            all_rls = True
            for table in tables:
                if not table.rowsecurity:
                    logger.warning("RLS not enabled", schema=schema_name, table=table.tablename)
                    all_rls = False

            # Check for tenant_isolation policy
            result = await conn.execute(
                text("""
                    SELECT schemaname, tablename, policyname
                    FROM pg_policies
                    WHERE schemaname = :schema
                """),
                {"schema": schema_name},
            )
            policies = result.fetchall()
            if not policies:
                logger.warning("No RLS policies found", schema=schema_name)
                all_rls = False
            else:
                for p in policies:
                    logger.info("RLS policy found", schema=p.schemaname, table=p.tablename, policy=p.policyname)

            return all_rls
    finally:
        await engine.dispose()


async def ensure_tenant_registered(database_url: str, tenant_slug: str, schema_name: str) -> None:
    """Re-register tenant in shared.tenants if not present."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as conn:
            result = await conn.execute(
                text("SELECT id FROM shared.tenants WHERE slug = :slug"),
                {"slug": tenant_slug},
            )
            if result.first():
                logger.info("Tenant already registered", slug=tenant_slug)
                return

            import uuid
            await conn.execute(
                text("""
                    INSERT INTO shared.tenants (id, slug, name, schema_name, is_active, created_at)
                    VALUES (:id, :slug, :name, :schema_name, true, now())
                """),
                {
                    "id": uuid.uuid4(),
                    "slug": tenant_slug,
                    "name": tenant_slug.replace("-", " ").title(),
                    "schema_name": schema_name,
                },
            )
            logger.info("Tenant re-registered", slug=tenant_slug)
    finally:
        await engine.dispose()


async def main_async(args: argparse.Namespace) -> None:
    database_url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://agent_army:agent_army_dev@localhost:5432/agent_army")

    schema_name = f"tenant_{args.tenant.replace('-', '_')}"

    # Validate backup file exists
    if not os.path.exists(args.file):
        print(f"Error: backup file not found: {args.file}")
        sys.exit(1)

    # Safety confirmation
    if not args.yes:
        print(f"WARNING: This will DROP and REPLACE the schema '{schema_name}'.")
        print(f"  Backup file: {args.file}")
        print(f"  Tenant slug: {args.tenant}")
        confirm = input("Type 'yes' to proceed: ")
        if confirm.strip().lower() != "yes":
            print("Aborted.")
            sys.exit(0)

    conn_params = parse_database_url(database_url)

    # Step 1: Drop existing schema
    print(f"Dropping schema '{schema_name}'...")
    if not await drop_schema(database_url, schema_name):
        print("Failed to drop schema. Aborting.")
        sys.exit(1)

    # Step 2: Restore from backup
    print(f"Restoring from '{args.file}'...")
    if not run_pg_restore(conn_params, args.file):
        print("Restore failed. Schema may be in an inconsistent state.")
        sys.exit(1)

    # Step 3: Verify RLS policies
    print("Verifying RLS policies...")
    rls_ok = await verify_rls_policies(database_url, schema_name)
    if rls_ok:
        print("RLS policies verified.")
    else:
        print("WARNING: RLS policies may need to be re-applied.")
        print("  Run: uv run python scripts/provision_tenant.py to re-create RLS policies if needed.")

    # Step 4: Ensure tenant is registered in shared.tenants
    await ensure_tenant_registered(database_url, args.tenant, schema_name)

    print(f"\nRestore complete: {args.tenant} -> {schema_name}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Restore a tenant schema from backup")
    parser.add_argument("--file", required=True, help="Path to the .dump backup file")
    parser.add_argument("--tenant", required=True, help="Tenant slug to restore")
    parser.add_argument("--yes", action="store_true", help="Skip confirmation prompt")
    args = parser.parse_args()

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
