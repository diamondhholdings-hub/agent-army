---
phase: 09-production-deployment
plan: 02
subsystem: infra
tags: [github-actions, cloud-run, ci-cd, smoke-test, httpx, docker]

# Dependency graph
requires:
  - phase: 09-01
    provides: Dockerfile and base deploy.yml structure
provides:
  - Production deploy-production job in GitHub Actions with all secrets as env_vars
  - verify_production.py CLI smoke test for SC1 (webapp) and SC2 (health endpoint)
  - SHA-tagged Docker image reuse between staging and production
affects: [09-03, 09-04, 09-05]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "env_vars injection over GCP Secret Manager for production secrets"
    - "SHA-tagged Docker images for staging-to-production promotion"
    - "Post-deploy smoke test as CI pipeline gate"

key-files:
  created:
    - scripts/verify_production.py
    - scripts/__init__.py
  modified:
    - .github/workflows/deploy.yml

key-decisions:
  - "All production secrets injected via GitHub Actions env_vars, not GCP Secret Manager"
  - "Docker image tagged with github.sha and reused from staging (no rebuild)"
  - "Smoke test uses httpx with 15s timeout and follow-redirects"

patterns-established:
  - "Production job depends on staging (needs: deploy-staging) for sequential deployment"
  - "env_vars_update_strategy: overwrite ensures clean env on each deploy"

# Metrics
duration: 1min
completed: 2026-02-22
---

# Phase 9 Plan 2: CI/CD Pipeline and Smoke Test Summary

**GitHub Actions production deploy job with 25 env_vars (no Secret Manager) and verify_production.py smoke test for SC1/SC2**

## Performance

- **Duration:** 1 min
- **Started:** 2026-02-23T03:42:49Z
- **Completed:** 2026-02-23T03:44:38Z
- **Tasks:** 2
- **Files modified:** 4

## Accomplishments
- Production deploy-production job added to GitHub Actions workflow with all 25 env vars injected from GitHub secrets
- Staging job updated to auth@v3 and deploy-cloudrun@v3 with SHA-tagged Docker images
- Standalone verify_production.py smoke test script with SC1 (webapp 200) and SC2 (health/ready) checks
- Post-deploy step in CI pipeline runs smoke test automatically against deployed URLs

## Task Commits

Each task was committed atomically:

1. **Task 1: Update deploy.yml with production deployment job** - `e8be57e` (feat)
2. **Task 2: Create production smoke test script** - `a933255` (feat)

## Files Created/Modified
- `.github/workflows/deploy.yml` - Added deploy-production job with env_vars, updated staging to v3 actions
- `scripts/verify_production.py` - Standalone SC1+SC2 verification CLI tool
- `scripts/__init__.py` - Package init for scripts directory

## Decisions Made
- All production secrets injected via GitHub Actions `env_vars` block, not GCP Secret Manager `secrets:` block -- avoids Secret Manager IAM complexity
- Docker image tagged with `github.sha` and reused from staging build (no rebuild in production job) -- faster deploys, identical artifact
- Smoke test uses `httpx` (already a project dependency) with 15s timeout per request

## Deviations from Plan

None - plan executed exactly as written.

## Issues Encountered
None

## User Setup Required
None - no external service configuration required.

## Next Phase Readiness
- deploy.yml production job is ready for first push-triggered deployment
- verify_production.py can be run locally or in CI to validate deployment
- GitHub repository needs PROD_* secrets configured before first production deploy
- Ready for 09-03 (GitHub secrets configuration and first deploy)

---
*Phase: 09-production-deployment*
*Completed: 2026-02-22*
