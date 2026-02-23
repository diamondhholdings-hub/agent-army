---
content_type: "product"
product_category: "monetization"
buyer_persona:
  - technical
sales_stage:
  - evaluation
  - demo
---

# Skyvera Technical Capabilities

## API Specifications

Skyvera exposes a REST API surface across three planes: management, runtime, and reporting.

### Management Plane
- **Base URL**: `https://api.skyvera.io/v2`
- **Auth**: OAuth 2.0 client credentials (Bearer token, 1-hour TTL). API keys available for service accounts.
- **Rate limits**: 1,000 req/min per tenant (burst: 2,000 for 10 s). Headers: `X-RateLimit-Remaining`, `X-RateLimit-Reset`.
- **Versioning**: URI-versioned (`/v2/`). Deprecated versions supported for 12 months with `Sunset` header.

### Runtime Plane
- **Event ingestion**: `POST /v2/events` — accepts JSON or Protobuf payloads, up to 10,000 events per batch.
- **Usage rating**: synchronous (< 100 ms p99) and async batch modes.
- **Webhook callbacks**: configurable per tenant with HMAC-SHA256 signature verification and exponential retry (up to 24 h).

### Reporting Plane
- `GET /v2/reports/{type}` — real-time aggregations or scheduled exports (CSV, Parquet, JSON).
- Supports OData-style `$filter`, `$select`, `$top` query parameters.

## Supported Integration Protocols

| Protocol | Description | Latency (p99) |
|----------|-------------|---------------|
| REST/HTTPS | Primary API; TLS 1.2+ required | < 80 ms |
| gRPC | High-throughput event streaming | < 20 ms |
| Kafka | Event bus integration (managed connector) | async |
| SFTP | Batch file exchange for CDR/billing feeds | N/A |
| SOAP/XML | Legacy BSS/OSS adapter (read-only) | < 200 ms |

Bidirectional sync is available for CRM (Salesforce, HubSpot) and ERP (SAP, Oracle) via certified connectors. Custom adapters supported via the Partner SDK.

## Performance SLAs

### Uptime
- **Production SLA**: 99.95% monthly uptime (≤ 22 min downtime/month).
- **Planned maintenance**: announced 72 h in advance; executed in off-peak windows.
- **RTO / RPO**: 1 h / 15 min for Tier 1 incidents.

### Latency
- API p50: < 25 ms | p95: < 60 ms | p99: < 100 ms (measured at edge).
- Real-time rating pipeline: p99 < 150 ms end-to-end including enrichment.
- Batch rating: 1 M events/min sustained throughput per tenant shard.

### Throughput
- Ingestion: up to 50,000 events/sec per tenant (horizontal auto-scaling).
- Concurrent API connections: 500 per tenant (enterprise tier).

## Security and Compliance

### Certifications
- **SOC 2 Type II**: annual audit, report available under NDA.
- **ISO 27001**: certified since 2022.
- **GDPR**: data residency options (EU, US, APAC); DPA template available.
- **HIPAA**: Business Associate Agreement available for healthcare verticals.
- **PCI DSS Level 1**: for payment processing integrations.

### Data Controls
- At-rest encryption: AES-256. In-transit: TLS 1.3.
- Field-level encryption for PII fields (MSISDN, email, payment tokens).
- Audit logs retained 90 days (configurable to 7 years for compliance tiers).
- Role-based access control (RBAC) with attribute-based policies (ABAC) for enterprise.

## Multi-Tenancy Architecture

Skyvera uses a shared-infrastructure, isolated-data model:
- **Tenant isolation**: dedicated schema per tenant in the data layer; namespace isolation at the API gateway.
- **Resource quotas**: configurable CPU, memory, and throughput limits per tenant.
- **Data residency**: tenant data never crosses region boundaries without explicit consent.
- **White-labeling**: full UI and notification customisation per tenant.

Enterprise customers may opt into a **dedicated shard** deployment for stricter isolation and custom SLAs.
