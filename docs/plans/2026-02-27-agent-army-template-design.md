# Design: agent-army-template

**Date:** 2026-02-27
**Status:** Approved
**Repo:** `valkyrie-revival-bot/agent-army-template` (private)
**Upstream:** `diamondhholdings-hub/agent-army`

## Problem

The sales-army project is tightly coupled to ESW/Skyvera branding in a small number of files. To reuse the platform for other projects, a clean starting point is needed — stripped of ESW product knowledge and company-specific references, but keeping the full agent platform, sales methodology, pricing approach, and regional data intact.

## Goal

A private GitHub repo (`agent-army-template`) that:
- Tracks `diamondhholdings-hub/agent-army` as upstream and can be synced with one script
- Has all ESW/Skyvera/Jigtree references removed
- Replaces company-specific agent prompt strings with a `COMPANY_NAME` runtime config
- Provides placeholder product docs so a new project knows exactly what to drop in
- Lets a new project be bootstrapped in minutes: clone → set env vars → provision tenant → add product docs

## Architecture

```
diamondhholdings-hub/agent-army  (upstream — has ESW content)
        ↓  git fetch upstream + git merge + scripts/strip_esw.py
valkyrie-revival-bot/agent-army-template  (private)
        └── main  (ESW stripped — default branch)
```

Single `main` branch. No complex branch topology needed — the strip script is idempotent, so syncing is always: fetch → merge → strip → commit → push.

## Strip Layer

The following files are modified. Everything else (platform, agents, orchestration, methodology, regional, tests, pricing structure) is kept verbatim.

### Files removed / replaced with placeholders

| File | Action |
|---|---|
| `data/products/monetization-platform.md` | Replace with `example-product.md` placeholder |
| `data/products/billing.md` | Remove |
| `data/products/charging.md` | Remove |
| `data/products/positioning/battlecard-vs-competitor-a.md` | Remove |
| `data/products/positioning/use-case-digital-transformation.md` | Remove |

A `data/products/PRODUCTS_README.md` is added explaining the expected document format and frontmatter schema (product_category, buyer_persona, sales_stage, region).

### Files modified

| File | Change |
|---|---|
| `src/knowledge/products/esw_data.py` | Rename → `product_data.py`; `ESW_DEFAULT_TENANT_ID` → `DEFAULT_TENANT_ID`; `"esw-default"` → `"default"`; all ESW references removed |
| `src/app/agents/sales/prompts.py` | `"ESW (Enterprise Sales Workflow)"` → `"enterprise sales"` |
| `src/app/agents/solution_architect/prompts.py` | `"at Skyvera"` and `"Skyvera"` → `settings.company_name` |
| `src/app/agents/project_manager/prompts.py` | `"at Skyvera"` → `settings.company_name` |
| `src/app/schemas/tenant.py` | Examples `skyvera`/`jigtree` → `acme`/`example-co` |
| `scripts/seed_sa_knowledge.py` | Default tenant arg `skyvera` → `default` |
| `scripts/provision_tenant.py` | Docstring examples genericized |

### Files kept as-is

- `data/products/pricing/esw-pricing.json` — pricing approach is reusable
- `data/methodology/` — BANT, MEDDIC, SPIN are universal
- `data/regional/` — APAC, EMEA, Americas regional data
- All platform code under `src/app/` (except the 3 prompt files above)
- All tests under `tests/`
- `docker-compose.yml`, `Dockerfile`, `pyproject.toml`, `alembic/`

## Runtime Config: COMPANY_NAME

Add `COMPANY_NAME` to `src/app/config.py`, reading from env var with default `"Your Company"`.

```python
company_name: str = Field(default="Your Company", description="Company name used in agent prompts")
```

Agent prompts that previously hardcoded "Skyvera" will call `get_settings().company_name` at prompt-build time. This means setting `COMPANY_NAME=Acme` in `.env` propagates to all agent personas with no code changes.

`.env.example` updated to include:
```
COMPANY_NAME=Your Company
```

## Sync Workflow

`scripts/sync_template.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

echo "Fetching upstream (diamondhholdings-hub/agent-army)..."
git fetch upstream

echo "Merging upstream/main..."
git merge upstream/main --no-edit

echo "Re-applying strip..."
python scripts/strip_esw.py

echo "Committing..."
UPSTREAM_SHA=$(git rev-parse --short upstream/main)
git add -A
git commit -m "sync: upstream@${UPSTREAM_SHA}" --allow-empty

echo "Pushing..."
git push origin main

echo "Done."
```

`scripts/strip_esw.py` performs all file modifications listed in the strip layer above. It is idempotent — safe to run on an already-stripped repo.

## Bootstrap: Starting a New Project

```bash
git clone git@github.com:valkyrie-revival-bot/agent-army-template.git my-project
cd my-project

# Remove template remote, set your own origin
git remote remove origin
git remote add origin git@github.com:your-org/my-project.git
git push -u origin main

# Configure
cp .env.example .env
# Edit .env: set COMPANY_NAME, API keys, DATABASE_URL, etc.

# Start infrastructure
docker compose up -d

# Provision first tenant
uv run python scripts/provision_tenant.py \
  --slug acme \
  --name "Acme Corp" \
  --admin-email admin@acme.com \
  --admin-password changeme

# Add your product docs to data/products/ (see PRODUCTS_README.md)
# Then seed knowledge base
uv run python scripts/seed_sa_knowledge.py --tenant acme
```

## Implementation Steps

1. Create `valkyrie-revival-bot/agent-army-template` as private GitHub repo via `gh` CLI
2. Clone it locally, add `diamondhholdings-hub/agent-army` as `upstream`
3. Pull upstream `main` as the initial state
4. Add `COMPANY_NAME` setting to `src/app/config.py` and `.env.example`
5. Update the 3 agent prompt files to use `settings.company_name`
6. Rename `esw_data.py` → `product_data.py`, update all imports and references
7. Replace ESW product docs with placeholders, add `PRODUCTS_README.md`
8. Genericize schema examples and script defaults
9. Write `scripts/strip_esw.py` (idempotent strip script)
10. Write `scripts/sync_template.sh`
11. Write template `README.md` with bootstrap instructions
12. Single clean commit: `feat: initial agent-army-template`
13. Push to `valkyrie-revival-bot/agent-army-template`
