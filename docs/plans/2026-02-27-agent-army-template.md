# agent-army-template Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create `valkyrie-revival-bot/agent-army-template` — a private GitHub repo that is a synced, ESW-stripped fork of `diamondhholdings-hub/agent-army`, ready to clone as a starting point for new projects.

**Architecture:** Copy the full sales-army codebase into a new private repo, strip ESW/Skyvera-specific product docs and company name references, wire `COMPANY_NAME` env var (already in config) into agent prompts, and add sync + strip scripts. The template tracks upstream via a remote so a single script keeps it current.

**Tech Stack:** Python, bash, GitHub CLI (`gh`), git

---

### Task 1: Create the private GitHub repo and seed from upstream

**Files:**
- Creates: `~/agent-army-template/` (new local directory)

**Step 1: Create the private repo on GitHub**

```bash
gh repo create valkyrie-revival-bot/agent-army-template \
  --private \
  --description "Generic AI sales agent platform — stripped template of agent-army"
```

Expected: `✓ Created repository valkyrie-revival-bot/agent-army-template on GitHub`

**Step 2: Clone sales-army as the source**

```bash
cd ~
git clone https://github.com/diamondhholdings-hub/agent-army.git agent-army-template
cd agent-army-template
```

**Step 3: Rewire remotes**

```bash
git remote rename origin upstream
git remote add origin https://github.com/valkyrie-revival-bot/agent-army-template.git
```

Verify:
```bash
git remote -v
```

Expected:
```
origin    https://github.com/valkyrie-revival-bot/agent-army-template.git (fetch)
origin    https://github.com/valkyrie-revival-bot/agent-army-template.git (push)
upstream  https://github.com/diamondhholdings-hub/agent-army.git (fetch)
upstream  https://github.com/diamondhholdings-hub/agent-army.git (push)
```

**Step 4: Push to new origin**

```bash
git push -u origin main
```

Expected: branch pushed, tracking set.

---

### Task 2: Wire COMPANY_NAME into Solution Architect prompts

> **Context:** `COMPANY_NAME` already exists in `src/app/config.py:96`. It just needs to be plumbed into agent identity prompts that currently hardcode "Skyvera".

**Files:**
- Modify: `src/app/agents/solution_architect/prompts.py`

**Step 1: Add settings import (after `from __future__ import annotations`)**

Find:
```python
from __future__ import annotations
```

Replace with:
```python
from __future__ import annotations

from src.app.config import get_settings
```

**Step 2: Replace hardcoded "Skyvera" in SA_SYSTEM_PROMPT (line ~30)**

Find:
```python
SA_SYSTEM_PROMPT: str = """\
You are a Solution Architect at Skyvera, a technical pre-sales expert \
```

Replace with:
```python
SA_SYSTEM_PROMPT: str = f"""\
You are a Solution Architect at {get_settings().company_name or 'your company'}, a technical pre-sales expert \
```

**Step 3: Replace hardcoded "Skyvera" in build_architecture_narrative_prompt (line ~138)**

Find:
```python
        "**Task:** Generate an architecture narrative describing how Skyvera "
```

Replace with:
```python
        f"**Task:** Generate an architecture narrative describing how {get_settings().company_name or 'our product'} "
```

**Step 4: Verify clean**

```bash
grep -n "Skyvera\|jigtree\|ESW\|esw" src/app/agents/solution_architect/prompts.py
```

Expected: no output.

**Step 5: Commit**

```bash
git add src/app/agents/solution_architect/prompts.py
git commit -m "feat: replace hardcoded Skyvera with COMPANY_NAME in SA prompts"
```

---

### Task 3: Wire COMPANY_NAME into Project Manager prompts

**Files:**
- Modify: `src/app/agents/project_manager/prompts.py`

**Step 1: Add settings import**

Find:
```python
from __future__ import annotations
```

Replace with:
```python
from __future__ import annotations

from src.app.config import get_settings
```

**Step 2: Replace hardcoded "Skyvera" in PM_SYSTEM_PROMPT (line ~32)**

Find:
```python
PM_SYSTEM_PROMPT: str = """\
You are a Project Manager at Skyvera, a PMBOK-certified delivery management expert \
```

Replace with:
```python
PM_SYSTEM_PROMPT: str = f"""\
You are a Project Manager at {get_settings().company_name or 'your company'}, a PMBOK-certified delivery management expert \
```

**Step 3: Verify clean**

```bash
grep -n "Skyvera\|jigtree\|ESW\|esw" src/app/agents/project_manager/prompts.py
```

Expected: no output.

**Step 4: Commit**

```bash
git add src/app/agents/project_manager/prompts.py
git commit -m "feat: replace hardcoded Skyvera with COMPANY_NAME in PM prompts"
```

---

### Task 4: Remove ESW branding from Sales Agent prompts

**Files:**
- Modify: `src/app/agents/sales/prompts.py`

**Step 1: Remove ESW acronym (line ~365)**

Find:
```python
        "are executing the ESW (Enterprise Sales Workflow) methodology, which "
```

Replace with:
```python
        "are executing an enterprise sales methodology which "
```

**Step 2: Verify clean**

```bash
grep -n "ESW\|esw\|Skyvera\|jigtree" src/app/agents/sales/prompts.py
```

Expected: no output.

**Step 3: Commit**

```bash
git add src/app/agents/sales/prompts.py
git commit -m "feat: remove ESW branding from sales agent prompts"
```

---

### Task 5: Rename esw_data.py to product_data.py

**Files:**
- Rename: `src/knowledge/products/esw_data.py` → `src/knowledge/products/product_data.py`
- Modify: `src/knowledge/products/__init__.py`

**Step 1: Copy with new name and remove old**

```bash
cp src/knowledge/products/esw_data.py src/knowledge/products/product_data.py
git rm src/knowledge/products/esw_data.py
```

**Step 2: In `product_data.py` — update module docstring**

Find:
```
"""ESW product ingestion helper and verification utilities.

Provides convenience functions for batch ingestion of ESW product
documentation and verification that ingested data is retrievable.

The PRODUCT_DATA_DIR points to the standard location for product
documentation files. ingest_all_esw_products() ingests all supported
documents in that directory through the IngestionPipeline.
"""
```

Replace with:
```
"""Product ingestion helper and verification utilities.

Provides convenience functions for batch ingestion of product
documentation and verification that ingested data is retrievable.

The PRODUCT_DATA_DIR points to the standard location for product
documentation files. ingest_all_products() ingests all supported
documents in that directory through the IngestionPipeline.
"""
```

**Step 3: Rename constant**

Find:
```python
# Default tenant ID for ESW product knowledge (shared across tenants)
ESW_DEFAULT_TENANT_ID: str = "esw-default"
```

Replace with:
```python
# Default tenant ID for shared product knowledge
DEFAULT_TENANT_ID: str = "default"
```

**Step 4: Rename function and update all references within the file**

- `ingest_all_esw_products` → `ingest_all_products`
- `ESW_DEFAULT_TENANT_ID` → `DEFAULT_TENANT_ID`
- `"ESW product ingestion complete"` → `"Product ingestion complete"`
- Docstring: `"ESW product documents"` → `"product documents"`
- Docstring: `"defaults to ESW_DEFAULT_TENANT_ID"` → `"defaults to DEFAULT_TENANT_ID"`

**Step 5: Replace ESW-specific sample queries in verify_product_retrieval**

Find:
```python
    sample_queries = [
        ("subscription management", {"product_category": "monetization"}),
        ("usage-based pricing", {"product_category": "charging"}),
        ("invoice generation", {"product_category": "billing"}),
    ]
```

Replace with:
```python
    sample_queries = [
        ("product features", {}),
        ("pricing and licensing", {}),
        ("integration and API", {}),
    ]
```

**Step 6: Update `__init__.py`**

Replace the entire file with:

```python
from src.knowledge.products.product_data import (
    DEFAULT_TENANT_ID,
    PRODUCT_DATA_DIR,
    ingest_all_products,
    verify_product_retrieval,
)

__all__ = [
    "DEFAULT_TENANT_ID",
    "PRODUCT_DATA_DIR",
    "ingest_all_products",
    "verify_product_retrieval",
]
```

**Step 7: Find any other callers and update**

```bash
grep -r "ESW_DEFAULT_TENANT_ID\|ingest_all_esw_products\|esw_data" \
  src/ tests/ scripts/ --include="*.py"
```

Update any hits: `ESW_DEFAULT_TENANT_ID` → `DEFAULT_TENANT_ID`, `ingest_all_esw_products` → `ingest_all_products`.

**Step 8: Commit**

```bash
git add src/knowledge/products/
git commit -m "feat: rename esw_data.py to product_data.py, remove ESW references"
```

---

### Task 6: Replace ESW product docs with generic placeholders

**Files:**
- Delete: `data/products/monetization-platform.md`
- Delete: `data/products/billing.md`
- Delete: `data/products/charging.md`
- Delete: `data/products/positioning/battlecard-vs-competitor-a.md`
- Delete: `data/products/positioning/use-case-digital-transformation.md`
- Create: `data/products/example-product.md`
- Create: `data/products/PRODUCTS_README.md`

**Step 1: Remove ESW product files**

```bash
git rm data/products/monetization-platform.md
git rm data/products/billing.md
git rm data/products/charging.md
git rm "data/products/positioning/battlecard-vs-competitor-a.md"
git rm "data/products/positioning/use-case-digital-transformation.md"
```

**Step 2: Create `data/products/example-product.md`**

```markdown
---
product_category: "your-product"
buyer_persona:
  - technical
  - business
  - executive
sales_stage:
  - discovery
  - demo
region:
  - global
---

# Example Product

Replace this file with your actual product documentation.

## Overview

Describe what your product does in 1-2 paragraphs. Focus on the customer outcome, not the technology.

## Key Capabilities

- **Capability 1:** Brief description with customer benefit.
- **Capability 2:** Brief description with customer benefit.
- **Capability 3:** Brief description with customer benefit.

## Who It's For

Describe the buyer personas: technical reviewers, business owners, executives.

## Common Use Cases

1. **Use Case 1:** Problem → Solution → Outcome
2. **Use Case 2:** Problem → Solution → Outcome

## Competitive Differentiation

What makes this product stand out vs. alternatives?

## Technical Overview

Architecture summary, integration points, deployment model.
```

**Step 3: Create `data/products/PRODUCTS_README.md`**

```markdown
# Product Knowledge Base

Add your product documentation here as Markdown files. Each file is ingested
into the vector database and made available to all agents for RAG retrieval.

## File Format

Each document should include YAML frontmatter:

    ---
    product_category: "your-category"
    buyer_persona:
      - technical
      - business
      - executive
    sales_stage:
      - discovery
      - demo
    region:
      - global
    ---

## What to Include

- **Product overviews** — what it does, who it's for, outcomes
- **Technical specs** — architecture, APIs, integrations, security
- **Positioning docs** — differentiation vs. competitors, use cases
- **Pricing** — see `pricing/` directory

## Naming Conventions

- `{product-name}.md` — main product doc
- `positioning/battlecard-{competitor}.md` — competitive battlecards
- `positioning/use-case-{industry}.md` — vertical use cases

## Ingesting Documents

After adding files:

    uv run python scripts/seed_sa_knowledge.py --tenant-id your-tenant

The `example-product.md` file is a placeholder — replace or delete it.
```

**Step 4: Commit**

```bash
git add data/products/
git commit -m "feat: replace ESW product docs with generic placeholders"
```

---

### Task 7: Genericize schemas and script defaults

**Files:**
- Modify: `src/app/schemas/tenant.py`
- Modify: `scripts/seed_sa_knowledge.py`
- Modify: `scripts/provision_tenant.py`

**Step 1: Update tenant schema examples in `src/app/schemas/tenant.py`**

Find:
```python
        examples=["skyvera", "jigtree"],
```
Replace with:
```python
        examples=["acme", "example-co"],
```

Find:
```python
        examples=["Skyvera", "Jigtree"],
```
Replace with:
```python
        examples=["Acme Corp", "Example Co"],
```

**Step 2: Update seed script default in `scripts/seed_sa_knowledge.py` (line ~255)**

Find:
```python
        default="skyvera",
        help="Tenant ID for the ingested knowledge (default: skyvera)",
```
Replace with:
```python
        default="default",
        help="Tenant ID for the ingested knowledge (default: default)",
```

**Step 3: Update provision_tenant.py docstring examples**

Find:
```python
    uv run python scripts/provision_tenant.py --slug skyvera --name "Skyvera"
    uv run python scripts/provision_tenant.py --slug skyvera --name "Skyvera" --admin-email admin@skyvera.com --admin-password changeme
```
Replace with:
```python
    uv run python scripts/provision_tenant.py --slug acme --name "Acme Corp"
    uv run python scripts/provision_tenant.py --slug acme --name "Acme Corp" --admin-email admin@acme.com --admin-password changeme
```

Find:
```python
    parser.add_argument("--slug", required=True, help="Tenant slug (e.g., skyvera)")
    parser.add_argument("--name", required=True, help="Tenant display name (e.g., 'Skyvera')")
```
Replace with:
```python
    parser.add_argument("--slug", required=True, help="Tenant slug (e.g., acme)")
    parser.add_argument("--name", required=True, help="Tenant display name (e.g., 'Acme Corp')")
```

**Step 4: Commit**

```bash
git add src/app/schemas/tenant.py scripts/seed_sa_knowledge.py scripts/provision_tenant.py
git commit -m "feat: genericize schema examples and script defaults"
```

---

### Task 8: Update .env.example with clearer COMPANY_NAME entry

**Files:**
- Modify: `.env.example`

**Step 1: Find current COMPANY_NAME line**

```bash
grep -n "COMPANY_NAME" .env.example
```

**Step 2: Ensure it reads clearly**

Find whatever the current `COMPANY_NAME` line looks like and replace with:

```
# Company name used in all agent personas (e.g. "Acme Corp")
COMPANY_NAME=Your Company
```

**Step 3: Commit**

```bash
git add .env.example
git commit -m "docs: clarify COMPANY_NAME usage in .env.example"
```

---

### Task 9: Write scripts/strip_esw.py

This is an idempotent Python script that applies all strip changes. Re-running on an already-stripped repo must be a no-op.

**Files:**
- Create: `scripts/strip_esw.py`

**Step 1: Create the script**

The script must:
1. Define `ROOT = Path(__file__).resolve().parent.parent`
2. Have a `_replace_in_file(path, old, new)` helper that reads, replaces, writes only if changed, and prints `[patched] {relative_path}` when it does
3. Call these strip functions in sequence:
   - `strip_agent_prompts()` — applies Tasks 2-4 replacements to SA/PM/Sales prompt files
   - `strip_schemas()` — applies Task 7 replacements to `src/app/schemas/tenant.py`
   - `strip_product_data_module()` — applies Task 5: copies `esw_data.py` → `product_data.py` if needed, renames symbols, deletes original; updates `__init__.py`
   - `strip_esw_product_docs()` — applies Task 6: deletes the 5 ESW doc files if they exist
   - `strip_script_defaults()` — applies Task 7: updates seed/provision script defaults
4. Print "Strip complete." at end

All replacements must be **exact string replacements** (not regex) so they're safely re-runnable.

**Step 2: Make executable**

```bash
chmod +x scripts/strip_esw.py
```

**Step 3: Run once to verify it works**

```bash
python scripts/strip_esw.py
```

Expected: "[patched]" lines for any remaining hits, then "Strip complete."

**Step 4: Run again to verify idempotency**

```bash
python scripts/strip_esw.py
```

Expected: no `[patched]` lines — already clean.

**Step 5: Commit**

```bash
git add scripts/strip_esw.py
git commit -m "feat: add idempotent strip_esw.py script"
```

---

### Task 10: Write scripts/sync_template.sh

**Files:**
- Create: `scripts/sync_template.sh`

**Step 1: Create the script with this content**

```bash
#!/usr/bin/env bash
# sync_template.sh -- Sync agent-army-template from upstream
#
# Usage:
#   bash scripts/sync_template.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$SCRIPT_DIR")"
cd "$ROOT"

echo "=== agent-army-template sync ==="

if ! git remote get-url upstream &>/dev/null; then
  echo "Error: 'upstream' remote not configured."
  echo "Run: git remote add upstream https://github.com/diamondhholdings-hub/agent-army.git"
  exit 1
fi

echo "1. Fetching upstream..."
git fetch upstream

echo "2. Merging upstream/main..."
git merge upstream/main --no-edit

echo "3. Re-applying strip..."
python3 scripts/strip_esw.py

UPSTREAM_SHA=$(git rev-parse --short upstream/main)

echo "4. Committing..."
if git diff --cached --quiet && git diff --quiet; then
  echo "   Nothing to commit -- already up to date."
else
  git add -A
  git commit -m "sync: upstream@${UPSTREAM_SHA}"
fi

echo "5. Pushing to origin..."
git push origin main

echo ""
echo "=== Sync complete (upstream@${UPSTREAM_SHA}) ==="
```

**Step 2: Make executable**

```bash
chmod +x scripts/sync_template.sh
```

**Step 3: Commit**

```bash
git add scripts/sync_template.sh
git commit -m "feat: add sync_template.sh for upstream syncing"
```

---

### Task 11: Write README.md

**Files:**
- Create/replace: `README.md`

**Step 1: Check if one exists**

```bash
head -3 README.md 2>/dev/null || echo "(no README)"
```

**Step 2: Write README.md with these sections:**

- Title + one-line description
- "What's Included" — 8 agents, multi-tenant, methodology, meeting/voice, test count
- "Quick Start" — 5-step bootstrap (clone, configure, docker up, provision tenant, seed + run)
- "Syncing from Upstream" — one command `bash scripts/sync_template.sh`
- "Configuration Reference" — table of key env vars (COMPANY_NAME, MEETING_BOT_NAME, RECALL_AI_API_KEY, HEYGEN_API_KEY, NOTION_TOKEN)
- "Project Structure" — annotated tree of src/app/, data/, scripts/
- "Running Tests" — `uv run pytest tests/ -v`

**Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add template README with bootstrap instructions"
```

---

### Task 12: Final verification and push

**Step 1: Full scan for remaining ESW/Skyvera references**

```bash
grep -r "Skyvera\|jigtree\|Jigtree\|esw-default" \
  src/app/agents/ src/app/schemas/ src/knowledge/products/ scripts/ \
  --include="*.py" \
  | grep -v "__pycache__"
```

Expected: no output.

**Step 2: Run strip script one final time**

```bash
python scripts/strip_esw.py
```

Expected: "Strip complete." with no `[patched]` lines.

**Step 3: Run tests**

```bash
uv run pytest tests/ -x -q 2>&1 | tail -20
```

Expected: same pass rate as before — no new failures from the strip.

**Step 4: Push**

```bash
git push origin main
```

**Step 5: Verify on GitHub**

```bash
gh repo view valkyrie-revival-bot/agent-army-template --web
```

Confirm: private repo, correct description, README visible.
