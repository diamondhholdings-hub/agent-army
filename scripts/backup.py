#!/usr/bin/env python3
"""Per-tenant backup script using pg_dump.

Usage:
    uv run python scripts/backup.py --tenant skyvera --output ./backups/
    uv run python scripts/backup.py --all --output ./backups/

Backs up tenant schemas using pg_dump in custom format (-Fc) for efficient
storage and parallel restore support.

Reads DATABASE_URL from environment or .env file.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
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
    """Parse DATABASE_URL into pg_dump connection parameters.

    Converts asyncpg:// URLs to standard postgresql:// for pg_dump.
    """
    # Replace asyncpg scheme with postgresql for pg_dump
    url = database_url.replace("postgresql+asyncpg://", "postgresql://")
    parsed = urlparse(url)
    return {
        "host": parsed.hostname or "localhost",
        "port": str(parsed.port or 5432),
        "user": parsed.username or "agent_army",
        "password": parsed.password or "",
        "dbname": parsed.path.lstrip("/") or "agent_army",
    }


def run_pg_dump(conn_params: dict, schema: str, output_file: str) -> bool:
    """Run pg_dump for a specific schema in custom format."""
    env = os.environ.copy()
    env["PGPASSWORD"] = conn_params["password"]

    cmd = [
        find_pg_tool("pg_dump"),
        "-h", conn_params["host"],
        "-p", conn_params["port"],
        "-U", conn_params["user"],
        "-d", conn_params["dbname"],
        "--schema", schema,
        "-Fc",  # Custom format (compressed, supports parallel restore)
        "-f", output_file,
    ]

    try:
        result = subprocess.run(cmd, env=env, capture_output=True, text=True, timeout=300)
        if result.returncode != 0:
            logger.error("pg_dump failed", schema=schema, stderr=result.stderr)
            return False
        logger.info("pg_dump completed", schema=schema, output=output_file)
        return True
    except subprocess.TimeoutExpired:
        logger.error("pg_dump timed out", schema=schema)
        return False
    except FileNotFoundError:
        logger.error("pg_dump not found -- install postgresql-client")
        return False


async def disable_force_rls(database_url: str, schema_name: str) -> list[str]:
    """Temporarily disable FORCE RLS on all tables in a schema for pg_dump.

    Returns list of table names that had FORCE RLS enabled (for re-enabling).
    """
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(database_url)
    tables_with_rls = []
    try:
        async with engine.begin() as conn:
            # Find all tables with RLS FORCE enabled
            result = await conn.execute(
                text("""
                    SELECT tablename FROM pg_tables
                    WHERE schemaname = :schema
                """),
                {"schema": schema_name},
            )
            for row in result.fetchall():
                table = row.tablename
                # Check if FORCE is enabled by querying pg_class
                rls_check = await conn.execute(
                    text("""
                        SELECT relforcerowsecurity
                        FROM pg_class c
                        JOIN pg_namespace n ON c.relnamespace = n.oid
                        WHERE n.nspname = :schema AND c.relname = :table
                    """),
                    {"schema": schema_name, "table": table},
                )
                rls_row = rls_check.first()
                if rls_row and rls_row.relforcerowsecurity:
                    await conn.execute(text(f'ALTER TABLE "{schema_name}"."{table}" NO FORCE ROW LEVEL SECURITY'))
                    tables_with_rls.append(table)
                    logger.info("Disabled FORCE RLS for backup", schema=schema_name, table=table)
    finally:
        await engine.dispose()
    return tables_with_rls


async def enable_force_rls(database_url: str, schema_name: str, tables: list[str]) -> None:
    """Re-enable FORCE RLS on tables after pg_dump."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(database_url)
    try:
        async with engine.begin() as conn:
            for table in tables:
                await conn.execute(text(f'ALTER TABLE "{schema_name}"."{table}" FORCE ROW LEVEL SECURITY'))
                logger.info("Re-enabled FORCE RLS after backup", schema=schema_name, table=table)
    finally:
        await engine.dispose()


async def get_all_tenant_schemas(database_url: str) -> list[dict]:
    """Query shared.tenants to get all active tenant schemas."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(
                text("SELECT slug, schema_name FROM shared.tenants WHERE is_active = true ORDER BY slug")
            )
            return [{"slug": row.slug, "schema_name": row.schema_name} for row in result.fetchall()]
    finally:
        await engine.dispose()


async def backup_tenant(database_url: str, tenant_slug: str, output_dir: str) -> dict | None:
    """Backup a single tenant's schema."""
    schema_name = f"tenant_{tenant_slug.replace('-', '_')}"
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    output_file = os.path.join(output_dir, f"{tenant_slug}_{timestamp}.dump")

    conn_params = parse_database_url(database_url)

    # Temporarily disable FORCE RLS so pg_dump can read all rows
    rls_tables = await disable_force_rls(database_url, schema_name)
    try:
        success = run_pg_dump(conn_params, schema_name, output_file)
    finally:
        # Always re-enable FORCE RLS
        if rls_tables:
            await enable_force_rls(database_url, schema_name, rls_tables)

    if success and os.path.exists(output_file):
        size_bytes = os.path.getsize(output_file)
        return {
            "tenant": tenant_slug,
            "schema": schema_name,
            "file": output_file,
            "size_bytes": size_bytes,
            "timestamp": timestamp,
        }
    return None


async def backup_all(database_url: str, output_dir: str) -> list[dict]:
    """Backup shared schema and all tenant schemas."""
    results = []

    # Backup shared schema
    conn_params = parse_database_url(database_url)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    shared_file = os.path.join(output_dir, f"shared_{timestamp}.dump")
    if run_pg_dump(conn_params, "shared", shared_file):
        results.append({
            "tenant": "shared",
            "schema": "shared",
            "file": shared_file,
            "size_bytes": os.path.getsize(shared_file),
            "timestamp": timestamp,
        })

    # Backup all tenant schemas
    tenants = await get_all_tenant_schemas(database_url)
    for tenant in tenants:
        output_file = os.path.join(output_dir, f"{tenant['slug']}_{timestamp}.dump")
        # Temporarily disable FORCE RLS for backup
        rls_tables = await disable_force_rls(database_url, tenant["schema_name"])
        try:
            success = run_pg_dump(conn_params, tenant["schema_name"], output_file)
        finally:
            if rls_tables:
                await enable_force_rls(database_url, tenant["schema_name"], rls_tables)
        if success:
            results.append({
                "tenant": tenant["slug"],
                "schema": tenant["schema_name"],
                "file": output_file,
                "size_bytes": os.path.getsize(output_file),
                "timestamp": timestamp,
            })

    return results


async def main_async(args: argparse.Namespace) -> None:
    database_url = os.environ.get("DATABASE_URL", "postgresql+asyncpg://agent_army:agent_army_dev@localhost:5432/agent_army")

    # Create output directory
    os.makedirs(args.output, exist_ok=True)

    if args.all:
        logger.info("Starting full backup (all tenants)")
        results = await backup_all(database_url, args.output)
    elif args.tenant:
        logger.info("Starting single tenant backup", tenant=args.tenant)
        result = await backup_tenant(database_url, args.tenant, args.output)
        results = [result] if result else []
    else:
        print("Error: specify --tenant <slug> or --all")
        sys.exit(1)

    # Write manifest
    if results:
        timestamp = results[0]["timestamp"]
        manifest_file = os.path.join(args.output, f"manifest_{timestamp}.json")
        manifest = {
            "timestamp": timestamp,
            "database_url_host": parse_database_url(database_url)["host"],
            "schemas_backed_up": len(results),
            "total_size_bytes": sum(r["size_bytes"] for r in results),
            "backups": results,
        }
        with open(manifest_file, "w") as f:
            json.dump(manifest, f, indent=2)
        logger.info("Manifest written", file=manifest_file)

        print(f"\nBackup complete: {len(results)} schema(s)")
        for r in results:
            print(f"  {r['tenant']:20s} -> {r['file']} ({r['size_bytes']:,} bytes)")
    else:
        print("No backups created.")
        sys.exit(1)


def main() -> None:
    parser = argparse.ArgumentParser(description="Backup tenant schemas")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--tenant", help="Tenant slug to backup")
    group.add_argument("--all", action="store_true", help="Backup all tenants")
    parser.add_argument("--output", required=True, help="Output directory for backup files")
    args = parser.parse_args()

    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
