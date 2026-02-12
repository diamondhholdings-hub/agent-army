---
phase: 05-deal-management
plan: 01
subsystem: database
tags: [sqlalchemy, pydantic, postgresql, alembic, rls, deal-management, political-mapping]

# Dependency graph
requires:
  - phase: 01-infrastructure
    provides: TenantBase, get_tenant_session, Alembic migration chain, RLS pattern
  - phase: 04-sales-agent-core
    provides: DealStage enum, ConversationStateRepository session_factory pattern
provides:
  - SQLAlchemy models for Account, Opportunity, Stakeholder, AccountPlan, OpportunityPlan
  - Pydantic schemas for plan structures, political mapping, CRM payloads, opportunity signals
  - DealRepository with async CRUD for all 5 deal entities
  - Alembic migration 006 with RLS policies and composite indexes
affects: [05-02 opportunity-detection, 05-03 political-mapping, 05-04 crm-sync, 05-05 stage-progression]

# Tech tracking
tech-stack:
  added: []
  patterns:
    - "JSON document pattern for plan_data columns (model_dump/model_validate round-trip)"
    - "Version-incrementing upsert for plan documents (optimistic concurrency)"
    - "find_matching_opportunity for opportunity deduplication by product_line + open status"

key-files:
  created:
    - src/app/deals/__init__.py
    - src/app/deals/models.py
    - src/app/deals/schemas.py
    - src/app/deals/repository.py
    - alembic/versions/add_deal_management_tables.py
  modified: []

key-decisions:
  - "No FK constraints in migration (application-level referential integrity via repository, consistent with existing RLS pattern)"
  - "Plan data stored as JSON columns with Pydantic model_dump/model_validate for schema flexibility"
  - "DealStage imported from agents.sales.schemas (not duplicated) to maintain single source of truth"
  - "StakeholderModel allows nullable contact_email in unique constraint for stakeholders without email"
  - "find_matching_opportunity uses product_line + open status (not timeline comparison) for dedup simplicity"

patterns-established:
  - "DealRepository session_factory pattern: matches ConversationStateRepository exactly"
  - "Version-incrementing upsert: plan_data updated with version++ on each write"
  - "Score transparency: score_sources and score_evidence tracked per stakeholder field"

# Metrics
duration: 6min
completed: 2026-02-12
---

# Phase 5 Plan 01: Deal Management Data Models Summary

**5 SQLAlchemy models (Account, Opportunity, Stakeholder, AccountPlan, OpportunityPlan) with TenantBase RLS, comprehensive Pydantic schemas for plan structures and political mapping, DealRepository with session_factory CRUD, and Alembic migration 006**

## Performance

- **Duration:** 6 min
- **Started:** 2026-02-12T12:47:35Z
- **Completed:** 2026-02-12T12:53:38Z
- **Tasks:** 2
- **Files created:** 5

## Accomplishments
- 5 SQLAlchemy models with TenantBase schema="tenant" and proper unique constraints
- Comprehensive Pydantic schemas: 4 enums, 25+ schema classes covering plans, political mapping, CRM payloads, and opportunity signals
- DealRepository with 16 async CRUD methods following session_factory pattern
- Alembic migration 006 creating all 5 tables with RLS policies and 7 composite indexes
- All field validations: 0-10 for political scores, 0-1 for confidence values

## Task Commits

Each task was committed atomically:

1. **Task 1: SQLAlchemy models and Pydantic schemas** - `6d25ce9` (feat)
2. **Task 2: DealRepository and Alembic migration** - `5d2938e` (feat)

## Files Created/Modified
- `src/app/deals/__init__.py` - Package init with module docstring
- `src/app/deals/models.py` - 5 SQLAlchemy models (AccountModel, OpportunityModel, StakeholderModel, AccountPlanModel, OpportunityPlanModel)
- `src/app/deals/schemas.py` - 25+ Pydantic schemas: enums, stakeholder, plans, CRM, signals
- `src/app/deals/repository.py` - DealRepository with 16 async CRUD methods
- `alembic/versions/add_deal_management_tables.py` - Migration 006: 5 tables, RLS, indexes

## Decisions Made
- No FK constraints in migration -- application-level referential integrity via repository, consistent with existing `add_sales_conversation_state.py` pattern. Tenant-schema tables with RLS cannot use cross-schema FKs reliably.
- DealStage imported from `agents.sales.schemas` (not duplicated) -- single source of truth for the 8-stage pipeline enum.
- Plan data as JSON columns with Pydantic serialization -- provides schema flexibility for plan evolution without migrations, while maintaining type safety at the application layer.
- StakeholderModel unique constraint on (tenant_id, account_id, contact_email) allows nullable email for stakeholders discovered from conversation signals where email is not yet known.
- find_matching_opportunity uses product_line + open status for simplicity -- timeline-based comparison deferred to full implementation when close_date population is more reliable.

## Deviations from Plan

None -- plan executed exactly as written.

## Issues Encountered
None.

## User Setup Required
None -- no external service configuration required.

## Next Phase Readiness
- All 5 models and schemas ready for Plans 02-05 to build upon
- DealRepository provides the persistence layer needed by opportunity detection (05-02), political mapping (05-03), CRM sync (05-04), and stage progression (05-05)
- Alembic migration chain: 006_deal_management depends on 005_learning_tables

---
*Phase: 05-deal-management*
*Completed: 2026-02-12*
