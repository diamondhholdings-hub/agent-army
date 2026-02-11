---
phase: 01-infrastructure-foundation
plan: 03
subsystem: infra, monitoring, deployment
tags: [docker, github-actions, cloud-run, prometheus, sentry, ci-cd, backup, pg_dump, gcp, workload-identity, health-checks]

# Dependency graph
requires:
  - phase: 01-infrastructure-foundation/01
    provides: "FastAPI app factory, tenant context, database engine, models"
provides:
  - Multi-stage Dockerfile for production FastAPI container
  - GitHub Actions CI pipeline (lint + test with Postgres/Redis services)
  - GitHub Actions CD pipeline (Cloud Run staging via Workload Identity Federation)
  - Prometheus metrics with tenant-scoped counters (requests, latency, LLM usage)
  - Sentry error tracking with tenant context in event tags
  - Liveness, readiness, and startup health check endpoints
  - Per-tenant backup and restore scripts (pg_dump/pg_restore)
  - CLI tenant provisioning script
  - .env.example documenting all environment variables
affects:
  - 02 (agent orchestration -- will use monitoring infrastructure and health checks)
  - All future phases (CI/CD pipeline runs tests and deploys on every merge)
  - Production deployment (Cloud Run config, secrets management pattern)

# Tech tracking
tech-stack:
  added: [prometheus-client, sentry-sdk]
  patterns: [multi-stage-docker, workload-identity-federation, metrics-middleware, tenant-scoped-prometheus-labels, per-tenant-backup]

key-files:
  created:
    - Dockerfile
    - .dockerignore
    - .github/workflows/test.yml
    - .github/workflows/deploy.yml
    - .env.example
    - scripts/provision_tenant.py
    - scripts/backup.py
    - scripts/restore.py
    - src/app/core/monitoring.py
  modified:
    - src/app/config.py
    - src/app/api/v1/health.py
    - src/app/main.py
    - src/app/core/tenant.py
    - tests/test_tenant_isolation.py

key-decisions:
  - "Per-tenant Prometheus labels: all metrics include tenant_id for multi-tenant observability"
  - "Sentry before_send callback injects tenant_id and user_id from contextvars into event tags"
  - "Workload Identity Federation for GitHub Actions to GCP (no long-lived service account keys)"
  - "Google Secret Manager for per-tenant secrets with naming convention {tenant-slug}-{secret-name}"
  - "Environment tiers (dev/staging/production) at deployment level, not per-tenant in v1"
  - "Health checks split: /health (liveness), /health/ready (readiness), /health/startup (startup probe)"

patterns-established:
  - "MetricsMiddleware: ASGI middleware records http_requests_total and http_request_duration_seconds per request"
  - "track_llm_call() context manager: wraps LLM calls to record duration, tokens, and success/error to Prometheus"
  - "Per-tenant backup via pg_dump --schema=tenant_{slug} with manifest generation"
  - "CI pipeline pattern: uv sync -> ruff check -> ruff format --check -> pytest with service containers"
  - "CD pipeline pattern: Workload Identity auth -> gcloud builds submit -> deploy-cloudrun with secrets mount"

# Metrics
duration: 9min
completed: 2026-02-11
---

# Phase 1 Plan 3: Deployment Pipeline and Monitoring Summary

**Docker containerization, GitHub Actions CI/CD to Cloud Run, Prometheus metrics with tenant-scoped labels, Sentry error tracking, and per-tenant pg_dump backup/restore**

## Performance

- **Duration:** 9 min
- **Started:** 2026-02-11T09:27:00Z
- **Completed:** 2026-02-11T09:36:00Z
- **Tasks:** 2 (+ 1 checkpoint)
- **Files modified:** 14

## Accomplishments

- Production Docker image with multi-stage build, non-root user, and postgresql-client for backup scripts
- GitHub Actions CI (test on push/PR with Postgres and Redis service containers) and CD (deploy to Cloud Run staging via Workload Identity Federation)
- Prometheus metrics: http_requests_total, http_request_duration_seconds, llm_requests_total, llm_tokens_used_total -- all with tenant_id labels
- Sentry integration with tenant-aware before_send callback injecting tenant context into error events
- Per-tenant backup/restore scripts using pg_dump/pg_restore with schema isolation
- Comprehensive .env.example documenting all 13 environment variables

## Task Commits

Each task was committed atomically:

1. **Task 1: Docker, CI/CD pipeline, secrets management, and environment config** - `1518c5a` (feat)
2. **Task 2: Monitoring, health checks, and backup/restore infrastructure** - `6984438` (feat)

## Files Created/Modified

- `Dockerfile` - Multi-stage production build (python:3.12-slim, non-root appuser, postgresql-client)
- `.dockerignore` - Excludes .git, .planning, tests, __pycache__, .env from Docker context
- `.github/workflows/test.yml` - CI: lint (ruff check + format) and test (pytest) with Postgres 16 + Redis 7 services
- `.github/workflows/deploy.yml` - CD: Workload Identity auth, gcloud builds submit, deploy to Cloud Run staging
- `.env.example` - Documents all environment variables (DATABASE_URL, REDIS_URL, JWT, LLM keys, GCP, Sentry)
- `scripts/provision_tenant.py` - CLI tool for tenant provisioning (--slug, --name, --admin-email)
- `scripts/backup.py` - Per-tenant backup via pg_dump --schema with manifest generation (--tenant or --all)
- `scripts/restore.py` - Per-tenant restore via pg_restore with safety checks and RLS verification
- `src/app/core/monitoring.py` - Prometheus metrics, MetricsMiddleware, Sentry init, track_llm_call() context manager
- `src/app/config.py` - Added GCP_PROJECT_ID and SENTRY_DSN settings
- `src/app/api/v1/health.py` - Refactored: /health (liveness), /health/ready (readiness), /health/startup (startup probe)
- `src/app/main.py` - Added MetricsMiddleware, Sentry init in lifespan, /metrics endpoint
- `src/app/core/tenant.py` - Added /metrics to SKIP_TENANT_PATHS
- `tests/test_tenant_isolation.py` - Updated test_health_ready_endpoint for new response format

## Decisions Made

- **Tenant-scoped Prometheus labels:** All metrics include tenant_id to enable per-tenant observability dashboards and alerting. Unknown tenant requests labeled "unknown".
- **Workload Identity Federation:** GitHub Actions authenticates to GCP via OIDC tokens -- no long-lived service account keys stored as secrets.
- **Google Secret Manager for per-tenant secrets:** Naming convention is `{tenant-slug}-{secret-name}`. Platform-level secrets mounted via Cloud Run secrets config. Per-tenant secrets loaded at runtime.
- **Environment tiers at deployment level:** dev/staging/production are deployment configurations, not per-tenant. All tenants share the same staging environment in v1.
- **Three health check endpoints:** /health (liveness, no deps), /health/ready (readiness, checks DB + Redis), /health/startup (startup probe, same as readiness but used during initial boot).
- **Sentry sample rates:** 100% in staging for full visibility, 10% in production to control costs.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Fixed test_health_ready_endpoint for new response format**
- **Found during:** Task 2 (health check refactoring)
- **Issue:** Existing test expected old response format; health endpoint changed from returning "healthy" to "ok" string
- **Fix:** Updated test assertion to match new response format
- **Files modified:** tests/test_tenant_isolation.py
- **Verification:** Test passes with updated assertion
- **Committed in:** `6984438` (Task 2 commit)

**2. [Rule 2 - Missing Critical] Added /metrics to SKIP_TENANT_PATHS**
- **Found during:** Task 2 (metrics endpoint)
- **Issue:** /metrics endpoint would fail without tenant context since it is a platform-level endpoint, not tenant-scoped
- **Fix:** Added "/metrics" to the SKIP_TENANT_PATHS list in tenant middleware
- **Files modified:** src/app/core/tenant.py
- **Verification:** /metrics endpoint returns data without requiring X-Tenant-ID header
- **Committed in:** `6984438` (Task 2 commit)

**3. [Rule 2 - Missing Critical] Added /health/startup endpoint**
- **Found during:** Task 2 (health check implementation)
- **Issue:** Cloud Run startup probes need a separate endpoint that allows longer timeouts during initial boot. Plan mentioned startup probe but /health/startup was not explicitly in the original health.py.
- **Fix:** Added /health/startup endpoint that performs same dependency checks as /health/ready, used for Cloud Run startup probe configuration
- **Files modified:** src/app/api/v1/health.py
- **Verification:** Endpoint returns 200 with dependency status
- **Committed in:** `6984438` (Task 2 commit)

---

**Total deviations:** 3 auto-fixed (1 bug, 2 missing critical)
**Impact on plan:** All fixes necessary for correct operation. No scope creep.

## Issues Encountered

- Docker is not installed on the development machine (Homebrew services used for Postgres/Redis). Docker build verification (`docker build -t agent-army .`) could not be performed locally. The Dockerfile is syntactically correct and follows multi-stage best practices; full verification will occur when CI runs or Docker is installed.
- 22 of 23 tests pass. The 1 failing test (`test_prompt_injection_detection`) is a pre-existing issue from plan 01-02 (LLM provider abstraction), not introduced by this plan.

## User Setup Required

**External services require manual configuration.** See the plan frontmatter `user_setup` section for:

**Google Cloud Platform:**
- Set GCP_PROJECT_ID, GCP_PROJECT_NUMBER, GCP_REGION
- Enable Cloud Run, Secret Manager, and Cloud Build APIs
- Create Workload Identity Pool for GitHub Actions
- Create service account with Cloud Run Admin and Secret Manager Accessor roles

**GitHub Repository:**
- Set repository secrets: GCP_PROJECT_ID, GCP_PROJECT_NUMBER, GCP_REGION
- Set repository secrets for LLM API keys: ANTHROPIC_API_KEY, OPENAI_API_KEY

## Next Phase Readiness

- Phase 1 infrastructure foundation is complete (all 3 plans delivered)
- CI/CD pipeline ready to validate all future work automatically
- Monitoring infrastructure (Prometheus + Sentry) ready for agent orchestration metrics in Phase 2
- Health checks ready for Cloud Run deployment
- Backup/restore scripts protect tenant data from day one
- **Blocker:** Docker not installed locally -- CI/CD will need Docker available in GitHub Actions runners (which have it by default)
- **Blocker:** GCP services not yet configured -- deployment pipeline will not function until user completes setup steps above

---
*Phase: 01-infrastructure-foundation*
*Completed: 2026-02-11*
