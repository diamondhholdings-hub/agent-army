---
phase: 01-infrastructure-foundation
plan: 02
subsystem: api, auth, llm
tags: [jwt, jose, bcrypt, fastapi, litellm, claude-sonnet-4, gpt-4o, prompt-injection, structlog, cors, sse, api-key, middleware]

# Dependency graph
requires:
  - phase: 01-01
    provides: Multi-tenant database, TenantContext via contextvars, tenant-scoped sessions, app factory
provides:
  - JWT authentication with access/refresh tokens and tenant-scoped claims
  - API key authentication for service-to-service calls
  - TenantAuthMiddleware resolving tenant from JWT, API key, or header
  - LLM provider abstraction via LiteLLM Router (Claude primary, GPT-4o fallback)
  - Prompt injection detection and message sanitization
  - Structured request logging with tenant/user context and X-Request-ID
  - CORS middleware with configurable origins
affects:
  - 01-03 (monitoring -- structured logging already in place)
  - 02 (LLM orchestration -- uses LLMService directly)
  - 03 (knowledge base -- LLM calls for embedding/retrieval)
  - All future phases (every request goes through auth + tenant middleware)

# Tech tracking
tech-stack:
  added: [python-jose, bcrypt, litellm, structlog]
  patterns: [JWT tenant-scoped claims, API key service auth, LiteLLM Router fallback chain, prompt injection heuristic detection, structured logging with contextvars, middleware layering (logging > tenant > auth)]

key-files:
  created:
    - src/app/core/security.py
    - src/app/api/v1/auth.py
    - src/app/api/v1/llm.py
    - src/app/api/middleware/__init__.py
    - src/app/api/middleware/tenant.py
    - src/app/api/middleware/logging.py
    - src/app/schemas/auth.py
    - src/app/schemas/llm.py
    - src/app/services/llm.py
    - tests/test_auth.py
    - tests/test_llm.py
    - tests/test_security.py
  modified:
    - pyproject.toml
    - src/app/api/deps.py
    - src/app/api/v1/router.py
    - src/app/config.py
    - src/app/core/database.py
    - src/app/models/tenant.py
    - src/app/services/tenant_provisioning.py
    - tests/conftest.py
    - uv.lock

key-decisions:
  - "bcrypt directly instead of passlib for Python 3.13 compatibility"
  - "statement_cache_size=0 to avoid asyncpg statement cache conflicts with RLS SET commands"
  - "Explicit commit after SET app.current_tenant_id for session visibility in RLS"
  - "Prompt injection detection as heuristic layer; architectural defense is tenant data isolation"
  - "4 injection pattern categories: override, exfiltration, hijacking, control chars"
  - "LiteLLM Router with reasoning (Claude Sonnet 4) and reasoning-fallback (GPT-4o) model groups"

patterns-established:
  - "JWT claims carry tenant_id and tenant_slug -- middleware extracts from token, not headers"
  - "API key auth as alternative to JWT for service-to-service calls"
  - "TenantAuthMiddleware resolves tenant from JWT > API key > X-Tenant-ID header (priority order)"
  - "All LLM calls include tenant metadata for cost tracking"
  - "Prompt injection detection runs on all user-role messages before LLM calls"
  - "Structured logging via structlog with tenant_id, user_id, request_id on every request"
  - "X-Request-ID header generated per request for distributed tracing"

# Metrics
duration: 22min
completed: 2026-02-11
---

# Phase 1 Plan 2: API Gateway and LLM Integration Summary

**JWT auth with tenant-scoped claims, LiteLLM Router (Claude primary, GPT-4o fallback), prompt injection detection, and structured request logging via structlog**

## Performance

- **Duration:** 22 min
- **Started:** 2026-02-11T09:20:00Z
- **Completed:** 2026-02-11T09:42:00Z
- **Tasks:** 3 (2 auto + 1 checkpoint verification)
- **Files modified:** 21

## Accomplishments

- JWT authentication with access/refresh tokens carrying tenant-scoped claims, plus API key auth for service-to-service
- LLM provider abstraction via LiteLLM Router with Claude Sonnet 4 as primary reasoning model and GPT-4o fallback
- Prompt injection detection with 4 pattern categories and message sanitization that preserves system messages
- Structured request logging via structlog with tenant_id, user_id, request_id, and duration_ms on every request
- 40 total tests passing: 12 auth + 4 LLM + 13 security + 11 isolation (from 01-01)

## Task Commits

Each task was committed atomically:

1. **Task 1: JWT authentication, tenant-scoped authorization, and structured logging** - `197059a` (feat)
2. **Task 2: LLM provider abstraction and prompt injection protection** - `ac0fee8` (feat)

**Task 3:** Checkpoint human-verify -- user approved API gateway, auth flow, and LLM integration.

## Files Created/Modified

- `src/app/core/security.py` - JWT creation/validation, password hashing (bcrypt), API key validation
- `src/app/api/v1/auth.py` - Login, token refresh, /me, and API key creation endpoints
- `src/app/api/v1/llm.py` - LLM completion and streaming completion endpoints (authenticated, tenant-scoped)
- `src/app/api/middleware/__init__.py` - Middleware package init
- `src/app/api/middleware/tenant.py` - TenantAuthMiddleware resolving tenant from JWT claims, API key, or header
- `src/app/api/middleware/logging.py` - Structured request logging with structlog, X-Request-ID generation
- `src/app/schemas/auth.py` - LoginRequest, TokenResponse, TokenRefreshRequest, ApiKeyCreate/Response
- `src/app/schemas/llm.py` - LLMCompletionRequest/Response, LLMMessage with Pydantic validation
- `src/app/services/llm.py` - LLMService with LiteLLM Router, prompt injection detection, message sanitization
- `src/app/config.py` - Added JWT settings, LLM API key settings, LLM timeout/retry config
- `src/app/api/deps.py` - Added get_current_user, get_optional_user, get_current_user_from_api_key dependencies
- `src/app/api/v1/router.py` - Registered auth and LLM routers
- `src/app/core/database.py` - Added statement_cache_size=0 to avoid asyncpg/RLS conflicts
- `src/app/models/tenant.py` - Added User.hashed_password field and ApiKey model with RLS
- `src/app/services/tenant_provisioning.py` - Added api_keys table creation and RLS in tenant provisioning
- `tests/conftest.py` - Added authenticated client fixtures, user creation, API key fixtures
- `tests/test_auth.py` - 12 auth tests: login, refresh, protected endpoints, cross-tenant 403, API keys
- `tests/test_llm.py` - 4 LLM tests: auth required, response structure, tenant metadata, fallback config
- `tests/test_security.py` - 13 security tests: injection detection (override, exfiltration, hijacking, control chars), clean input passthrough, sanitization
- `pyproject.toml` - Added bcrypt, python-jose[cryptography] dependencies
- `uv.lock` - Updated lockfile

## Decisions Made

- **bcrypt directly, not passlib:** passlib has compatibility issues with Python 3.13. Using bcrypt directly avoids the deprecation warnings and breakage.
- **statement_cache_size=0 on asyncpg:** asyncpg's prepared statement cache conflicts with RLS SET commands that change the session context. Disabling the cache ensures each query sees the correct tenant context.
- **Explicit commit after SET app.current_tenant_id:** Without an explicit commit, the SET command was not visible to subsequent queries in the same session, breaking RLS tenant resolution.
- **Heuristic prompt injection detection:** Not a bulletproof solution by design. The real defense is architectural (tenant data never mixed in LLM context). Heuristic patterns catch the most common injection attempts as a defense-in-depth layer.
- **4 injection pattern categories:** override ("ignore previous instructions"), exfiltration ("repeat everything above"), hijacking ("you are now"), and control characters. Categorization enables targeted logging and future tuning.
- **LiteLLM Router model groups:** "reasoning" maps to Claude Sonnet 4 (primary), "reasoning-fallback" maps to GPT-4o. Future "fast" model group for classification tasks is configured but not yet active.

## Deviations from Plan

### Auto-fixed Issues

**1. [Rule 1 - Bug] Used bcrypt directly instead of passlib**
- **Found during:** Task 1 (security.py implementation)
- **Issue:** Plan specified passlib for bcrypt hashing, but passlib has compatibility issues with Python 3.13 (deprecation warnings, potential breakage)
- **Fix:** Used bcrypt library directly with bcrypt.gensalt() and bcrypt.hashpw()
- **Files modified:** src/app/core/security.py, pyproject.toml
- **Verification:** hash_password and verify_password work correctly in tests
- **Committed in:** 197059a (Task 1 commit)

**2. [Rule 1 - Bug] Fixed asyncpg statement cache conflicting with RLS**
- **Found during:** Task 1 (auth tests with tenant-scoped queries)
- **Issue:** asyncpg's prepared statement cache returned stale results after SET app.current_tenant_id because the cached plan didn't reflect the new tenant context
- **Fix:** Set statement_cache_size=0 in the asyncpg connect args
- **Files modified:** src/app/core/database.py
- **Verification:** Auth tests with tenant-scoped queries return correct tenant data
- **Committed in:** 197059a (Task 1 commit)

**3. [Rule 1 - Bug] Fixed tenant session SET visibility**
- **Found during:** Task 1 (cross-tenant authorization tests)
- **Issue:** SET app.current_tenant_id was not visible to subsequent queries in the same session without an explicit commit
- **Fix:** Added explicit commit after the SET command in the tenant session setup
- **Files modified:** src/app/services/tenant_provisioning.py
- **Verification:** Cross-tenant access prevention test (403 on mismatch) passes
- **Committed in:** 197059a (Task 1 commit)

**4. [Rule 2 - Missing Critical] Added CORS middleware**
- **Found during:** Task 1 (main.py middleware setup)
- **Issue:** No CORS middleware configured, which would block frontend requests in development and production
- **Fix:** Added CORSMiddleware with configurable origins (allow all in dev, restricted in production)
- **Files modified:** src/app/main.py
- **Verification:** Server starts with CORS headers in responses
- **Committed in:** 197059a (Task 1 commit)

---

**Total deviations:** 4 auto-fixed (3 bugs, 1 missing critical)
**Impact on plan:** All fixes necessary for correct operation. bcrypt direct usage is a library swap (same algorithm). Statement cache and SET visibility fixes were required for RLS to work with auth. CORS is required for any frontend integration. No scope creep.

## Issues Encountered

- passlib bcrypt wrapper is incompatible with Python 3.13. Using bcrypt directly provides identical security with better compatibility.
- asyncpg's prepared statement cache is a known issue with PostgreSQL session-level configuration like RLS. Setting statement_cache_size=0 is the recommended workaround from the asyncpg documentation.

## User Setup Required

**External services require manual configuration.** API keys needed for LLM functionality:

- **ANTHROPIC_API_KEY** - Get from Anthropic Console -> API Keys (https://console.anthropic.com/settings/keys)
- **OPENAI_API_KEY** - Get from OpenAI Platform -> API Keys (https://platform.openai.com/api-keys)

These are only required for live LLM calls. All tests use mocks and pass without API keys.

## Next Phase Readiness

- API gateway with JWT auth and LLM integration is complete and tested
- Ready for Plan 01-03: Monitoring, health checks, and infrastructure (structured logging already in place)
- Ready for Phase 2: LLM orchestration can use LLMService directly with tenant-scoped calls
- Prompt injection detection provides baseline security for all future LLM interactions
- All 40 tests passing (11 isolation + 12 auth + 4 LLM + 13 security)

---
*Phase: 01-infrastructure-foundation*
*Completed: 2026-02-11*
