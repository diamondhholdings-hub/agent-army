# Phase 9: Production Deployment - Context

**Gathered:** 2026-02-22
**Status:** Ready for planning

<domain>
## Phase Boundary

Deploy the Sales Agent platform to production — Vercel hosts the webapp, GCP Cloud Run hosts the backend, all production credentials are wired up, and a complete end-to-end demo scenario runs successfully using real Skyvera data. No new agent capabilities are added here.

</domain>

<decisions>
## Implementation Decisions

### Demo scenario
- Use a real named Skyvera prospect (not a synthetic demo account)
- Scenario starts at Discovery / early stage — first meeting, initial qualification, agent gathers BANT signals
- Demo always runs live against production — no recorded version
- Must be runnable by a non-technical sales person without developer assistance — needs a clear user-facing guide or UI flow

### Secrets & credentials
- Production secrets stored as GitHub Actions secrets, injected as env vars into Cloud Run at deploy time — no GCP Secret Manager for now
- Developer holds all credentials locally; no shared team access required
- Google Workspace: a dedicated agent email (e.g. `agent@skyvera.com`) must be provisioned — the plan should include full setup steps (service account, OAuth scopes, credentials JSON)
- All credential provisioning steps should be documented in the plan so nothing is assumed pre-existing

### Deployment process
- **Vercel webapp**: auto-deploys on push to `main` branch
- **Cloud Run backend**: GitHub Actions CI/CD pipeline deploys on push to `main` — builds container, pushes to GCR, deploys to Cloud Run
- **Cloud Run access**: publicly accessible URL, no IAM auth required — app-level auth handles security (JWT / session checks within the app)

### Verification
- **SC1 (webapp)** and **SC2 (health endpoint)**: automated — Claude decides the form (lean toward a standalone verification script in the repo, optionally also run as a post-deploy step in GitHub Actions)
- **SC3 (Google Workspace)**, **SC4 (Notion CRM)**, **SC5 (end-to-end demo)**: manual verification by the developer
- Sign-off: developer alone — phase is done when all 5 criteria are personally verified as passing
- No external deadline or stakeholder approval required

### Claude's Discretion
- Form of automated verification script (smoke test runner, post-deploy GitHub Actions step, or both)
- Exact Cloud Run container build strategy (Dockerfile optimization, layer caching)
- Health endpoint dependency check implementation details
- Demo guide format (Notion page, Markdown file, or in-app walkthrough)

</decisions>

<specifics>
## Specific Ideas

- The demo must be sales-person-friendly — if a non-technical person can't run it solo, it's not done
- Google Workspace setup should be treated as needing full provisioning steps (don't assume anything exists)

</specifics>

<deferred>
## Deferred Ideas

None — discussion stayed within phase scope.

</deferred>

---

*Phase: 09-production-deployment*
*Context gathered: 2026-02-22*
