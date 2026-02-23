---
content_type: "architecture_template"
product_category: "monetization"
buyer_persona:
  - technical
sales_stage:
  - evaluation
  - implementation
region:
  - global
---

# Architecture Template: Database Sync Integration (CDC)

This template describes the Change Data Capture (CDC) integration pattern for synchronizing data between Skyvera and a prospect's databases. Use this when the prospect needs bulk data synchronization, data warehouse population, or bi-directional data flow without building custom API polling logic.

## Integration Overview

The CDC-based database sync pattern captures row-level changes from Skyvera's operational database and streams them to the prospect's target systems in near-real-time. This avoids the overhead of polling REST APIs for changes and provides a complete, ordered change stream for downstream consumers.

**When to Use Database Sync / CDC:**
- Populating data warehouses or analytics platforms with billing data
- Bi-directional sync between Skyvera and legacy billing systems during migration
- Real-time reporting dashboards that need full dataset access
- ETL pipelines that consume incremental changes rather than full snapshots

**When to Consider Alternatives:**
- Single-record real-time operations (use REST API)
- Event-driven workflows triggered by billing events (use Webhooks)
- Simple status notifications (use Webhooks)

## Sync Approach

Skyvera supports two CDC delivery mechanisms:

### Debezium-Based CDC (Recommended)

- Skyvera publishes a Debezium-compatible CDC stream to Apache Kafka
- Topics follow the naming convention: `skyvera.{tenant_id}.{table_name}`
- Each message contains: `before` (previous row state), `after` (new row state), `op` (operation: c/u/d), `ts_ms` (timestamp)
- Consumers use standard Kafka consumer groups for parallel processing
- Supports exactly-once semantics when used with Kafka transactions

### Managed Export (Alternative)

- Scheduled incremental exports via Skyvera's Export API
- Formats: Parquet, CSV, JSON Lines
- Delivery targets: S3, GCS, Azure Blob Storage, SFTP
- Incremental exports include only rows changed since last export timestamp
- Full snapshots available on demand for initial load or reconciliation

## Frequency and Latency

| Mechanism | Latency | Throughput | Best For |
|-----------|---------|------------|----------|
| Debezium CDC | 1-5 seconds | 10,000+ events/sec | Real-time sync, streaming analytics |
| Managed Export (hourly) | Up to 60 minutes | Millions of rows/export | Data warehouse loads |
| Managed Export (daily) | Up to 24 hours | Full dataset | Batch analytics, archival |
| On-demand snapshot | Minutes (varies by size) | Full dataset | Initial load, reconciliation |

**SLA Guarantees:**
- CDC stream: 99.9% delivery within 10 seconds of database commit
- Managed exports: delivered within 15 minutes of scheduled time
- On-demand snapshots: initiated within 60 seconds, completion depends on dataset size

## Conflict Resolution

For bi-directional sync scenarios (e.g., migration parallel-run), Skyvera implements a deterministic conflict resolution strategy:

**Last-Writer-Wins (LWW) with Source Priority:**
1. Each change carries a `source_system` identifier and `modified_at` timestamp
2. If timestamps differ: most recent write wins
3. If timestamps are identical: Skyvera is the authoritative source for billing entities
4. Conflict events are logged to an audit table for review

**Field-Level Merge (Optional):**
- For customer records, field-level merge can be enabled
- Non-conflicting fields from both sources are preserved
- Conflicting fields use LWW with source priority
- Merge decisions are logged with before/after values for audit

**Conflict Dashboard:**
- Real-time view of detected conflicts in the Skyvera admin dashboard
- Filter by entity type, source system, time range, and resolution method
- Manual override capability for unresolved conflicts
- Export conflict log for compliance and audit purposes

## Schema Mapping

Skyvera's CDC stream publishes the following core tables:

| Skyvera Table | Key Fields | Change Frequency |
|---------------|------------|-----------------|
| `customers` | id, name, email, status, metadata | Low (account updates) |
| `subscriptions` | id, customer_id, plan_id, status, billing_period | Medium (lifecycle events) |
| `invoices` | id, customer_id, amount, currency, status, due_date | High (billing cycles) |
| `invoice_line_items` | id, invoice_id, description, amount, quantity | High (billing cycles) |
| `payments` | id, invoice_id, amount, status, payment_method | High (payment processing) |
| `usage_events` | id, subscription_id, metric, quantity, timestamp | Very high (metering) |
| `credit_notes` | id, invoice_id, amount, reason, status | Low (adjustments) |

**Schema Versioning:**
- Schema changes are announced 30 days in advance via the Skyvera changelog
- Additive changes (new columns, new tables) are non-breaking
- Breaking changes (column removal, type changes) use a new topic version: `skyvera.v2.{tenant_id}.{table}`
- Both old and new schema versions are published in parallel for 90 days during transition

## Data Transformation

Skyvera provides built-in transformation capabilities for common mapping needs:

**Currency Normalization:**
- All monetary amounts are published in the smallest currency unit (cents for USD, pence for GBP)
- A `currency` field accompanies every amount field
- Optional: normalized USD equivalent using daily ECB exchange rates

**Timestamp Standardization:**
- All timestamps in UTC ISO 8601 format
- `created_at` and `modified_at` on every record
- CDC `ts_ms` reflects the database commit timestamp (not application time)

**PII Handling:**
- PII fields (email, name, address, phone) can be masked in CDC stream
- Masking options: SHA-256 hash, partial mask (j***@example.com), full redaction
- Configured per-endpoint via the Skyvera admin dashboard
- Unmasked access requires explicit PII access scope on the CDC credential

**Custom Transformations:**
- SQL-based transformation rules applied before CDC publication
- Common use cases: field renaming, type casting, computed columns, filtering
- Transformations are versioned and auditable
