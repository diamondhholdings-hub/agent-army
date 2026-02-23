---
content_type: "poc_template"
product_category: "monetization"
buyer_persona:
  - technical
  - business
sales_stage:
  - demo
  - evaluation
region:
  - global
---

# POC Templates: Proof of Concept Engagement Tiers

This document defines three standard POC engagement tiers for Skyvera implementations. Use these templates when scoping technical evaluations with prospects. Each tier includes scope definition, deliverables with acceptance criteria, success criteria, resource estimates, timeline, and risk factors.

---

## Tier 1: Small POC (Billing API Integration)

**Effort:** 5-10 developer days | **Duration:** 2-3 weeks | **Typical Prospect:** Mid-market, single product line, subscription billing

### Scope

Demonstrate Skyvera's core billing capabilities by integrating a single product line with the prospect's existing systems. This POC validates API connectivity, subscription lifecycle management, and invoice generation for a representative subset of the prospect's billing scenarios.

**In Scope:**
- Customer creation and management via REST API
- Single subscription plan configuration (flat-rate or simple tiered)
- Subscription lifecycle: create, upgrade, downgrade, cancel
- Invoice generation for one billing cycle
- Payment processing via one payment gateway (Stripe or Adyen)
- Basic webhook integration for invoice and payment events

**Out of Scope:**
- Multi-currency billing
- Complex usage-based metering
- Custom invoice templates
- Production data migration
- Performance/load testing

### Deliverables and Acceptance Criteria

| Deliverable | Acceptance Criteria |
|------------|-------------------|
| Integration architecture document | Reviewed and approved by prospect's tech lead |
| API integration code (sample app or connector) | Successfully creates customers, subscriptions, and invoices via API |
| Webhook event handler | Receives and processes invoice.paid and payment.failed events |
| Test billing cycle | Generates accurate invoices for 10+ test customers with correct amounts |
| POC summary report | Documents findings, performance metrics, and go/no-go recommendation |

### Success Criteria

- API response times under 200ms (p95) for all CRUD operations
- Invoice amounts match expected calculations within $0.01 tolerance
- Webhook events delivered within 5 seconds of trigger event
- Zero data integrity errors across the test billing cycle
- Prospect's development team can independently extend the integration

### Resource Estimates

| Role | Skyvera | Prospect |
|------|---------|----------|
| Solution Architect | 2 days | - |
| Backend Developer | 3-5 days | 3-5 days |
| QA Engineer | 1 day | 1 day |
| Project Manager | 1 day | 1 day |

### Timeline

| Week | Activities |
|------|-----------|
| Week 1 | Architecture review, environment setup, API key provisioning, plan configuration |
| Week 2 | Integration development, webhook setup, test billing cycle execution |
| Week 3 | UAT, bug fixes, POC summary report, go/no-go decision meeting |

### Risks

- **API key provisioning delays:** Mitigate by providing sandbox credentials on day 1
- **Prospect developer availability:** Require committed resource allocation before kickoff
- **Scope creep into usage metering:** Firmly defer to Medium POC if needed

---

## Tier 2: Medium POC (Usage-Based Billing + Integrations)

**Effort:** 15-25 developer days | **Duration:** 4-6 weeks | **Typical Prospect:** Growth-stage or enterprise, multiple products, usage-based pricing

### Scope

Demonstrate Skyvera's advanced billing capabilities including usage-based metering, multi-plan configurations, and integration with the prospect's CRM and ERP systems. This POC validates that Skyvera can handle the prospect's full billing complexity.

**In Scope:**
- Everything in Tier 1, plus:
- Usage-based metering with real-time event ingestion
- Multiple plan configurations (subscription + metered hybrid)
- Multi-currency support (2-3 currencies)
- CRM integration (Salesforce or HubSpot) for customer sync
- ERP integration (export to GL system) for revenue data
- Custom invoice template with prospect branding
- Webhook integration for full billing lifecycle events
- CDC sync to prospect's data warehouse (basic setup)

**Out of Scope:**
- Full production data migration
- Custom dunning workflows
- More than 3 currencies
- Performance testing beyond 10,000 events/day
- SSO/SAML integration

### Deliverables and Acceptance Criteria

| Deliverable | Acceptance Criteria |
|------------|-------------------|
| Solution architecture blueprint | Covers all integration points with data flow diagrams; signed off by both teams |
| Usage metering pipeline | Ingests 1,000+ usage events/hour with correct aggregation and rating |
| Multi-plan billing configuration | Generates accurate invoices for hybrid subscription + usage plans |
| CRM integration | Bi-directional customer sync with Salesforce/HubSpot within 5 minutes |
| ERP export | Financial journal entries exported in prospect's GL format |
| Custom invoice template | Branded invoices matching prospect's design requirements |
| CDC data pipeline | Incremental changes flowing to prospect's data warehouse |
| Load test results | System handles 10,000 usage events/day without degradation |
| POC summary report | Comprehensive findings, performance data, TCO comparison, go/no-go recommendation |

### Success Criteria

- Usage event ingestion handles 1,000+ events/hour with sub-second acknowledgment
- Invoice calculations accurate across all plan types (within $0.01 tolerance)
- CRM sync latency under 5 minutes for customer record changes
- CDC stream delivers changes within 30 seconds to data warehouse
- System maintains performance with 10,000+ usage events per day
- Prospect's team demonstrates ability to configure new plans independently

### Resource Estimates

| Role | Skyvera | Prospect |
|------|---------|----------|
| Solution Architect | 5 days | - |
| Backend Developer | 8-12 days | 8-12 days |
| Frontend Developer | 2 days (invoice template) | 2 days |
| QA Engineer | 3 days | 2 days |
| DevOps Engineer | 2 days | 2 days |
| Project Manager | 3 days | 2 days |

### Timeline

| Week | Activities |
|------|-----------|
| Week 1 | Architecture workshop, environment provisioning, plan configuration |
| Week 2 | Core API integration, usage metering pipeline development |
| Week 3 | CRM + ERP integration, custom invoice template |
| Week 4 | CDC pipeline setup, end-to-end testing |
| Week 5 | Load testing, bug fixes, UAT |
| Week 6 | POC report, stakeholder presentation, go/no-go decision |

### Risks

- **Usage metering schema misalignment:** Conduct data modeling workshop in Week 1
- **CRM API rate limits:** Design sync with exponential backoff and batch processing
- **Stakeholder availability for workshops:** Schedule all key meetings at kickoff
- **Multi-currency edge cases:** Define currency conversion rules upfront with finance team

---

## Tier 3: Large POC (Enterprise Platform Validation)

**Effort:** 30-60 developer days | **Duration:** 8-12 weeks | **Typical Prospect:** Large enterprise, complex billing, regulatory requirements, multiple business units

### Scope

Full platform validation demonstrating Skyvera's ability to serve as the enterprise billing backbone. This POC covers multi-business-unit billing, complex pricing models, regulatory compliance, migration planning, and operational readiness. This tier typically leads directly to a production contract.

**In Scope:**
- Everything in Tier 2, plus:
- Multi-business-unit configuration with separate billing profiles
- Complex pricing models: tiered, volume, staircase, prepaid credits, minimum commits
- Full multi-currency support (5+ currencies) with tax calculation
- Complete CRM + ERP + data warehouse integration suite
- SSO/SAML integration for admin dashboard
- Custom dunning workflow configuration
- Production migration plan with parallel-run architecture
- Performance and load testing (production-scale: 100,000+ events/day)
- Security review and compliance documentation (SOC 2 controls mapping)
- Operational runbook: monitoring, alerting, incident response

**Out of Scope:**
- Actual production data migration execution (separate engagement)
- Custom feature development beyond configuration
- Third-party system changes (ERP customization, CRM workflow changes)

### Deliverables and Acceptance Criteria

| Deliverable | Acceptance Criteria |
|------------|-------------------|
| Enterprise architecture document | Full system design with deployment topology, security model, and DR plan |
| Multi-BU billing configuration | Each business unit generates accurate invoices independently |
| Complex pricing engine validation | All pricing models produce correct calculations across 50+ test scenarios |
| Tax integration | Correct tax calculation for 5+ jurisdictions verified against reference data |
| Full integration suite | CRM, ERP, DW, SSO all functional with documented API contracts |
| Migration plan | Step-by-step migration runbook with rollback procedures and parallel-run design |
| Performance test report | 100,000+ events/day sustained for 48 hours with SLA metrics met |
| Security assessment | SOC 2 controls mapped, penetration test passed, compliance gaps documented |
| Operational runbook | Monitoring dashboards, alert definitions, escalation procedures, SLA tracking |
| Executive summary | Business case with ROI model, TCO comparison, and implementation roadmap |

### Success Criteria

- All pricing models produce accurate results across 50+ test scenarios
- System sustains 100,000+ usage events/day for 48 hours without degradation
- Invoice generation for 10,000+ customers completes within 4-hour billing window
- All integrations (CRM, ERP, DW, SSO) operational with documented SLAs
- Security review passes with no critical or high findings
- Migration parallel-run demonstrates data consistency between old and new systems
- Prospect's operations team completes incident simulation exercise
- Executive stakeholders approve ROI model and implementation timeline

### Resource Estimates

| Role | Skyvera | Prospect |
|------|---------|----------|
| Solution Architect | 15 days | - |
| Senior Backend Developer | 15-25 days | 15-25 days |
| Frontend Developer | 5 days | 5 days |
| QA Engineer | 8 days | 5 days |
| DevOps / SRE | 5 days | 5 days |
| Security Engineer | 3 days | 3 days |
| Project Manager | 8 days | 5 days |
| Executive Sponsor | 2 days (reviews) | 2 days (reviews) |

### Timeline

| Week | Activities |
|------|-----------|
| Weeks 1-2 | Architecture workshop, environment provisioning, security review kickoff |
| Weeks 3-4 | Core integration development, multi-BU configuration, pricing model setup |
| Weeks 5-6 | CRM + ERP + DW integration, SSO setup, custom dunning workflows |
| Weeks 7-8 | Migration plan development, parallel-run architecture, tax integration |
| Weeks 9-10 | Performance/load testing, security assessment, operational runbook |
| Weeks 11-12 | UAT, executive review, POC report, contract negotiation preparation |

### Risks

- **Enterprise procurement delays:** Engage procurement early for sandbox access and security questionnaire
- **Multi-BU configuration complexity:** Assign dedicated SA per business unit; run parallel configuration streams
- **Legacy system integration brittleness:** Build adapter layer with circuit breakers; define fallback behavior
- **Stakeholder alignment across business units:** Establish steering committee with bi-weekly check-ins
- **Performance testing infrastructure:** Provision dedicated load test environment in Week 1; do not share with UAT
- **Regulatory compliance gaps:** Engage compliance team in Week 1 for early identification of showstoppers
