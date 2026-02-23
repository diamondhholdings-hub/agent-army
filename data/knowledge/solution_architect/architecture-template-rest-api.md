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

# Architecture Template: REST API Integration

This template describes the standard REST API integration pattern between Skyvera and a prospect's systems. Use this as the starting point when designing API-based integrations during technical evaluations and POC planning.

## Integration Overview

The REST API integration pattern provides synchronous, request-response communication between the prospect's systems and Skyvera's platform. This is the most common integration pattern, suitable for real-time operations such as subscription management, invoice retrieval, payment processing, and usage reporting.

**When to Use REST API Integration:**
- Real-time CRUD operations on billing entities (customers, subscriptions, invoices)
- Synchronous payment processing and status queries
- On-demand report generation and data retrieval
- Administrative operations (tenant config, user management)

**When to Consider Alternatives:**
- High-volume event streaming (prefer Webhooks or CDC)
- Bulk data synchronization (prefer Database Sync)
- Fire-and-forget notifications (prefer Webhooks)

## Authentication

Skyvera's REST API supports two authentication methods. API keys are recommended for server-to-server integrations, while OAuth2 is required for user-facing applications.

### API Key Authentication

- Keys are tenant-scoped and rotatable via the admin dashboard
- Pass via `X-API-Key` header on every request
- Keys support scoped permissions: `read`, `write`, `admin`
- Rate limits are applied per-key, not per-IP
- Key rotation supports overlapping validity periods (old key valid for 24h after rotation)

### OAuth2 Authentication

- Authorization Code flow for user-facing applications
- Client Credentials flow for machine-to-machine (M2M) communication
- Token endpoint: `POST /oauth2/token`
- Access tokens expire in 1 hour; refresh tokens expire in 30 days
- Scopes map to API resource groups: `billing:read`, `billing:write`, `subscriptions:manage`, `payments:process`

## Data Flow

```
Prospect System                    Skyvera Platform
      |                                  |
      |--- POST /v1/customers ---------> |  Create customer
      |<-- 201 Created + customer_id --- |
      |                                  |
      |--- POST /v1/subscriptions -----> |  Create subscription
      |<-- 201 Created + sub_id -------- |
      |                                  |
      |--- POST /v1/usage/events ------> |  Report usage
      |<-- 202 Accepted ---------------- |
      |                                  |
      |--- GET /v1/invoices?customer= -> |  Retrieve invoices
      |<-- 200 OK + invoice list ------- |
```

## Core Endpoints

| Resource | Method | Path | Description |
|----------|--------|------|-------------|
| Customers | POST | `/v1/customers` | Create a new customer |
| Customers | GET | `/v1/customers/{id}` | Retrieve customer details |
| Subscriptions | POST | `/v1/subscriptions` | Create subscription |
| Subscriptions | PATCH | `/v1/subscriptions/{id}` | Modify subscription |
| Usage Events | POST | `/v1/usage/events` | Report metered usage (batch) |
| Invoices | GET | `/v1/invoices` | List invoices (filterable) |
| Invoices | GET | `/v1/invoices/{id}/pdf` | Download invoice PDF |
| Payments | POST | `/v1/payments` | Process a payment |
| Payments | GET | `/v1/payments/{id}` | Get payment status |

All endpoints return JSON with consistent envelope: `{"data": {...}, "meta": {"request_id": "...", "timestamp": "..."}}`.

## Error Handling

Skyvera uses standard HTTP status codes with structured error bodies:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "subscription_id is required",
    "details": [
      {"field": "subscription_id", "reason": "missing_required_field"}
    ],
    "request_id": "req_abc123",
    "documentation_url": "https://docs.skyvera.com/errors/VALIDATION_ERROR"
  }
}
```

**Error Code Categories:**
- `4xx` Client errors: fix the request and retry
- `429` Rate limited: back off and retry with exponential backoff
- `5xx` Server errors: retry with exponential backoff (max 3 retries)

**Idempotency:** All POST endpoints accept an `Idempotency-Key` header. Duplicate requests with the same key within 24 hours return the original response without re-processing.

## Rate Limiting

Rate limits are applied per API key and communicated via response headers:

| Header | Description |
|--------|-------------|
| `X-RateLimit-Limit` | Maximum requests per window |
| `X-RateLimit-Remaining` | Remaining requests in current window |
| `X-RateLimit-Reset` | Unix timestamp when the window resets |

**Default Limits:**
- Standard tier: 1,000 requests/minute
- Enterprise tier: 10,000 requests/minute
- Burst allowance: 2x limit for 10-second windows

**Usage Events Endpoint:** Accepts batch payloads (up to 1,000 events per request) to reduce call volume. Recommended for high-throughput metering.

## Security Considerations

- All traffic over TLS 1.2+ (TLS 1.3 preferred)
- IP allowlisting available for enterprise customers
- Request signing (HMAC-SHA256) available for high-security environments
- PII fields (email, address, payment methods) are encrypted at rest with AES-256
- API keys are stored hashed; full key shown only once at creation
- Audit log records every API call with request_id, timestamp, authenticated principal, and response status
