Garment Factory IIoT Platform — Product Requirements Document

| Field | Value |
|---|---|
| Document ID | `PRD-IIOT-001` |
| Version | `1.0` |
| Status | Phase 0 complete — simulated pipeline validated |
| Owner | Ovais Durrani (OT/IT Convergence Engineer) |
| Last updated | 2026-11-15 |
| Related docs | `data-contract-v1.0.1.md`, `architecture-blueprint.md`, `data-flow-diagram.md` |
| Audience | Customers, investors, partners, internal contributors |

---

## 0. How to Read This Document

This PRD describes the **IIoT platform for garment factories** — what it does, who it's for, why it matters, and how we measure success.

- **Business readers** should focus on §1–§6 (Problem, Vision, Users, Success Metrics, Scope, Commercial Model).
- **Technical readers** should focus on §7–§9 (Functional, Non-Functional Requirements, User Stories) and follow the referenced technical docs for depth.
- **Investors and partners** should focus on §1–§6 and §11–§12 (Risks and Roadmap).

**One critical caveat up front:** this platform is currently at **Phase 0** — the full software pipeline is built and working, but on **simulated data**. No real machines are connected yet. §6 explains exactly what's built vs. what remains.

---

## 1. Executive Summary

Garment factories are the second-largest employer in South Asia, producing apparel worth **$1.5 trillion annually** across 200 million+ workers. They are also among the least instrumented manufacturing sectors on earth. **Most garment factories measure OEE on paper, during supervisor rounds, once a shift** — meaning 10–20% of production capacity is lost to downtime that no one can see.

This platform solves that. It's an **on-premise IIoT system** that captures every event from every industrial sewing machine in real time — job completions, machine state changes, faults, power consumption — and computes OEE continuously. No cloud, no internet dependency, no per-machine industrial MES system costing $500K–$5M.

**Status:** Phase 0 complete. The full software pipeline is built end-to-end and validated on simulated data. Phase 1 (one real machine on a bench) begins immediately.

**Business model:** pilot-then-scale. A 4–6 week pilot on one line (15 machines) for **$3K–8K**, followed by per-machine scale-up if the pilot proves value. No customer commitment beyond the pilot.

**Target market:** mid-size garment factories (500–5,000 employees, 200–2,000 machines) in Pakistan, Bangladesh, Vietnam, and India. Long-term target: 1,000 machines per factory across 50 lines.

---

## 2. Problem Statement

### 2.1 The problem — quantified

Garment factories run at **40–60% OEE** (apparel industry benchmark), compared to 70–85% in automotive and 75–80% in food & beverage. The gap is not technology — it's **visibility**.

The three losses are well-known in lean manufacturing:

| Loss category                                   | What it looks like in a garment factory                                        | Estimated impact             |
| ----------------------------------------------- | ------------------------------------------------------------------------------ | ---------------------------- |
| **Availability losses** **(Equipment Failure)** | Machine stops, thread breaks, operator pauses, bobbin changes, faults          | 15–25% of shift time         |
| **Performance losses** **(Reduced Speed)**      | Operator runs machine slower than ideal cycle time, or pauses to adjust fabric | 15–25% of remaining capacity |
| **Quality losses** **(Process Defects)**        | Rework, rejects, machine-specific issues (needle, thread, stitch quality)      | 2–5% of production           |

**Combined, the losses are typically 40–50% of theoretical capacity.** The factory is producing roughly half of what its machines and people are capable of — and no one knows which specific losses are dominant, because no one is measuring them.

### 2.2 Why the problem persists

| Reason | Detail |
|---|---|
| **Manual measurement is inadequate** | Supervisors walk lines periodically and record observations. This misses 30–40% of downtime events entirely, and misclassifies many others. |
| **Commercial MES is too expensive** | Enterprise MES/IIoT systems (Ignition, ThingWorx, Plex, Siemens Opcenter) cost $50K–$500K+ per factory and require 6–12 months to deploy. Mid-size garment factories can't justify this. |
| **Cloud-first vendors don't fit** | Modern IIoT startups assume reliable internet. Most garment factory floors have unreliable connectivity and no appetite for their production data leaving the building. |
| **Garment-specific solutions are rare** | Most IIoT vendors target automotive, pharma, or heavy industry. The garment workflow (per-piece job completion, small-batch production, high product variability) is underserved. |

### 2.3 The cost of not solving it

A mid-size garment factory producing **$500K/month** in finished goods and losing **15% of capacity to invisible downtime** is losing **$75K/month** — **$900K/year** — to causes it cannot identify, let alone fix.

Even recovering 5% of that is $45K/year. A $5K pilot that achieves this pays back in **40 days**.

---

## 3. Vision

> **Every garment factory floor, from Karachi to Dhaka to Ho Chi Minh City, has real-time OEE visibility it can trust — without spending $500K, without a cloud subscription, without 6-month deployment timelines.**
> 
> **To empower every garment factory floor across Asia with an affordable, scalable, and manufacturer-independent IoT platform that delivers real-time operational visibility and analytics they can trust—without massive capital costs, cloud subscriptions, or multi-month deployment timelines.**

### 3.1 What we're building (product vision)

An on-premise IIoT platform that:
1. **Connects to any industrial sewing machine** — with hardware costing under $100 per machine, installed in under 30 minutes.
2. **Captures every event** — job completions, state changes, faults, power consumption — with sub-2-second latency from machine to dashboard.
3. **Computes OEE continuously** — Availability, Performance, Quality — per machine, per line, per shift.
4. **Runs entirely on-premise** — no cloud dependency, no data leaves the factory.
5. **Deploys in days, not months** — 4–6 weeks for a pilot, 8–12 weeks for full-factory scale.

### 3.2 What we're NOT building (product boundaries)

- ❌ **Not a full MES.** We track machines, not work orders, inventory, or ERP integration (that's Phase 6+).
- ❌ **Not a cloud platform.** No AWS, Azure, or GCP dependency. Ever.
- ❌ **Not a predictive maintenance system.** We track faults as events; we don't predict them (that's a possible Phase 7+).
- ❌ **Not a general-purpose industrial IoT platform.** We're purpose-built for garment factories with sewing machines — not welding robots, CNC mills, or assembly lines.

### 3.3 Design principles

| Principle | What it means |
|---|---|
| **Facts first, meanings later** | Capture raw events accurately; compute OEE from raw events. Never compute OEE at ingestion time. |
| **On-premise by default** | No data leaves the factory. No internet dependency. No subscription lock-in. |
| **Cheap enough to deploy per machine** | Under $100/machine hardware. Not $500. Not $5,000. |
| **Reproducible from Git** | `git clone && docker compose up -d` reconstructs the entire system. No manual setup, no configuration drift. |
| **Single writer per data stream** | No service duplicates another's work. No silent corruption from parallel writes. |
| **Honest assumptions** | Every design decision that depends on customer input is documented, tagged, and validated before scaling. |

---

## 4. Target Users & Personas

### 4.1 Primary buyer — Plant Manager / Operations Manager

| Dimension | Detail |
|---|---|
| **Role** | Manages 200–2,000 machines across 10–50 lines |
| **Reports to** | Factory owner / General Manager |
| **KPIs they're measured on** | OEE, on-time delivery, unit cost, labor productivity |
| **Pain** | Knows OEE is low, doesn't know where or why. Under pressure from owner to improve. |
| **Budget authority** | $3K–$15K discretionary spend for a pilot; $50K+ requires owner approval |
| **What they want from a pilot** | "Show me the real numbers. If the numbers are useful, I'll fight for budget to scale." |
| **What would lose them** | A dashboard they don't trust, a deployment that takes months, a monthly cloud bill they can't justify |

### 4.2 Secondary user — Production Supervisor

| Dimension | Detail |
|---|---|
| **Role** | Manages one line (10–20 machines), 2–3 shifts |
| **KPIs they're measured on** | Line OEE, shift output, quality |
| **Pain** | Doesn't know which machine is causing the bottleneck at any moment |
| **What they want** | A live dashboard showing current machine state — which machines are running, which are stopped, which are faulted |
| **What would lose them** | Complexity, lag between reality and dashboard, alerts they can't act on |

### 4.3 Tertiary user — Industrial Engineer / Continuous Improvement

| Dimension | Detail |
|---|---|
| **Role** | Owns OEE methodology, SAM (Standard Allowed Minutes), lean initiatives |
| **Pain** | Manual data collection is exhausting and inaccurate; can't validate improvement initiatives |
| **What they want** | Historical data they can analyze — trend views, comparison across lines, export to their own tools |
| **What would lose them** | No raw data access, no export capability, OEE numbers they can't audit |

### 4.4 Non-user (explicitly out of scope for v1)

- ❌ **Operators** — the platform captures their actions, but they don't interact with it (except pressing a job-complete button, which requires no training)
- ❌ **IT department** — on-premise design means IT has minimal involvement (VLAN setup, backups)
- ❌ **ERP / MES integration** — Phase 6+ scope

---

## 5. Success Metrics

### 5.1 Product success metrics (is the product working?)

| Metric | Phase 0 | Phase 1 | Phase 2 (pilot) | Phase 3+ |
|---|---|---|---|---|
| **Event capture rate** | 100% (simulated) | 100% (one machine) | ≥ 99% (pilot line) | ≥ 99.5% (production) |
| **End-to-end latency** | < 2s | < 2s | < 2s | < 2s |
| **Data accuracy vs. ground truth** | N/A (no ground truth) | ± 5% (vs. manual count) | ± 3% | ± 1% |
| **System uptime** | N/A | 95% (bench) | 99% (pilot) | 99.5% |
| **OEE calculation** | Not implemented | Not implemented | Not implemented | Implemented and validated |
| **Dashboard load time** | < 500ms | < 500ms | < 500ms | < 1s |

### 5.2 Business success metrics (is the business working?)

| Metric | Phase 0 | Phase 2 (pilot) | Phase 6 (factory scale) |
|---|---|---|---|
| **Customers** | 0 | 1 (pilot) | 3–5 |
| **Machines connected** | 3 (simulated) | 15 (one line) | 1,000+ per customer |
| **Revenue** | $0 | $3K–8K per pilot | $50K–150K per customer per year |
| **Pilot-to-production conversion** | N/A | ≥ 50% (half of pilots should convert) | ≥ 70% |
| **Customer-reported value** | N/A | "You showed me things I didn't know" | "OEE improved by X%" |
| **Inbound leads** | 0 (LinkedIn series in progress) | 2–3 per month from series | 10+ per month |

### 5.3 What success looks like at Phase 2

**The Phase 2 pilot succeeds when a plant manager says:**

> "I didn't know machine 7 was stopping 40 times a shift. I put a supervisor on it last week, and the stops are down to 8. I want this on the whole factory."

**The Phase 2 pilot fails when the plant manager says:**

> "Nice dashboard. But I still don't see anything I didn't already know."

**The difference is not the technology — it's the specific, actionable insight.** A dashboard that shows "OEE = 62%" is not useful. A dashboard that shows "Machine 7 stopped 40 times yesterday, each time for 45–90 seconds, all between 2–3 PM" is a reason to act.

**The pilot must produce that specific insight for at least one machine.** Otherwise the product has failed, regardless of the OEE number.

---

## 6. Current State — Phase 0 Complete (What's Built vs. What Remains)

### 6.1 What's built (Phase 0)

| Capability | Status | Detail |
|---|---|---|
| **MQTT infrastructure** | ✅ Complete | Mosquitto broker, retained state topics, QoS policies |
| **Event pipeline** | ✅ Complete | Node-RED state machine with hysteresis, deduplication, retained state publish |
| **Power pipeline** | ✅ Complete | Telegraf power ingestion, `power_metrics` + `power_latest` tables |
| **Data schema** | ✅ Complete | TimescaleDB with 6 tables, `(event_id, time)` deduplication, triggers, continuous aggregates |
| **State model** | ✅ Complete | 5 states (RUNNING, IDLE, STOPPED, FAULT, OFFLINE), 10 normative transition rules |
| **Dashboard** | ✅ Complete | Grafana with 6 panels, 2 template variables, 5-second refresh |
| **Data contract** | ✅ Complete | v1.0.1 with 20 explicit `[ASSUMPTION]` items, 15 sections, validation script |
| **Simulator** | ✅ Complete | Python simulator with realistic state transitions, configurable cadence |
| **Reproducibility** | ✅ Complete | `docker compose up -d` reconstructs entire system |
| **Documentation** | ✅ Complete | Data contract, architecture blueprint, data flow diagrams, README |

### 6.2 What's NOT built (deliberately deferred to later phases)

| Capability | Phase | Why deferred |
|---|---|---|
| **Real hardware integration** | Phase 1 | Requires physical bench and ESP32-S3 hardware |
| **Pilot line deployment** | Phase 2 | Requires a customer |
| **TLS + authentication** | Phase 2 | Hard gate for pilot — no anonymous access in production |
| **OEE calculation** | Phase 3 | Requires all 20 assumptions validated first |
| **Multi-line scale** | Phase 5 | Architecture is designed for 1,000 machines; not load-tested yet |
| **Fault code catalogue** | Requires vendor data | Placeholder codes (E-101 through E-110) — real codes come from machine control boards |
| **BOM pricing** | Phase 1 | Requires distributor quotes |
| **Production runbook** | Phase 2 | Installation procedure per machine |
| **HA / clustering** | Phase 5+ | Single VM acceptable through Phase 4 |

### 6.3 The 20 unvalidated assumptions

The data contract (`data-contract-v1.0.1.md` §2) contains 20 `[ASSUMPTION]` items that must be validated against a real customer before Phase 2 can proceed. These are the critical-path dependencies between "the software works" and "the system is useful."

**Highest-impact assumptions (must be validated in the first customer meeting):**

| ID | Assumption | If wrong, impact |
|---|---|---|
| A-01 | Shift length = 480 min, breaks = 60 min | Availability denominator changes |
| A-02 | IDLE is NOT downtime | Availability math changes |
| A-03 | STOPPED is downtime | Availability math changes |
| A-04 | Ideal cycle time per SKU (45s for T-shirt) | Performance metric changes |
| A-11 | "Job Complete" per piece, not per bundle | **Critical** — 10× difference in event volume |
| A-16 | Motor type (servo vs. clutch) | Noise mitigation depth |

**The validation checklist (`data-contract-v1.0.1.md` §14) is the meeting agenda for the first customer call.**

---

## 7. Scope — What This Product Does

### 7.1 In scope (v1.0)

| Capability | Description | Phase |
|---|---|---|
| **Event capture** | Job completions, faults, state changes, from every machine | ✅ Phase 0 (simulated), Phase 1 (real) |
| **Power telemetry** | Voltage, current, wattage, energy — every 5 seconds | ✅ Phase 0 (simulated), Phase 1 (real) |
| **State machine** | 5 states with hysteresis-based debounce (10s stop, 15s idle, 60s offline) | ✅ Phase 0 |
| **Retained state** | Real-time machine status broadcast on MQTT `state` topic | ✅ Phase 0 |
| **Real-time dashboard** | 6 panels, 2 variables, 5-second refresh | ✅ Phase 0 |
| **Historical data** | TimescaleDB hypertables, continuous aggregates | ✅ Phase 0 |
| **Data contract** | Frozen, validated, with executable conformance checks | ✅ Phase 0 |
| **OEE calculation** | Availability × Performance × Quality | Phase 3 |
| **Alerting** | Email/SMS on OFFLINE / FAULT / POWER_STALE | Phase 4 |
| **Pilot installation** | Physical hardware on real machines | Phase 1–2 |
| **Production deployment** | TLS, auth, ACLs, backups | Phase 2 |

### 7.2 Out of scope (v1.0) — explicitly

| Not included | Why |
|---|---|
| **Cloud deployment** | On-premise is a design principle, not a limitation |
| **Mobile app** | Grafana dashboards are responsive; no separate app |
| **ERP integration** | Phase 6+ — requires MES/ERP API access |
| **Predictive maintenance** | Phase 7+ — requires more data than v1 will capture |
| **Machine control** | Read-only for v1 — no commands to change machine state |
| **Multi-tenant / SaaS** | Single-factory deployment per instance |
| **Video / vision inspection** | Phase 7+ — ESP32-P4 with MIPI-CSI is the future chip for this |

---

## 8. Functional Requirements

Functional requirements are grouped by capability. Each has a priority: **P0** (must-have for v1), **P1** (should-have), **P2** (nice-to-have).

### 8.1 Event Ingestion

| # | Requirement | Priority | Status |
|---|---|---|---|
| F-01 | System accepts MQTT events on `factory/{line}/machine/{id}/event` | P0 | ✅ |
| F-02 | `JOB_COMPLETE` events are captured with job_id, operator_id, garment_sku, quantity | P0 | ✅ |
| F-03 | `FAULT` events are captured with fault_code, description, severity | P0 | ✅ |
| F-04 | `STATE_CHANGE` events are generated by the state machine with previous and new state | P0 | ✅ |
| F-05 | Duplicate events (same `event_id` + `timestamp`) are silently dropped via `ON CONFLICT DO NOTHING` | P0 | ✅ |
| F-06 | Malformed JSON is captured to `dead_letter` table and does not block pipeline | P1 | ⏳ (Phase 4) |
| F-07 | Events use **device-side timestamps**, not server time, for deduplication | P0 | ✅ |

### 8.2 Power Telemetry

| # | Requirement | Priority | Status |
|---|---|---|---|
| F-10 | System accepts power samples on `factory/{line}/machine/{id}/power` at 5-second cadence | P0 | ✅ |
| F-11 | Samples include voltage, current, power, energy, power_factor, frequency | P0 | ✅ |
| F-12 | `power_latest` table is UPSERTed on every insert (trigger-based) | P0 | ✅ |
| F-13 | `power_1min` continuous aggregate refreshes every 1 minute | P0 | ✅ |
| F-14 | Power quality flags (`good` / `suspect` / `bad`) are captured | P1 | ✅ |
| F-15 | Inrush current spikes are filtered from analytics (Phase 4 hardening) | P2 | ⏳ |

### 8.3 State Machine

| # | Requirement | Priority | Status |
|---|---|---|---|
| F-20 | State transitions follow the 10 normative rules in data contract §4.2 | P0 | ✅ |
| F-21 | Debounce windows: STOP 10s, IDLE 15s, RUN 3s, FAULT 200ms | P0 | ✅ |
| F-22 | OFFLINE detection after 60s of no heartbeat | P0 | ✅ |
| F-23 | Retained state is published on `factory/{line}/machine/{id}/state` | P0 | ✅ |
| F-24 | LWT (Last Will and Testament) publishes OFFLINE if device disconnects | P1 | ⏳ (Phase 1) |
| F-25 | State machine handles first-ever event from a new machine (defaults to STOPPED) | P0 | ✅ |

### 8.4 Dashboard & Visualization

| # | Requirement | Priority | Status |
|---|---|---|---|
| F-30 | Dashboard displays live state per machine (color-coded) | P0 | ✅ |
| F-31 | Dashboard displays live power trend (last 10 minutes) | P0 | ✅ |
| F-32 | Dashboard displays current power gauge per machine (repeat by variable) | P0 | ✅ |
| F-33 | Dashboard displays state timeline (last 1 hour) | P0 | ✅ |
| F-34 | Dashboard displays jobs completed today | P0 | ✅ |
| F-35 | Dashboard displays recent events with JSON payloads | P0 | ✅ |
| F-36 | Dashboard refreshes every 5 seconds automatically | P0 | ✅ |
| F-37 | Dashboard is provisioned from Git (survives `down -v`) | P0 | ✅ |

### 8.5 OEE Calculation (Phase 3 — not yet built)

| # | Requirement | Priority | Phase |
|---|---|---|---|
| F-40 | Availability = RUNNING time / (RUNNING + IDLE + STOPPED + FAULT) | P0 | Phase 3 |
| F-41 | Performance = (ideal_cycle_time × JOB_COMPLETE count) / RUNNING time | P0 | Phase 3 |
| F-42 | Quality = Good count / Total count (v1: placeholder = 100%) | P0 | Phase 3 |
| F-43 | OEE = A × P × Q, computed per machine, per line, per shift | P0 | Phase 3 |
| F-44 | OEE data available for historical analysis (week-over-week) | P1 | Phase 3 |
| F-45 | OEE numbers are auditable (raw events always traceable) | P0 | Phase 3 |

---

## 9. Non-Functional Requirements

### 9.1 Performance

| # | Requirement | Target | Status |
|---|---|---|---|
| NF-01 | Event latency (device to dashboard) | < 2 seconds (p99) | ✅ 14ms current |
| NF-02 | Dashboard load time | < 500ms | ✅ |
| NF-03 | Ingestion throughput | 200 msg/s at 1,000 machines | ✅ Telegraf handles |
| NF-04 | Query response (real-time panels) | < 100ms | ✅ sub-50ms |
| NF-05 | Query response (historical panels) | < 1 second | ✅ |
| NF-06 | System uptime (Phase 2 pilot) | 99% | ⏳ |

### 9.2 Reliability

| # | Requirement | Target | Status |
|---|---|---|---|
| NF-10 | Event capture rate | ≥ 99% (Phase 2 pilot) | ✅ 100% (simulated) |
| NF-11 | Duplicate event rate | 0 (guaranteed by `(event_id, time)` unique index) | ✅ |
| NF-12 | Graceful degradation on DB outage | Telegraf buffers; Node-RED retries | ⏳ (Phase 4) |
| NF-13 | Graceful recovery after network outage | Events buffered on ESP32, flushed on reconnect | ⏳ (Phase 1) |

### 9.3 Security (Phase 2 gate — mandatory before pilot)

| # | Requirement | Priority | Status |
|---|---|---|---|
| NF-20 | TLS on MQTT (port 8883) | P0 (Phase 2) | ⏳ |
| NF-21 | Per-device credentials (username/password) | P0 (Phase 2) | ⏳ |
| NF-22 | ACLs restricting each device to its own topics | P0 (Phase 2) | ⏳ |
| NF-23 | Node-RED UI login | P0 (Phase 2) | ⏳ |
| NF-24 | Grafana login (no anonymous) | P0 (Phase 2) | ⏳ |
| NF-25 | Nightly `pg_dump` with tested restore | P0 (Phase 2) | ⏳ |

### 9.4 Deployment

| # | Requirement | Target | Status |
|---|---|---|---|
| NF-30 | Full system deployment time | < 30 minutes (fresh clone to working) | ✅ ~5 minutes |
| NF-31 | Per-machine installation time | < 30 minutes | ⏳ (Phase 1) |
| NF-32 | Reproducibility from Git | `docker compose up -d` | ✅ |
| NF-33 | Hardware cost per machine | < $100 | ⏳ (Phase 1, ~$50–85) |

### 9.5 Maintainability

| # | Requirement | Target | Status |
|---|---|---|---|
| NF-40 | Deployment without downtime | Not required for v1 | N/A |
| NF-41 | Configuration in Git (not in UI) | All configs bind-mounted | ✅ (Phase 2 hardening) |
| NF-42 | Documented runbook for common failures | After Phase 2 | ⏳ |

---

## 10. User Stories

### 10.1 Plant Manager

**US-01:** As a plant manager, I want to see my factory's OEE broken down by line, shift, and machine — so that I know which specific machines are hurting my numbers.

**US-02:** As a plant manager, I want to receive a notification when a machine goes offline — so that I know immediately when production is affected.

**US-03:** As a plant manager, I want to see historical OEE trends — so that I can validate whether a process change actually improved things.

### 10.2 Production Supervisor

**US-10:** As a supervisor, I want to see the current state of every machine in my line on one screen — so that I can quickly spot which machine needs attention.

**US-11:** As a supervisor, I want to see how long each machine has been in its current state — so that I can prioritize.

**US-12:** As a supervisor, I want to see recent fault events — so that I can investigate recurring issues.

### 10.3 Industrial Engineer

**US-20:** As an industrial engineer, I want to export raw event data as CSV or via API — so that I can analyze it in my own tools.

**US-21:** As an industrial engineer, I want to see the OEE calculation logic and validate it against manual counts — so that I can trust the numbers.

**US-22:** As an industrial engineer, I want to see breakdowns by loss category (availability, performance, quality) — so that I can prioritize improvement initiatives.

---

## 11. Risks & Mitigations

| # | Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|---|
| R-01 | **No customer interest in Phase 0 outcome** | Medium | High | LinkedIn series in progress (3 posts, 549 impressions, 5 GitHub visitors); continued outbound outreach |
| R-02 | **First customer's assumptions differ wildly from defaults** (e.g., IDLE is downtime) | High | Medium | All 20 assumptions documented and validated in first customer meeting |
| R-03 | **Hardware noise/crashes at scale** | Medium | High | Phase 1 bench testing surfaces this before pilot; opto-isolation, filtering, watchdog are pre-designed |
| R-04 | **Node-RED state loss on restart** | High | Medium | File-backed context (Phase 2 hardening) — 5-minute fix |
| R-05 | **TimescaleDB performance at 1,000 machines** | Medium | High | Load-tested at 1,000 simulated machines before Phase 6 |
| R-06 | **Customer unwilling to pay $3K-8K for pilot** | Medium | High | Price is fully justified by $900K/year invisible downtime figure; pilot can be reduced to one week's scope if needed |
| R-07 | **Competitor enters (a vendor launches a similar cheap IIoT product)** | Low | High | Domain knowledge (25 years OT/IT), garment-specific design, on-premise, low cost — competitive moats |
| R-08 | **Serial hardware failure at pilot scale** | Low | Medium | MTBF is high for ESP32-S3; spare units included in pilot BOM |
| R-09 | **IoT security incident during pilot** | Low | Critical | TLS + auth + ACLs (Phase 2 gates) mandatory before pilot goes live |
| R-10 | **Regulatory / data sovereignty issue** | Low | High | On-premise by design — no data leaves the factory, no regulatory exposure |

### 11.1 Risk that matters most

**R-01 (no customer interest)** is the existential risk. Everything else can be fixed technically. If no one wants the product, the technology is irrelevant.

**Mitigation:** The LinkedIn series is the primary go-to-market. Three posts published, 549 impressions on the best-performing post, 5 GitHub visitors, 2 deep readers. This is a "small but qualified" audience — realistic for Phase 0. Conversion to a pilot requires continued content, direct outreach to plant managers, and — critically — **a Phase 1 bench demonstration that transforms "I read your post" into "I saw your system work on a real machine."**

---

## 12. Commercial Model

### 12.1 Pricing

| Offering | What | Price (Pakistan / South Asia) |
|---|---|---|
| **Pilot (one line, 15 machines)** | 4–6 week deployment, hardware included, dashboard + data contract | **$3,000–$8,000** |
| **Scale-up (per machine)** | Hardware + software license for full factory deployment | **$150–$300/machine + $5K–$15K software** |
| **Per-line meter** (Phase 2+) | 3-phase Modbus meter on line distribution board | **~$150/line** (hardware only) |
| **Support / SLA** (optional) | Ongoing support, updates, monitoring | **$500–$2,000/month** (Phase 6+) |

### 12.2 Pilot structure

**The pilot is the core commercial vehicle.** It's structured to:
- **Minimize customer risk** — $3K–8K is small enough to justify without board approval
- **Maximize learning** — 4–6 weeks is enough to collect real data
- **Prove value clearly** — either the dashboard shows insights the customer didn't have, or it doesn't

**Pilot deliverables:**
1. Hardware installed on 15 machines (one line)
2. Full software deployment on customer's network
3. Dashboard accessible to plant manager and supervisor
4. OEE baselines for the line (first shift-level and daily-level)
5. Data export (raw events + OEE history)
6. Post-pilot report with recommended scale-up plan

**Pilot success criteria:**
- At least 90% of state changes captured within 2 seconds
- Dashboard usable by plant manager without training
- At least **one specific, actionable insight** discovered (e.g., "Machine 7 has 40 stops/shift, all between 2–3 PM")
- Customer willing to sign a scale-up contract

### 12.3 Customer acquisition strategy

| Channel | Status | Contribution |
|---|---|---|
| **LinkedIn series** | In progress (3 posts) | Awareness + inbound leads from technical audience |
| **Direct outreach** | Not started | Target 5 plant managers/week from LinkedIn search |
| **Industry groups** | Not started | Join Pakistan Apparel Forum, BGMEA, VITAS discussion groups |
| **Reference customer** | Not yet | The first pilot becomes the case study for #2–#5 |
| **Partnerships** | Not started | Sewing machine dealers (Juki, Brother, Singer) — they have relationships with factory owners |

### 12.4 Revenue projection (conservative)

| Year | Customers | Machines | Revenue |
|---|---|---|---|
| **Year 1 (2026)** | 1 pilot | 15 | $5K–$8K |
| **Year 2 (2027)** | 2–3 pilots, 1 scale-up | 15 + 100 | $20K–$40K |
| **Year 3 (2028)** | 5 customers | 500 | $100K–$150K |
| **Year 5 (2030)** | 10 customers | 2,000 | $300K–$500K |

**These are conservative estimates for a bootstrapped, solo-founder business.** They are not the numbers for a venture-backed startup — they are the numbers for a profitable small business. The product is designed for that shape.

---

## 13. Roadmap

| Phase | Timeline | Scope | Key Deliverable |
|---|---|---|---|
| **Phase 0** ✅ | Complete | Full software pipeline on simulated data | Reproducible system, data contract, 6-panel dashboard |
| **Phase 1** | Weeks 1–8 (starting now) | One ESP32-S3 + CT clamp + Modbus meter on a bench | Real hardware generating real data |
| **Phase 2** | Weeks 9–16 | Pilot line (15 machines), first customer | Validated OEE on one line, TLS + auth gates passed |
| **Phase 3** | Weeks 17–20 | OEE calculation (Python batch + lookup tables) | Availability, Performance, Quality computed |
| **Phase 4** | Weeks 21–24 | Hardening (catch nodes, file-backed context, health checks, backups) | Production-grade reliability |
| **Phase 5** | Weeks 25–32 | Line 2 + state machine migration (if needed) | Multi-line support |
| **Phase 6** | Weeks 33–44 | Factory scale (50 lines, 1,000 machines) | Load-tested, production-deployed |
| **Phase 7+** | Beyond | Predictive maintenance, vision inspection, ERP integration | Future capabilities |

### 13.1 Phase 1 — what success looks like

**Phase 1 succeeds when:**
- One real sewing machine is instrumented with ESP32-S3, CT clamp, and Modbus meter
- Real power data flows through the same pipeline as Phase 0
- Real events (buttons, fault relays) trigger real state changes
- The dashboard shows real data with no manual intervention
- The 4 design truths are proven: real current signature, noise tolerance, RTC stability, pipeline-on-real-hardware

**Phase 1 fails when:**
- The ESP32 crashes under electrical noise without a working firmware fix
- The CT clamp readings are unusable after calibration
- The pipeline requires code changes to handle real hardware (vs. simulator)

### 13.2 Phase 2 — what success looks like

**Phase 2 succeeds when:**
- A real customer's pilot line is instrumented and running
- The plant manager uses the dashboard daily
- At least one specific, actionable insight is documented
- The customer says "I want this on the whole factory"

**Phase 2 fails when:**
- The customer stops using the dashboard after week 2
- The data quality is questioned ("that's not what actually happened")
- The pilot doesn't produce any insights the customer didn't already know

---

## 14. Appendices

### 14.1 Glossary

See `data-contract-v1.0.1.md` §1 for the full glossary. Key terms:

- **OEE** — Overall Equipment Effectiveness (Availability × Performance × Quality)
- **Hypertable** — TimescaleDB's time-partitioned table
- **Continuous aggregate (CAGG)** — materialized view that refreshes on a schedule
- **MES** — Manufacturing Execution System
- **SAM** — Standard Allowed Minutes (garment industry cycle-time standard)
- **QoS** — MQTT quality of service (0 = fire-and-forget, 1 = at-least-once)
- **Hysteresis** — delay applied before confirming a state change

### 14.2 References

- `data-contract-v1.0.1.md` — frozen contract with 20 `[ASSUMPTION]` items
- `architecture-blueprint.md` — full architecture design with industrial mitigations
- `data-flow-diagram.md` — four views of the data flow with debugging reference
- `README.md` — showcase repo landing page

### 14.3 Assumption validation checklist

See `data-contract-v1.0.1.md` §14. **This is the agenda for the first customer meeting.** No Phase 2 work begins until all rows are resolved.

### 14.4 Change log

| Version | Date | Changes |
|---|---|---|
| 1.0 | 2026-11-15 | Initial PRD after Phase 0 completion. |

---

*End of PRD v1.0*
