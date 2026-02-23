---
content_type: "architecture_template"
product_category: "monetization"
buyer_persona:
  - technical
sales_stage:
  - evaluation
  - implementation
---

# Integration Complexity Guide

## Effort Estimation Matrix

Use this matrix to set realistic expectations with prospects during technical validation.

| Integration Type | Typical Effort | Complexity Drivers |
|-----------------|---------------|-------------------|
| REST API (event ingestion only) | 5–10 days | Auth setup, payload mapping |
| REST API (full management + reporting) | 10–20 days | Schema alignment, error handling |
| Webhook (outbound notifications) | 3–7 days | Endpoint security, retry logic |
| Webhook (bidirectional) | 7–14 days | Idempotency, ordering guarantees |
| Database sync (append-only CDR) | 15–25 days | Schema migration, change detection |
| Database sync (bidirectional) | 25–40 days | Conflict resolution, rollback |
| Kafka event bus | 10–20 days | Topic design, consumer group setup |
| CRM connector (standard) | 5–10 days | Field mapping, object lifecycle |
| ERP connector (SAP/Oracle) | 20–35 days | Data model complexity, approval workflows |
| SOAP/Legacy BSS adapter | 30–50 days | Protocol translation, data quality |

*Estimates assume a competent integration team with basic REST/cloud experience. Add 30% for first-time Skyvera integrators.*

## Common Integration Blockers and Mitigations

### Auth / Identity
- **Blocker**: Customer SSO provider uses non-standard OAuth scopes.
- **Mitigation**: Skyvera supports custom scope mapping; SA provides mapping guide. Fallback to API key with IP allowlist.

### Network / Firewall
- **Blocker**: Customer cannot open egress to Skyvera API endpoints.
- **Mitigation**: Provide static IP ranges for allowlisting. Private Link (AWS PrivateLink / Azure Private Endpoint) available on Enterprise tier.

### Data Model Mismatch
- **Blocker**: Customer's usage events do not map cleanly to Skyvera event schema.
- **Mitigation**: Use the Event Transformation Layer (ETL hooks in runtime plane). Provide canonical schema mapping template.

### Rate Limits
- **Blocker**: Burst traffic exceeds tenant rate limits during peak billing cycles.
- **Mitigation**: Implement exponential backoff with jitter. Request temporary limit increase for migration windows. Evaluate batch ingestion path.

### Legacy System Coupling
- **Blocker**: Existing BSS cannot be modified to emit events; reads from DB only.
- **Mitigation**: Deploy Skyvera's Change Data Capture (CDC) agent alongside legacy DB. Supported for Oracle, MySQL, PostgreSQL, MSSQL.

## Data Transformation Patterns

### Pattern 1: Canonical Event Enrichment
Normalise customer-specific event fields to Skyvera's canonical model before ingestion. Use a lightweight transformer (Lambda, Cloud Function, or custom middleware). Recommended for REST integrations.

### Pattern 2: Pass-Through with Schema Registry
Ingest raw events and configure transformation rules inside Skyvera's Event Transformation Layer. Lower upfront effort; transformation logic lives in Skyvera config rather than customer infrastructure.

### Pattern 3: Dual-Write Bridge
During migration, write to both legacy system and Skyvera simultaneously. Reconciliation report identifies discrepancies. Phased cutover reduces risk.

### Pattern 4: Batch Reconciliation
For billing-critical data, supplement real-time events with a nightly reconciliation batch (SFTP or S3) to catch gaps. Standard practice for MNO integrations.

## Risk Factors by Integration Depth

| Depth | Risk Level | Key Risks |
|-------|-----------|-----------|
| Read-only reporting | Low | Schema drift, auth token rotation |
| Event ingestion only | Medium | Volume spikes, event ordering |
| Full lifecycle (ingest + rate + bill) | High | Data consistency, rollback complexity |
| ERP/BSS bidirectional | Very High | Distributed transaction failures, compliance audit trails |

## Typical POC Acceptance Criteria

A well-scoped POC should validate the critical integration path, not the full feature set.

### Minimum Viable POC (2–4 weeks)
1. Auth flow working end-to-end (OAuth client credentials or API key).
2. 1,000 synthetic events ingested and rated correctly.
3. One report generated matching expected output.
4. Webhook notification received for a test event.

### Extended POC (4–8 weeks)
All MVP criteria plus:
5. Peak load test: 10,000 events/min sustained for 15 min without errors.
6. Failover test: simulated API downtime with retry recovery verified.
7. Security review: penetration test summary or shared assessment passed.
8. Data residency confirmed: all data stored in agreed region.

### Enterprise POC (8–12 weeks)
All Extended criteria plus:
9. SSO integration live with customer IdP.
10. ERP/CRM connector validated with real (sanitised) data.
11. Reconciliation report matches legacy system within 0.01% tolerance.
12. Runbook and rollback plan reviewed and approved by customer ops team.
