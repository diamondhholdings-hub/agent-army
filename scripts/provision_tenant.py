#!/usr/bin/env python3
"""CLI script to provision a new tenant.

Usage:
    uv run python scripts/provision_tenant.py --slug skyvera --name "Skyvera"
    uv run python scripts/provision_tenant.py --slug skyvera --name "Skyvera" --admin-email admin@skyvera.com --admin-password changeme

Connects directly to the database using DATABASE_URL from environment or .env file.
Provisions schema, creates tables with RLS, registers tenant in shared.tenants.
Optionally creates an initial admin user.
"""

from __future__ import annotations

import argparse
import asyncio
import os
import sys
import uuid

# Ensure project root is on sys.path so we can import src.app
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dotenv import load_dotenv  # noqa: E402

# Load .env from project root
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


async def provision(slug: str, name: str, admin_email: str | None, admin_password: str | None) -> None:
    """Provision a tenant by calling the provisioning service directly."""
    from src.app.core.database import get_engine, init_db
    from src.app.services.tenant_provisioning import provision_tenant

    # Initialize shared schema if needed
    await init_db()

    print(f"Provisioning tenant: slug={slug}, name={name}")
    result = await provision_tenant(slug=slug, name=name)
    print(f"Tenant provisioned successfully:")
    print(f"  ID:     {result['tenant_id']}")
    print(f"  Slug:   {result['slug']}")
    print(f"  Name:   {result['name']}")
    print(f"  Schema: {result['schema_name']}")

    # Optionally create admin user
    if admin_email and admin_password:
        from src.app.core.security import hash_password

        engine = get_engine()
        schema_name = result["schema_name"]
        tenant_id = result["tenant_id"]
        user_id = uuid.uuid4()

        async with engine.begin() as conn:
            from sqlalchemy import text

            await conn.execute(
                text(f"""
                    INSERT INTO "{schema_name}".users
                        (id, tenant_id, email, name, role, is_active, hashed_password, created_at)
                    VALUES (:id, :tenant_id, :email, :name, 'admin', true, :hashed_password, now())
                """),
                {
                    "id": user_id,
                    "tenant_id": tenant_id,
                    "email": admin_email,
                    "name": f"Admin ({name})",
                    "hashed_password": hash_password(admin_password),
                },
            )
        print(f"  Admin user created: {admin_email}")

    # Clean up
    engine = get_engine()
    await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser(description="Provision a new tenant")
    parser.add_argument("--slug", required=True, help="Tenant slug (e.g., skyvera)")
    parser.add_argument("--name", required=True, help="Tenant display name (e.g., 'Skyvera')")
    parser.add_argument("--admin-email", default=None, help="Initial admin user email")
    parser.add_argument("--admin-password", default=None, help="Initial admin user password")
    args = parser.parse_args()

    if (args.admin_email and not args.admin_password) or (args.admin_password and not args.admin_email):
        parser.error("--admin-email and --admin-password must be provided together")

    asyncio.run(provision(args.slug, args.name, args.admin_email, args.admin_password))


if __name__ == "__main__":
    main()
