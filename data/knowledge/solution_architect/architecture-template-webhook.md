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

# Architecture Template: Webhook Event Integration

This template describes the webhook-based event integration pattern for pushing real-time events from Skyvera to a prospect's systems. Use this when the prospect needs event-driven reactions to billing lifecycle changes without polling.

## Integration Overview

Webhooks provide an event-driven, push-based integration where Skyvera sends HTTP POST callbacks to prospect-registered endpoints whenever significant billing events occur. This pattern is ideal for triggering downstream workflows, updating external systems, and building real-time dashboards.

**When to Use Webhooks:**
- Real-time notifications for billing events (invoice created, payment received, subscription changed)
- Triggering downstream workflows (provisioning, CRM updates, notification emails)
- Keeping external systems in sync without polling
- Event-sourced architectures that consume event streams

**When to Consider Alternatives:**
- Synchronous request-response operations (use REST API)
- Bulk data synchronization (use Database Sync / CDC)
- Sub-second latency requirements (use REST API polling or streaming)

## Event Types Published

Skyvera publishes events across the full billing lifecycle:

| Event Category | Event Type | Description |
|---------------|------------|-------------|
| Customer | `customer.created` | New customer record created |
| Customer | `customer.updated` | Customer details modified |
| Subscription | `subscription.created` | New subscription activated |
| Subscription | `subscription.changed` | Plan upgrade, downgrade, or modification |
| Subscription | `subscription.cancelled` | Subscription cancellation processed |
| Subscription | `subscription.renewed` | Subscription auto-renewed |
| Invoice | `invoice.created` | New invoice generated |
| Invoice | `invoice.finalized` | Invoice finalized and sent to customer |
| Invoice | `invoice.payment_failed` | Payment attempt on invoice failed |
| Invoice | `invoice.paid` | Invoice fully paid |
| Payment | `payment.succeeded` | Payment transaction completed |
| Payment | `payment.failed` | Payment transaction failed |
| Payment | `payment.refunded` | Payment refund processed |
| Usage | `usage.threshold_reached` | Metered usage crossed configured threshold |

Each event payload follows a consistent envelope:

```json
{
  "id": "evt_abc123def456",
  "type": "invoice.paid",
  "created_at": "2025-01-15T10:30:00Z",
  "tenant_id": "tenant_xyz",
  "data": {
    "invoice_id": "inv_789",
    "amount_paid": 4999,
    "currency": "USD",
    "customer_id": "cust_456"
  },
  "api_version": "2025-01-01"
}
```

## Delivery Guarantees

Skyvera provides **at-least-once delivery** for all webhook events:

- Every event is delivered at least once to every registered endpoint
- Duplicate events are possible; consumers must implement idempotent processing
- The `id` field is globally unique and stable across retries — use it as the idempotency key
- Events are ordered per-resource (e.g., all events for `inv_789` arrive in order) but not globally
- Event delivery is guaranteed within the retry window (72 hours from event creation)

## Signature Verification

Every webhook delivery includes a cryptographic signature for verification:

- Signature header: `X-Skyvera-Signature`
- Algorithm: HMAC-SHA256
- Signing key: per-endpoint secret provided at registration time
- Signed payload: raw request body (do NOT parse/re-serialize before verification)

**Verification steps:**
1. Extract the `X-Skyvera-Signature` header value
2. Compute HMAC-SHA256 of the raw request body using your endpoint secret
3. Compare the computed signature with the header value (constant-time comparison)
4. Reject the request if signatures do not match

**Timestamp validation:** The `X-Skyvera-Timestamp` header contains the delivery timestamp. Reject events older than 5 minutes to prevent replay attacks.

## Retry Policy and Dead Letter Queue

When a webhook delivery fails, Skyvera retries with exponential backoff:

| Attempt | Delay | Cumulative Time |
|---------|-------|-----------------|
| 1 (initial) | Immediate | 0 min |
| 2 | 1 minute | 1 min |
| 3 | 5 minutes | 6 min |
| 4 | 30 minutes | 36 min |
| 5 | 2 hours | 2h 36min |
| 6 | 8 hours | 10h 36min |
| 7 | 24 hours | 34h 36min |
| 8 (final) | 48 hours | 82h 36min |

**Failure definition:** HTTP status 4xx (except 429) or 5xx, connection timeout (30s), or DNS resolution failure.

**429 (Rate Limited):** Skyvera respects `Retry-After` header if present; otherwise backs off for 60 seconds.

**Dead Letter Queue (DLQ):**
- After all retry attempts are exhausted, the event moves to the DLQ
- DLQ events are visible in the Skyvera dashboard for 30 days
- Operators can manually replay DLQ events to any registered endpoint
- DLQ events include the full event payload and delivery attempt history

## Webhook Registration

Endpoints are registered via the REST API or the Skyvera dashboard:

```
POST /v1/webhooks
{
  "url": "https://api.prospect.com/skyvera-events",
  "events": ["invoice.paid", "invoice.payment_failed", "subscription.*"],
  "description": "Production billing event handler",
  "active": true
}
```

**Registration features:**
- Wildcard subscriptions: `subscription.*` matches all subscription events
- Multiple endpoints: register different URLs for different event categories
- Test mode: send a `webhook.test` event to verify endpoint connectivity
- Endpoint health: dashboard shows delivery success rate and latency per endpoint
- Secret rotation: generate a new signing secret without downtime (old secret valid for 24h)
