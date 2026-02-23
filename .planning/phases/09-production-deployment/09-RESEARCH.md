# Phase 9: Production Deployment - Research

**Researched:** 2026-02-22
**Domain:** GCP Cloud Run CI/CD, Vercel deployment, Google Workspace delegation, production credential management, smoke testing
**Confidence:** HIGH

## Summary

This phase deploys the Sales Agent platform to production across two hosting targets: Vercel for the meeting-bot-webapp (avatar frontend) and GCP Cloud Run for the Python/FastAPI backend. The codebase already has a functioning `Dockerfile` (multi-stage, python:3.12-slim, uv-based), a `deploy.yml` GitHub Actions workflow, and a `vercel.json` configuration. The primary work is (1) updating the CI/CD pipeline to inject secrets from GitHub Actions instead of GCP Secret Manager, (2) adding missing environment variables (Notion CRM, Qdrant Cloud, service account JSON), (3) enhancing the health endpoint to check Qdrant and LiteLLM, (4) provisioning Google Workspace credentials, and (5) writing a verification script and demo guide.

A critical gap discovered: the current `deploy.yml` references GCP Secret Manager secrets (`database-url-staging:latest`, etc.) which contradicts the user decision to use GitHub Actions secrets as plain env vars. The deploy workflow also only targets staging (`agent-army-api-staging`) and needs a production deployment job. Additionally, the `Settings` class in `config.py` is missing Notion CRM env vars (`NOTION_TOKEN`, `NOTION_DATABASE_ID`) and needs a mechanism to handle the Google service account JSON as a base64-encoded env var instead of a file path.

**Primary recommendation:** Update the existing `deploy.yml` to add a production deployment job that injects all secrets as `env_vars` from GitHub Actions secrets, add missing env vars to `config.py`, enhance the health endpoint for Qdrant/LiteLLM checks, and create a standalone `scripts/verify_production.py` smoke test script.

## Standard Stack

The established tools/services for this deployment:

### Core
| Tool | Version | Purpose | Why Standard |
|------|---------|---------|--------------|
| `google-github-actions/auth` | v3 | Authenticate GitHub Actions to GCP via Workload Identity Federation | Official Google action, keyless auth, no service account key files in CI |
| `google-github-actions/deploy-cloudrun` | v3 | Deploy container to Cloud Run | Official Google action, supports env_vars and flags |
| `google-github-actions/setup-gcloud` | v2 | Install gcloud CLI for `gcloud builds submit` | Official Google action |
| Vercel Git Integration | N/A | Auto-deploy meeting-bot-webapp on push to `main` | Zero-config, already partially set up via `.vercel/` directory |
| `gcloud builds submit` | N/A | Build Docker image in Cloud Build (avoids local Docker) | Already in deploy.yml, works since Docker not installed locally |
| Qdrant Cloud | Managed | Production vector database | Free 1GB tier available, remote URL replaces local `./qdrant_data` path |

### Supporting
| Tool | Version | Purpose | When to Use |
|------|---------|---------|-------------|
| `httpx` | >=0.27.0 | HTTP client for smoke test script | Already in dependencies, use for health/webapp checks |
| `notion-client` | >=2.7.0 | Notion API client for CRM verification | Already installed, used by NotionAdapter |
| `google-api-python-client` | >=2.0.0 | Gmail/Calendar API for Workspace verification | Already installed, used by GSuiteAuthManager |

### Alternatives Considered
| Instead of | Could Use | Tradeoff |
|------------|-----------|----------|
| GitHub Actions secrets as env_vars | GCP Secret Manager | Secret Manager is more secure for rotation/audit, but user decision is GitHub Actions secrets for simplicity |
| Qdrant Cloud managed | Self-hosted Qdrant on Cloud Run | Self-hosted adds operational burden; managed free tier sufficient for demo |
| Base64-encoded service account JSON | GCP Secret Manager volume mount | Volume mount requires Secret Manager; base64 env var is self-contained |

**No new installations required** -- all libraries are already in `pyproject.toml`. The only new external service is Qdrant Cloud (free tier).

## Architecture Patterns

### Current Deployment Architecture (what exists)
```
.github/workflows/
  deploy.yml          # Cloud Run deploy (NEEDS UPDATE: staging only, uses Secret Manager)
  test.yml            # CI: lint + test on push/PR

Dockerfile            # Multi-stage build, python:3.12-slim, uv sync, uvicorn
docker-compose.yml    # Local dev: postgres + redis only

meeting-bot-webapp/
  vercel.json         # Vercel config (already exists)
  .vercel/            # Local Vercel project link (already initialized)
```

### Target Deployment Architecture (what to build)
```
.github/workflows/
  deploy.yml          # UPDATED: production job, GitHub secrets as env_vars
  test.yml            # Unchanged

scripts/
  verify_production.py    # NEW: automated smoke test (SC1 + SC2)
  provision_tenant.py     # Existing (may need prod tenant setup)

docs/
  demo-guide.md           # NEW: step-by-step demo runbook for non-technical users
  credential-setup.md     # NEW: Google Workspace + Notion provisioning guide
```

### Pattern 1: GitHub Actions Secrets as Cloud Run Env Vars
**What:** Pass all production secrets via `env_vars` input of `deploy-cloudrun@v3`, sourced from GitHub repository secrets.
**When to use:** Every production deployment.
**Why:** User decision -- no GCP Secret Manager. Simple, single source of truth in GitHub.

**Example:**
```yaml
# Source: https://github.com/google-github-actions/deploy-cloudrun
- name: Deploy to Cloud Run (production)
  uses: google-github-actions/deploy-cloudrun@v3
  with:
    service: agent-army-api
    image: gcr.io/${{ env.PROJECT_ID }}/${{ env.SERVICE }}
    region: ${{ secrets.GCP_REGION }}
    env_vars: |
      ENVIRONMENT=production
      DATABASE_URL=${{ secrets.DATABASE_URL }}
      REDIS_URL=${{ secrets.REDIS_URL }}
      ANTHROPIC_API_KEY=${{ secrets.ANTHROPIC_API_KEY }}
      OPENAI_API_KEY=${{ secrets.OPENAI_API_KEY }}
      JWT_SECRET_KEY=${{ secrets.JWT_SECRET_KEY }}
      GOOGLE_SERVICE_ACCOUNT_JSON_B64=${{ secrets.GOOGLE_SERVICE_ACCOUNT_JSON_B64 }}
      GOOGLE_DELEGATED_USER_EMAIL=${{ secrets.GOOGLE_DELEGATED_USER_EMAIL }}
      NOTION_TOKEN=${{ secrets.NOTION_TOKEN }}
      NOTION_DATABASE_ID=${{ secrets.NOTION_DATABASE_ID }}
      KNOWLEDGE_QDRANT_URL=${{ secrets.KNOWLEDGE_QDRANT_URL }}
      KNOWLEDGE_QDRANT_API_KEY=${{ secrets.KNOWLEDGE_QDRANT_API_KEY }}
      KNOWLEDGE_OPENAI_API_KEY=${{ secrets.OPENAI_API_KEY }}
      RECALL_AI_API_KEY=${{ secrets.RECALL_AI_API_KEY }}
      DEEPGRAM_API_KEY=${{ secrets.DEEPGRAM_API_KEY }}
      ELEVENLABS_API_KEY=${{ secrets.ELEVENLABS_API_KEY }}
      ELEVENLABS_VOICE_ID=${{ secrets.ELEVENLABS_VOICE_ID }}
      HEYGEN_API_KEY=${{ secrets.HEYGEN_API_KEY }}
      HEYGEN_AVATAR_ID=${{ secrets.HEYGEN_AVATAR_ID }}
      MEETING_BOT_WEBAPP_URL=${{ secrets.MEETING_BOT_WEBAPP_URL }}
      LANGFUSE_PUBLIC_KEY=${{ secrets.LANGFUSE_PUBLIC_KEY }}
      LANGFUSE_SECRET_KEY=${{ secrets.LANGFUSE_SECRET_KEY }}
      SENTRY_DSN=${{ secrets.SENTRY_DSN }}
    flags: |
      --min-instances=0
      --max-instances=10
      --memory=1Gi
      --cpu=1
      --timeout=300
      --concurrency=80
      --allow-unauthenticated
```

### Pattern 2: Base64-Encoded Service Account JSON
**What:** Encode the Google service account JSON file as base64, store as GitHub secret, decode at app startup.
**When to use:** When the app needs a service account JSON but can only receive env vars (no file mount).
**Why:** Cloud Run env vars cannot contain multi-line JSON; base64 solves this cleanly.

**Example:**
```python
# Encoding (one-time, local terminal):
# cat service-account.json | base64 -w 0
# Store the output as GOOGLE_SERVICE_ACCOUNT_JSON_B64 in GitHub secrets

# Decoding in config.py:
import base64
import json
import tempfile
import os

class Settings(BaseSettings):
    GOOGLE_SERVICE_ACCOUNT_FILE: str = ""
    GOOGLE_SERVICE_ACCOUNT_JSON_B64: str = ""  # NEW: base64-encoded JSON

    def get_service_account_path(self) -> str | None:
        """Return path to service account file, decoding from base64 if needed."""
        if self.GOOGLE_SERVICE_ACCOUNT_FILE:
            return self.GOOGLE_SERVICE_ACCOUNT_FILE
        if self.GOOGLE_SERVICE_ACCOUNT_JSON_B64:
            decoded = base64.b64decode(self.GOOGLE_SERVICE_ACCOUNT_JSON_B64)
            tmp_path = "/tmp/service-account.json"
            with open(tmp_path, "wb") as f:
                f.write(decoded)
            return tmp_path
        return None
```

### Pattern 3: Enhanced Health Endpoint with All Dependencies
**What:** Extend existing `/health/ready` to check Qdrant and LiteLLM in addition to DB and Redis.
**When to use:** SC2 requires all 4 dependency checks.
**Why:** Current health endpoint only checks DB and Redis. Production needs all dependencies verified.

**Example:**
```python
# Extend _check_dependencies() in src/app/api/v1/health.py
async def _check_dependencies() -> dict:
    checks: dict = {"database": "ok", "redis": "ok", "qdrant": "ok", "litellm": "ok"}

    # ... existing DB and Redis checks ...

    # Check Qdrant
    try:
        from src.knowledge.config import KnowledgeBaseConfig
        from qdrant_client import QdrantClient
        config = KnowledgeBaseConfig()
        if config.qdrant_url:
            client = QdrantClient(url=config.qdrant_url, api_key=config.qdrant_api_key)
            client.get_collections()  # Simple connectivity check
            client.close()
        else:
            checks["qdrant"] = "local"  # Local mode, not a real remote check
    except Exception as e:
        checks["qdrant"] = "error"
        checks["qdrant_error"] = str(e)

    # Check LiteLLM (verify at least one provider key is configured)
    try:
        import litellm
        settings = get_settings()
        if settings.ANTHROPIC_API_KEY or settings.OPENAI_API_KEY:
            checks["litellm"] = "ok"
        else:
            checks["litellm"] = "no_keys"
    except Exception as e:
        checks["litellm"] = "error"
        checks["litellm_error"] = str(e)

    return checks
```

### Pattern 4: Standalone Verification Script
**What:** A `scripts/verify_production.py` that checks SC1 (webapp) and SC2 (health endpoint) programmatically.
**When to use:** Run manually after deploy, optionally as GitHub Actions post-deploy step.
**Why:** User decision -- automated verification for SC1 and SC2, lean toward standalone script.

**Example:**
```python
#!/usr/bin/env python3
"""Production verification script -- checks SC1 (webapp) and SC2 (health endpoint)."""
import sys
import httpx

WEBAPP_URL = "https://agent-army-meeting-bot.vercel.app"  # Vercel production URL
API_URL = "https://agent-army-api-HASH.run.app"  # Cloud Run production URL

def check_webapp(url: str) -> bool:
    """SC1: Verify webapp returns 200 and contains avatar-related content."""
    resp = httpx.get(url, follow_redirects=True, timeout=10)
    return resp.status_code == 200 and "avatar" in resp.text.lower()

def check_health(url: str) -> bool:
    """SC2: Verify health endpoint reports all dependencies healthy."""
    resp = httpx.get(f"{url}/health/ready", timeout=10)
    data = resp.json()
    return resp.status_code == 200 and data.get("status") == "ready"

if __name__ == "__main__":
    results = {}
    results["SC1_webapp"] = check_webapp(WEBAPP_URL)
    results["SC2_health"] = check_health(API_URL)
    for name, passed in results.items():
        status = "PASS" if passed else "FAIL"
        print(f"  [{status}] {name}")
    sys.exit(0 if all(results.values()) else 1)
```

### Anti-Patterns to Avoid
- **Hardcoding production URLs in code:** Use environment variables for all URLs; the verification script should accept URLs as CLI args or env vars.
- **Testing in staging and assuming production works:** The deploy.yml currently only deploys to staging. Production needs its own explicit job.
- **Storing service account JSON as a file in the repo:** Never commit credentials. Use base64-encoded env var.
- **Running the full test suite as a smoke test:** Smoke tests should be fast (<30s), not the full pytest suite.

## Don't Hand-Roll

Problems that look simple but have existing solutions:

| Problem | Don't Build | Use Instead | Why |
|---------|-------------|-------------|-----|
| GCP authentication in CI | Custom service account key management | `google-github-actions/auth@v3` with Workload Identity Federation | Keyless, short-lived tokens, no key rotation burden |
| Docker image building | Local docker build + push | `gcloud builds submit` in CI | Docker not installed locally; Cloud Build handles it |
| Vercel deployment pipeline | Custom CI/CD for frontend | Vercel Git Integration (auto-deploy on push) | Zero-config, already initialized |
| Cloud Run health probes | Custom health check scheduler | Cloud Run's built-in startup/liveness/readiness probes | Automatic restart on failure, no custom orchestration |
| Secret injection | Custom secret fetching code | `deploy-cloudrun@v3` `env_vars` input | Declarative, no runtime secret fetching logic |
| HTTP smoke tests | Custom socket/urllib code | `httpx` (already a dependency) | Async support, timeout handling, redirect following |

**Key insight:** The project already has all the infrastructure pieces in place (Dockerfile, deploy.yml, vercel.json, health endpoint). This phase is about wiring them up for production, not building from scratch. Resist the urge to rebuild what exists.

## Common Pitfalls

### Pitfall 1: Service Account JSON as File Path in Production
**What goes wrong:** `GOOGLE_SERVICE_ACCOUNT_FILE` expects a filesystem path. In Cloud Run, you cannot mount arbitrary files without GCP Secret Manager volume mounts.
**Why it happens:** Dev mode uses a local file; the same pattern doesn't work in containerized production with env-var-only secrets.
**How to avoid:** Add `GOOGLE_SERVICE_ACCOUNT_JSON_B64` env var support. Decode base64 to a temp file at startup. The `get_service_account_path()` method checks both: file path (dev) and base64 (prod).
**Warning signs:** App starts but GSuite services are `None` because `GOOGLE_SERVICE_ACCOUNT_FILE` is empty.

### Pitfall 2: Deploy Workflow Still References Secret Manager
**What goes wrong:** The current `deploy.yml` uses `secrets:` block with `database-url-staging:latest` format, which references GCP Secret Manager secrets that may not exist.
**Why it happens:** The workflow was scaffolded for a Secret Manager approach during Phase 1.
**How to avoid:** Replace the `secrets:` block with `env_vars:` block that references `${{ secrets.GITHUB_SECRET_NAME }}`. Remove the GCP Secret Manager dependency entirely.
**Warning signs:** Deploy fails with "secret not found" or "permission denied" errors on Cloud Run.

### Pitfall 3: Missing Notion Env Vars in Settings
**What goes wrong:** `NotionAdapter` requires `token` and `database_id` but `config.py` has no corresponding env vars. The adapter is never instantiated in `main.py` -- CRM sync engine is initialized with `external=None`.
**Why it happens:** Phase 5 built the adapter code but deferred production wiring to Phase 9.
**How to avoid:** Add `NOTION_TOKEN` and `NOTION_DATABASE_ID` to `Settings`. Wire `NotionAdapter` initialization in `main.py` when these are set. Add to GitHub Actions secrets.
**Warning signs:** CRM sync engine reports `external=None`, SC4 fails.

### Pitfall 4: Health Endpoint Missing Qdrant and LiteLLM Checks
**What goes wrong:** SC2 requires "all dependency checks passing (DB, Redis, Qdrant, LiteLLM)" but current `/health/ready` only checks DB and Redis.
**Why it happens:** Health endpoint was built in Phase 1 before Qdrant (Phase 3) and LiteLLM (Phase 2) were added.
**How to avoid:** Add Qdrant connectivity check (call `get_collections()`) and LiteLLM key validation to `_check_dependencies()`.
**Warning signs:** Health endpoint reports "ready" but Qdrant or LLM calls fail at runtime.

### Pitfall 5: Vercel Webapp URL Not Configured in Backend
**What goes wrong:** The `MEETING_BOT_WEBAPP_URL` env var must point to the Vercel production URL. If missing, the Recall.ai bot cannot display the avatar.
**Why it happens:** The meeting-bot-webapp deploys to Vercel independently. Its URL must be manually copied to the Cloud Run env vars.
**How to avoid:** After Vercel deployment, get the production URL and set it as `MEETING_BOT_WEBAPP_URL` in GitHub Actions secrets before deploying Cloud Run.
**Warning signs:** Bot joins meeting but shows no avatar; `output_media_url` is empty in Recall.ai bot configuration.

### Pitfall 6: Workload Identity Federation Not Set Up
**What goes wrong:** The deploy.yml uses Workload Identity Federation (`workload_identity_provider`), which requires a pre-configured WIF pool in GCP.
**Why it happens:** WIF setup is a one-time GCP console operation that is easy to forget.
**How to avoid:** Document the exact GCP commands to create the WIF pool, provider, and service account IAM binding. Include the `GCP_PROJECT_NUMBER` (not just ID) in the checklist.
**Warning signs:** Auth step fails with "unable to generate access token" or "workload identity pool not found".

### Pitfall 7: Cloud Run Readiness Probe November 2025 Quirk
**What goes wrong:** If a readiness probe was configured before November 2025 via API v1, it silently stops working.
**Why it happens:** Google changed readiness probe behavior; existing probes need to be removed and re-added.
**How to avoid:** Since this is a new production deployment (not upgrading an existing one), this should not apply. But if reusing a staging service, be aware.
**Warning signs:** Service deploys but readiness probe has no effect.

### Pitfall 8: `--allow-unauthenticated` Flag Missing
**What goes wrong:** Cloud Run defaults to requiring IAM authentication. Without `--allow-unauthenticated`, all HTTP requests return 403.
**Why it happens:** Security-by-default in Cloud Run.
**How to avoid:** Include `--allow-unauthenticated` in the deploy flags. The user decision explicitly states "publicly accessible URL, no IAM auth required -- app-level auth handles security."
**Warning signs:** All requests to Cloud Run URL return 403 Forbidden, even `/health`.

## Code Examples

### Complete GitHub Actions Production Deploy Job
```yaml
# Source: https://github.com/google-github-actions/deploy-cloudrun (v3 docs)
deploy-production:
  runs-on: ubuntu-latest
  permissions:
    contents: read
    id-token: write
  steps:
    - uses: actions/checkout@v4

    - id: auth
      uses: google-github-actions/auth@v3
      with:
        workload_identity_provider: projects/${{ secrets.GCP_PROJECT_NUMBER }}/locations/global/workloadIdentityPools/github/providers/github
        service_account: github-actions@${{ secrets.GCP_PROJECT_ID }}.iam.gserviceaccount.com

    - uses: google-github-actions/setup-gcloud@v2

    - name: Build and push Docker image
      run: gcloud builds submit --tag gcr.io/${{ secrets.GCP_PROJECT_ID }}/agent-army-api --timeout=600

    - name: Deploy to Cloud Run (production)
      uses: google-github-actions/deploy-cloudrun@v3
      with:
        service: agent-army-api
        image: gcr.io/${{ secrets.GCP_PROJECT_ID }}/agent-army-api
        region: ${{ secrets.GCP_REGION }}
        env_vars: |
          ENVIRONMENT=production
          DATABASE_URL=${{ secrets.PROD_DATABASE_URL }}
          REDIS_URL=${{ secrets.PROD_REDIS_URL }}
          JWT_SECRET_KEY=${{ secrets.PROD_JWT_SECRET_KEY }}
          ANTHROPIC_API_KEY=${{ secrets.ANTHROPIC_API_KEY }}
          OPENAI_API_KEY=${{ secrets.OPENAI_API_KEY }}
          GOOGLE_SERVICE_ACCOUNT_JSON_B64=${{ secrets.GOOGLE_SERVICE_ACCOUNT_JSON_B64 }}
          GOOGLE_DELEGATED_USER_EMAIL=${{ secrets.GOOGLE_DELEGATED_USER_EMAIL }}
          NOTION_TOKEN=${{ secrets.NOTION_TOKEN }}
          NOTION_DATABASE_ID=${{ secrets.NOTION_DATABASE_ID }}
          KNOWLEDGE_QDRANT_URL=${{ secrets.KNOWLEDGE_QDRANT_URL }}
          KNOWLEDGE_QDRANT_API_KEY=${{ secrets.KNOWLEDGE_QDRANT_API_KEY }}
          KNOWLEDGE_OPENAI_API_KEY=${{ secrets.OPENAI_API_KEY }}
          RECALL_AI_API_KEY=${{ secrets.RECALL_AI_API_KEY }}
          DEEPGRAM_API_KEY=${{ secrets.DEEPGRAM_API_KEY }}
          ELEVENLABS_API_KEY=${{ secrets.ELEVENLABS_API_KEY }}
          ELEVENLABS_VOICE_ID=${{ secrets.ELEVENLABS_VOICE_ID }}
          HEYGEN_API_KEY=${{ secrets.HEYGEN_API_KEY }}
          HEYGEN_AVATAR_ID=${{ secrets.HEYGEN_AVATAR_ID }}
          MEETING_BOT_WEBAPP_URL=${{ secrets.MEETING_BOT_WEBAPP_URL }}
          LANGFUSE_PUBLIC_KEY=${{ secrets.LANGFUSE_PUBLIC_KEY }}
          LANGFUSE_SECRET_KEY=${{ secrets.LANGFUSE_SECRET_KEY }}
          SENTRY_DSN=${{ secrets.SENTRY_DSN }}
          CORS_ALLOWED_ORIGINS=${{ secrets.CORS_ALLOWED_ORIGINS }}
          COMPANY_NAME=Skyvera
          MEETING_BOT_NAME=Sales Agent
        env_vars_update_strategy: overwrite
        flags: |
          --min-instances=0
          --max-instances=10
          --memory=1Gi
          --cpu=1
          --timeout=300
          --concurrency=80
          --allow-unauthenticated
```

### Google Workspace Domain-Wide Delegation Scopes
```
# All scopes needed for the Sales Agent service account:

# Gmail (send, read, modify)
https://www.googleapis.com/auth/gmail.send
https://www.googleapis.com/auth/gmail.readonly
https://www.googleapis.com/auth/gmail.modify

# Calendar (read events for meeting detection)
https://www.googleapis.com/auth/calendar.readonly
https://www.googleapis.com/auth/calendar.events.readonly

# Chat (bot -- does NOT require delegation, uses service account directly)
https://www.googleapis.com/auth/chat.bot
```

### Base64 Service Account Encoding (One-Time Setup)
```bash
# On developer machine:
cat /path/to/service-account.json | base64 -w 0 > /tmp/sa_b64.txt
# Copy the content of /tmp/sa_b64.txt into GitHub secret GOOGLE_SERVICE_ACCOUNT_JSON_B64
```

### Cloud Run Health Check YAML Configuration
```yaml
# Source: https://docs.cloud.google.com/run/docs/configuring/healthchecks
# Can be passed via --yaml flag or configured in Cloud Run console
apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: agent-army-api
spec:
  template:
    spec:
      containers:
        - image: gcr.io/PROJECT/agent-army-api
          startupProbe:
            httpGet:
              path: /health/startup
              port: 8080
            initialDelaySeconds: 5
            periodSeconds: 10
            failureThreshold: 12
            timeoutSeconds: 5
          livenessProbe:
            httpGet:
              path: /health
              port: 8080
            periodSeconds: 30
            failureThreshold: 3
            timeoutSeconds: 5
```

## State of the Art

| Old Approach | Current Approach | When Changed | Impact |
|--------------|------------------|--------------|--------|
| `google-github-actions/auth@v2` | `@v3` (Node 24, cleaner API) | September 2025 | Must update deploy.yml |
| `google-github-actions/deploy-cloudrun@v2` | `@v3` (new `env_vars_update_strategy`) | September 2025 | Must update deploy.yml |
| GCR (`gcr.io`) for images | Artifact Registry (`REGION-docker.pkg.dev`) recommended | 2024 | GCR still works but Google recommends migration; keep GCR for now since deploy.yml already uses it |
| Cloud Run readiness probes (pre-Nov 2025) | Updated readiness probe API | November 2025 | New deployments unaffected; only existing services need re-deployment |
| `gcloud builds submit` | Could use GitHub Actions Docker build + push | N/A | Keep `gcloud builds submit` -- it works, Docker not installed locally |

**Deprecated/outdated:**
- `google-github-actions/auth@v1`: Removed, use v3
- `google-github-actions/deploy-cloudrun@v1`: Removed, use v3
- GCP Secret Manager secrets in deploy.yml: User decision overrides -- use GitHub Actions secrets as env_vars

## Inventory of Required GitHub Actions Secrets

This is the complete list of secrets that must be configured in the GitHub repository settings before the first production deploy:

| Secret Name | Source | Purpose |
|-------------|--------|---------|
| `GCP_PROJECT_ID` | GCP Console | GCP project identifier |
| `GCP_PROJECT_NUMBER` | GCP Console | Required for WIF provider path |
| `GCP_REGION` | Developer choice | Cloud Run region (e.g., `us-central1`) |
| `PROD_DATABASE_URL` | Cloud SQL or managed Postgres | Production PostgreSQL connection string |
| `PROD_REDIS_URL` | Managed Redis (Upstash, Memorystore, etc.) | Production Redis connection string |
| `PROD_JWT_SECRET_KEY` | `openssl rand -hex 32` | JWT signing key for production |
| `ANTHROPIC_API_KEY` | Anthropic Console | Claude API access |
| `OPENAI_API_KEY` | OpenAI Dashboard | GPT + embeddings API access |
| `GOOGLE_SERVICE_ACCOUNT_JSON_B64` | `cat sa.json \| base64 -w 0` | Base64-encoded service account credentials |
| `GOOGLE_DELEGATED_USER_EMAIL` | Google Workspace Admin | Agent email (e.g., `agent@skyvera.com`) |
| `NOTION_TOKEN` | Notion Integrations page | Internal integration token for CRM database |
| `NOTION_DATABASE_ID` | Notion URL | Database ID for deals pipeline |
| `KNOWLEDGE_QDRANT_URL` | Qdrant Cloud Console | Qdrant Cloud cluster URL |
| `KNOWLEDGE_QDRANT_API_KEY` | Qdrant Cloud Console | Qdrant Cloud API key |
| `RECALL_AI_API_KEY` | Recall.ai Dashboard | Bot management API |
| `DEEPGRAM_API_KEY` | Deepgram Console | Speech-to-text API |
| `ELEVENLABS_API_KEY` | ElevenLabs Dashboard | Text-to-speech API |
| `ELEVENLABS_VOICE_ID` | ElevenLabs Dashboard | Voice ID for agent |
| `HEYGEN_API_KEY` | HeyGen Dashboard | Avatar rendering API |
| `HEYGEN_AVATAR_ID` | HeyGen Dashboard | Specific avatar ID |
| `MEETING_BOT_WEBAPP_URL` | Vercel Dashboard | Production URL of meeting-bot-webapp |
| `LANGFUSE_PUBLIC_KEY` | Langfuse Cloud | LLM observability public key |
| `LANGFUSE_SECRET_KEY` | Langfuse Cloud | LLM observability secret key |
| `SENTRY_DSN` | Sentry Dashboard | Error monitoring DSN |
| `CORS_ALLOWED_ORIGINS` | Developer choice | Comma-separated allowed origins |

## Google Workspace Provisioning Checklist

Full steps for setting up the agent email and domain-wide delegation:

1. **Create agent email account** in Google Workspace Admin (`agent@skyvera.com`)
2. **Create GCP project** (or use existing) at console.cloud.google.com
3. **Enable APIs** in the GCP project:
   - Gmail API
   - Google Calendar API
   - Google Chat API
4. **Create service account** in GCP IAM:
   - Name: `sales-agent-service`
   - No additional roles needed (delegation handles access)
5. **Generate JSON key** for the service account and download
6. **Copy the Client ID** from the service account details page (numeric, not email)
7. **Configure domain-wide delegation** in Google Admin Console:
   - Navigate to: Security > Access and data control > API controls > Manage Domain Wide Delegation
   - Click "Add new"
   - Client ID: (from step 6)
   - Scopes (comma-separated):
     ```
     https://www.googleapis.com/auth/gmail.send,https://www.googleapis.com/auth/gmail.readonly,https://www.googleapis.com/auth/gmail.modify,https://www.googleapis.com/auth/calendar.readonly,https://www.googleapis.com/auth/calendar.events.readonly
     ```
   - Click "Authorize"
8. **Wait 5-15 minutes** for delegation to propagate (can take up to 24 hours)
9. **Base64-encode** the JSON key: `cat service-account.json | base64 -w 0`
10. **Store** as `GOOGLE_SERVICE_ACCOUNT_JSON_B64` in GitHub Actions secrets
11. **Store** `agent@skyvera.com` as `GOOGLE_DELEGATED_USER_EMAIL` in GitHub Actions secrets

## Notion CRM Production Setup Checklist

1. **Create a Notion internal integration** at notion.so/my-integrations
2. **Copy the integration token** (starts with `ntn_`)
3. **Create (or identify) the deals pipeline database** in Notion
4. **Share the database** with the integration (click "..." on database page > Connections > Add connection)
5. **Get the database ID** from the Notion URL: `https://www.notion.so/WORKSPACE/DATABASE_ID?v=...`
6. **Verify database properties** match the expected field mapping:
   - "Deal Name" (title), "Stage" (select), "Value" (number), "Close Date" (date), "Product" (select), "Probability" (number), "Source" (select), "Contact" (rich_text), "Email" (email)
7. **Store** token as `NOTION_TOKEN` and database ID as `NOTION_DATABASE_ID` in GitHub Actions secrets

## Open Questions

Things that couldn't be fully resolved:

1. **Production PostgreSQL and Redis provider**
   - What we know: Cloud Run needs managed Postgres and Redis accessible via connection strings
   - What's unclear: Which provider is being used (Cloud SQL? Supabase? Neon? Upstash? Memorystore?)
   - Recommendation: The plan should include a task to verify/provision production database and Redis. If not yet provisioned, Cloud SQL (Postgres) + Memorystore (Redis) are the GCP-native options. Alternatively, Supabase/Neon + Upstash are simpler serverless options.

2. **Qdrant Cloud cluster provisioning**
   - What we know: Knowledge base needs remote Qdrant in production (local `./qdrant_data` path doesn't work in containers)
   - What's unclear: Whether a Qdrant Cloud account/cluster exists already
   - Recommendation: Plan should include provisioning a Qdrant Cloud free-tier cluster, getting the URL and API key, and initializing collections.

3. **Workload Identity Federation pool status**
   - What we know: deploy.yml references a WIF pool named "github" with provider "github"
   - What's unclear: Whether this has been created in GCP already
   - Recommendation: Plan should include verification steps and creation commands if missing.

4. **Vercel project linking to GitHub repo**
   - What we know: `.vercel/project.json` exists locally, `vercel.json` is configured
   - What's unclear: Whether the Vercel project is connected to the GitHub repo for auto-deploy on push
   - Recommendation: Plan should include verification and connection via Vercel Dashboard > Git > Connect.

5. **Production database migration state**
   - What we know: Alembic is configured (`alembic/` directory, `alembic.ini`)
   - What's unclear: Whether production database has been migrated to the latest schema
   - Recommendation: Plan should include running `alembic upgrade head` against production DB (either in a startup script or as a pre-deploy step).

6. **Demo prospect selection**
   - What we know: Must be a real named Skyvera prospect, Discovery/early stage
   - What's unclear: Which specific prospect to use
   - Recommendation: Developer selects during demo guide creation. Plan should prompt for selection.

## Sources

### Primary (HIGH confidence)
- **Codebase analysis** -- `Dockerfile`, `deploy.yml`, `config.py`, `health.py`, `main.py`, `notion.py`, `auth.py`, `calendar.py` all read directly
- [google-github-actions/deploy-cloudrun README](https://github.com/google-github-actions/deploy-cloudrun) -- v3 API, `env_vars` parameter, `env_vars_update_strategy`, `flags`
- [google-github-actions/auth README](https://github.com/google-github-actions/auth) -- v3, Workload Identity Federation configuration
- [Cloud Run health check docs](https://docs.cloud.google.com/run/docs/configuring/healthchecks) -- startup/liveness/readiness probe configuration, defaults, HTTP probe behavior
- [Google OAuth2 service account docs](https://developers.google.com/identity/protocols/oauth2/service-account) -- domain-wide delegation setup steps

### Secondary (MEDIUM confidence)
- [Cloud Run environment variables docs](https://docs.cloud.google.com/run/docs/configuring/services/environment-variables) -- `--set-env-vars` flag, env var configuration
- [Vercel Git integration docs](https://vercel.com/docs/git) -- auto-deploy on push to production branch
- [Google Workspace domain-wide delegation](https://support.google.com/a/answer/162106?hl=en) -- Admin Console setup steps
- [Qdrant Cloud pricing](https://qdrant.tech/pricing/) -- free 1GB tier, managed service setup

### Tertiary (LOW confidence)
- Base64 service account encoding pattern -- sourced from multiple community blog posts, not official Google recommendation (but widely used and functional)

## Metadata

**Confidence breakdown:**
- Standard stack: HIGH -- all tools are already in the codebase or are official Google Actions with verified documentation
- Architecture: HIGH -- patterns directly derived from existing codebase analysis (deploy.yml, config.py, health.py)
- Pitfalls: HIGH -- every pitfall identified from direct code reading (missing env vars, Secret Manager references, incomplete health checks)
- Credential provisioning: MEDIUM -- Google Workspace delegation steps verified via official docs, but exact UX may vary with admin console version

**Research date:** 2026-02-22
**Valid until:** 2026-03-22 (30 days -- infrastructure tooling is stable)
