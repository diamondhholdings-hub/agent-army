---
product_category: "charging"
buyer_persona:
  - technical
  - operations
sales_stage:
  - discovery
  - evaluation
  - demo
region:
  - global
---

# ESW Charging

ESW Charging is a real-time convergent charging system designed for telecommunications operators and digital service providers. It handles online and offline charging, rating, balance management, and policy control across all service types -- voice, data, messaging, content, IoT, and digital services.

Built for carrier-grade performance, the Charging engine processes over 50,000 transactions per second per node with sub-10ms latency for online charging requests. It supports both 3GPP-standard Diameter (Ro/Rf) interfaces and modern RESTful APIs for cloud-native service integration.

The system converges prepaid and postpaid charging into a single platform, eliminating the operational complexity and cost of maintaining separate charging stacks. Cross-references: Monetization Platform, Billing.

## Real-Time Rating Engine

The Real-Time Rating Engine is the computational core of ESW Charging, responsible for converting raw usage events into rated charges according to customer-specific rate plans.

**Key Capabilities:**

- Multi-dimensional rating across service type, time of day, location, quality of service, and customer segment
- Configurable rating tables with support for flat, tiered, volume, staircase, tap-step, and hybrid pricing models
- Real-time rate plan switching for mid-cycle plan changes with prorated calculations
- Currency conversion with configurable exchange rate feeds and rounding rules
- Tax calculation engine with jurisdiction-aware tax rules and exemption handling
- Rating simulation mode for testing new rate plans against historical traffic without impacting live systems
- Rating exception handling with configurable fallback rules for unmatched events
- Parallel rating for multi-party scenarios (caller pays, called party pays, third-party pays)

**Ideal Buyer Persona:** Technical architects designing rating infrastructure; operations teams managing rate plan catalogs.

**Typical Use Case:** A converged telecom operator needs to rate voice calls, data sessions, and content purchases across prepaid and postpaid subscribers using a single rating engine. The Real-Time Rating Engine applies subscriber-specific rate plans with time-of-day discounts and volume commitments, producing rated CDRs for downstream billing.

## Convergent Charging

Convergent Charging unifies prepaid and postpaid charging into a single real-time platform, eliminating duplicate infrastructure and enabling hybrid business models.

**Key Capabilities:**

- Single charging session handling for both prepaid (online) and postpaid (offline) subscribers
- Hybrid accounts combining prepaid balances with postpaid credit limits
- Real-time balance management with reservation, commitment, and refund operations
- Spending limits and credit controls for postpaid subscribers
- Threshold notifications for balance and spending alerts
- Shared balance accounts for family plans and enterprise groups
- Multi-service convergence: voice, data, SMS, MMS, content, IoT, and digital services all through one charging path
- Diameter Ro (online) and Rf (offline) interfaces per 3GPP TS 32.299

**Ideal Buyer Persona:** Technical leads evaluating convergent charging architectures; operations managers consolidating legacy systems.

**Typical Use Case:** An operator wants to offer hybrid plans where customers can prepay for data bundles while accumulating postpaid voice charges on the same account. Convergent Charging manages both balance types in real time, applying usage against prepaid bundles first and then switching to postpaid accumulation when bundles are exhausted.

**Integration Points:** Feeds rated charges to the Monetization Platform for subscription tracking and the Billing system for invoice generation. Cross-references: Monetization Platform, Billing.

## Policy and Quota Management

Policy and Quota Management provides real-time service control by enforcing usage policies, fair use quotas, and quality of service rules.

**Key Capabilities:**

- Policy decision function (PDF) per 3GPP Diameter Gx/Rx interfaces
- Real-time quota allocation and tracking with configurable refill periods
- Fair use policy enforcement with speed throttling and service gating
- Quality of Service (QoS) control: bandwidth allocation, priority queuing, traffic shaping
- Time-based policies: parental controls, peak/off-peak rules, promotional windows
- Location-based policies: roaming controls, geo-fenced services, network slice assignment
- Policy templates for rapid deployment of standardized policy configurations
- Policy simulation and testing environment for impact analysis

**Ideal Buyer Persona:** Technical architects designing policy infrastructure; operations teams managing fair use and QoS.

**Typical Use Case:** An operator needs to enforce fair use policies on unlimited data plans, throttling speed after 50GB monthly consumption. The Policy module monitors real-time data usage, triggers bandwidth reduction at the threshold, and restores full speed at cycle reset.

## Multi-Service Support

Multi-Service Support enables a single ESW Charging instance to rate and charge for any service type across telecommunications and digital domains.

**Key Capabilities:**

- Voice: Duration-based rating with call setup fees, per-minute rates, and destination surcharges
- Data: Volume-based rating with QoS-aware tiering and speed-based pricing
- Messaging: Per-message rating for SMS, MMS, and rich communication services (RCS)
- Content: Event-based rating for content purchases, in-app transactions, and digital goods
- IoT: High-volume, low-value event rating optimized for machine-to-machine traffic patterns
- Digital services: API call metering, SaaS consumption tracking, and cloud resource rating
- Roaming: Visited network rating with TAP/RAP settlement support and inter-operator tariff management
- 5G network slicing: Per-slice charging with differentiated pricing based on slice SLA

**Ideal Buyer Persona:** Technical architects planning multi-service convergence; business analysts modeling new service pricing.

**Typical Use Case:** A 5G operator offers voice, data, IoT connectivity, and enterprise network slicing from a single platform. Multi-Service Support rates each service type with its native pricing model while presenting a unified balance and spending view to the customer.

## Mediation and Event Processing

Mediation and Event Processing handles the collection, normalization, correlation, and enrichment of raw network events before they enter the rating engine.

**Key Capabilities:**

- Protocol adapters for all major network element interfaces (Diameter, RADIUS, SIP, HTTP, MQTT, AMQP)
- Event normalization converting vendor-specific CDR formats into a canonical event model
- Event correlation linking related events (e.g., SIP INVITE and BYE for call duration calculation)
- Duplicate detection and deduplication using configurable time windows and event fingerprints
- Event enrichment with subscriber profile, location, and service context data
- Partial record handling for long-duration sessions with intermediate charging events
- Event routing to appropriate rating paths based on service type and business rules
- Real-time event streaming with guaranteed delivery and at-least-once processing semantics
- Configurable event buffering with backpressure handling for traffic spikes

**Ideal Buyer Persona:** Technical leads integrating network elements; operations teams managing event processing pipelines.

**Typical Use Case:** A telecom operator receives CDRs from 15 different network elements in proprietary formats. The Mediation module normalizes all events into a standard format, correlates partial records, deduplicates retransmissions, and enriches events with subscriber context before routing to the rating engine.

**Integration Points:** Feeds normalized, rated events to both the Monetization Platform for real-time analytics and the Billing system for settlement processing. Cross-references: Monetization Platform, Billing.

## Performance and Scalability

ESW Charging is engineered for carrier-grade performance meeting the most demanding transaction volumes.

**Performance Specifications:**

- 50,000+ online charging transactions per second per node
- Sub-10ms end-to-end latency for online charging requests (p99)
- Sub-100ms for offline rating batch processing per CDR
- 99.9999% availability with active-active geo-redundant deployment
- Linear horizontal scaling by adding processing nodes
- In-memory balance cache with persistent storage synchronization
- Zero-downtime upgrades with rolling deployment strategy
- Automated failover with less than 1 second detection and switchover time

**Capacity Planning:**

- Supports 100M+ subscriber profiles per deployment
- Handles 1B+ daily transactions in production environments
- Storage optimization with configurable data retention and archival policies

## Deployment and Integration

ESW Charging supports multiple deployment models to accommodate diverse operator environments.

**Deployment Models:**

- Cloud-native on Kubernetes (public cloud or private)
- Bare-metal for ultra-low-latency requirements
- Hybrid deployment with charging nodes at network edge and management plane in cloud
- Virtual network function (VNF) packaging for NFV infrastructure

**Standard Interfaces:**

- 3GPP Diameter Ro (online charging)
- 3GPP Diameter Rf (offline charging)
- 3GPP Diameter Gy (data charging)
- 3GPP Diameter Gx/Rx (policy control)
- RESTful APIs (OpenAPI 3.0)
- AMQP/Kafka for event streaming integration
- SNMP and Prometheus for monitoring
