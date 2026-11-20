# Garment Factory IIoT Platform — Technical Implementation Plan

| Field | Value |
|---|---|
| Document ID | `TIP-IIOT-001` |
| Version | `1.0` |
| Status | Active — Phase 1 starting |
| Owner | Ovais Durrani |
| Last updated | 2026-11-15 |
| Related docs | `prd-v1.0.md`, `sad-v1.0.md`, `data-contract-v1.0.1.md`, `architecture-blueprint.md` |

---

## 0. Purpose & Scope

This document defines **how** the IIoT platform will be built, phase by phase, from the current Phase 0 state to full factory deployment at 1,000 machines.

**In scope:**
- Work breakdown for Phases 1–6 (Phase 0 is complete — summary only)
- Task estimates, dependencies, and critical path
- Acceptance criteria and go/no-go checkpoints
- Resource requirements (time, money, skills)
- Risks and contingency plans
- Rollback procedures

**Out of scope:**
- Product requirements (see `prd-v1.0.md`)
- Architecture decisions (see `sad-v1.0.md`)
- Payload schemas (see `data-contract-v1.0.1.md`)

**Audience:** The developer (self), future contributors, potential investors evaluating execution capability.

---

## 1. Current State — Phase 0 Complete

Phase 0 delivered a fully working software pipeline on simulated data. Key facts:

| Aspect | State |
|---|---|
| **Software pipeline** | ✅ Complete — MQTT → Telegraf/Node-RED → TimescaleDB → Grafana |
| **Data contract** | ✅ Frozen at v1.0.1 with 20 `[ASSUMPTION]` items |
| **Dashboard** | ✅ 6 panels, provisioned from Git |
| **Reproducibility** | ✅ `docker compose up -d` on fresh clone |
| **Test coverage** | ⚠️ Manual (no CI tests yet) |
| **Real hardware** | ❌ None yet |
| **Customer** | ❌ None yet |
| **OEE calculation** | ❌ Not implemented |

**Phase 0 took:** ~3 weeks of focused work. **Cost:** ~$0 in hardware (all simulated).

---

## 2. Phase Overview

| Phase | Duration | Effort | Cost | Blocking Dependency |
|---|---|---|---|---|
| **Phase 0** ✅ | Complete | Done | $0 | — |
| **Phase 1** — Bench hardware | 6–8 weeks | ~120 hrs | $100–200 | Hardware arrival (1–2 wk shipping) |
| **Phase 2** — Pilot line | 6–10 weeks | ~200 hrs | $1,500–3,000 | Customer signed |
| **Phase 3** — OEE calculation | 1–2 weeks | ~40 hrs | $0 | Assumptions A-01 to A-11 validated |
| **Phase 4** — Hardening | 2 weeks | ~60 hrs | $0 | Phase 2 data collected |
| **Phase 5** — Line 2 + optional migration | 1–2 weeks | ~40 hrs | $100–200 | Phase 2 successful |
| **Phase 6** — Factory scale | 8–12 weeks | ~300 hrs | $10,000–20,000 | Phase 5 successful + customer expansion |
| **Total to Phase 6** | ~26–38 weeks | ~760 hrs | ~$12,000–23,500 | ~6–9 months |

**Effort assumption:** solo developer, ~30 hours/week. If full-time, halve the durations.

---

## 3. Phase 1 — Bench Hardware

### 3.1 Goal

**Demonstrate the full pipeline on one real sewing machine (or realistic equivalent) on a bench. The software must not change — only the `source` field in payloads, and the publisher (Python → ESP32 firmware).**

### 3.2 Duration & Effort

- **Calendar:** 6–8 weeks
- **Effort:** ~120 hours
- **Hardware delivery:** 1–2 weeks (order first, work in parallel)

### 3.3 Prerequisites

| Prerequisite | Owner | Lead time |
|---|---|---|
| Order hardware (see §5) | Ovais | 1–2 weeks shipping |
| Bench space (1m × 0.5m clear, 2 power outlets, network) | Ovais | Immediate |
| Mock load available (motor, or lamp, or borrowed machine) | Ovais | 1 week |
| Arduino IDE or ESP-IDF toolchain installed | Ovais | 1 day |
| Docker Compose stack running (Phase 0) | Ovais | ✅ Complete |

### 3.4 Work Breakdown Structure

Tasks are numbered; dependencies reference task IDs.

#### WBS-1.1 — Hardware smoke test (~4 hrs)

| # | Task | Est. | Depends on |
|---|---|---|---|
| 1.1.1 | Blink test on ESP32-S3 (confirm board works) | 30 min | Hardware arrival |
| 1.1.2 | I2C scan (confirm ADS1115 at 0x48 and DS3231 at 0x68) | 30 min | 1.1.1 |
| 1.1.3 | ADS1115 read test (1.5V battery between A0 and GND → expect ~1500 mV) | 1 hr | 1.1.2 |
| 1.1.4 | DS3231 time test (set time, disconnect power 10 min, verify time preserved) | 1 hr | 1.1.2 |
| 1.1.5 | Wi-Fi connect test (ESP32 connects, gets IP) | 30 min | 1.1.1 |
| 1.1.6 | MQTT publish test (publish "hello" to `test/topic`, verify with `mosquitto_sub`) | 1 hr | 1.1.5 |

**Exit gate:** all six tests pass. If any fails, fix before proceeding.

#### WBS-1.2 — CT clamp signal processing (~24 hrs)

This is the hardest task in Phase 1.

| # | Task | Est. | Depends on |
|---|---|---|---|
| 1.2.1 | Read raw ADS1115 samples at 860 SPS, log values, understand waveform | 4 hrs | 1.1.3 |
| 1.2.2 | Implement RMS calculation over one full AC cycle (20ms at 50Hz, 100 samples) | 6 hrs | 1.2.1 |
| 1.2.3 | Add zero-crossing detection (to align sampling window to AC phase) | 6 hrs | 1.2.2 |
| 1.2.4 | Add median filter (5-sample) + outlier rejection (>3× rolling median) | 4 hrs | 1.2.3 |
| 1.2.5 | Calibrate against Modbus meter (compare ESP32 computed power vs. meter reading) | 4 hrs | 1.2.4 + 1.3.4 |

**Exit gate:** CT clamp readings match Modbus meter within ±5% over 100 consecutive samples.

**Risk:** if RMS is noisy after filtering, fall back to Modbus meter only (skip CT clamp for Phase 1 measurement).

#### WBS-1.3 — DS3231 RTC + NTP integration (~8 hrs)

| # | Task | Est. | Depends on |
|---|---|---|---|
| 1.3.1 | Set DS3231 time from NTP on boot (with fallback if NTP unavailable) | 3 hrs | 1.1.4 |
| 1.3.2 | Read DS3231 time for every event's `timestamp` field | 2 hrs | 1.3.1 |
| 1.3.3 | Periodic resync from NTP (every 6 hours) | 2 hrs | 1.3.1 |
| 1.3.4 | Test: power cycle 3× over 24 hours, verify time drift < 2 seconds | 1 hr | 1.3.2 |

**Exit gate:** DS3231 keeps time through power cycles within ±2 seconds over 24 hours.

#### WBS-1.4 — MQTT client with reconnection (~16 hrs)

| # | Task | Est. | Depends on |
|---|---|---|---|
| 1.4.1 | MQTT client setup (PubSubClient or async-mqtt), connect to broker | 3 hrs | 1.1.6 |
| 1.4.2 | Publish power every 5s (QoS 0) with correct payload schema | 3 hrs | 1.2.5, 1.3.2 |
| 1.4.3 | Publish heartbeat every 30s (QoS 0, include `buffered_events`) | 2 hrs | 1.4.2 |
| 1.4.4 | Reconnection logic (exponential backoff, max 60s retry interval) | 4 hrs | 1.4.1 |
| 1.4.5 | LWT setup (publish OFFLINE state on device disconnect) | 2 hrs | 1.4.1 |
| 1.4.6 | Test: broker restart → device reconnects within 60s | 2 hrs | 1.4.4 |

**Exit gate:** device survives 10 consecutive broker restarts without manual intervention.

#### WBS-1.5 — Event capture (button + fault relay) (~16 hrs)

| # | Task | Est. | Depends on |
|---|---|---|---|
| 1.5.1 | Button input with 100ms debounce (interrupt-based) | 3 hrs | 1.1.1 |
| 1.5.2 | Build JOB_COMPLETE payload with UUID v4, device timestamp, machine_id, etc. | 3 hrs | 1.3.2 |
| 1.5.3 | Publish JOB_COMPLETE with QoS 1, wait for PUBACK | 3 hrs | 1.4.1 |
| 1.5.4 | Fault relay input (optically isolated), fault code mapping | 4 hrs | 1.1.1 |
| 1.5.5 | Test: press button 100 times, verify 100 events in DB, 0 duplicates | 3 hrs | 1.5.3 |

**Exit gate:** 100 button presses produce exactly 100 `machine_events` rows (no duplicates, no losses).

#### WBS-1.6 — LittleFS event buffer (~20 hrs)

| # | Task | Est. | Depends on |
|---|---|---|---|
| 1.6.1 | LittleFS initialization, mount partition | 2 hrs | 1.1.1 |
| 1.6.2 | Event serialization (JSON → byte array → file) | 3 hrs | 1.5.2 |
| 1.6.3 | Ring buffer implementation (fixed size, wrap on full, oldest eviction) | 6 hrs | 1.6.2 |
| 1.6.4 | Flush logic on reconnect (FIFO order, delete after PUBACK) | 5 hrs | 1.6.3, 1.4.4 |
| 1.6.5 | Test: disconnect network, press button 20 times, reconnect, verify all 20 events arrive at broker | 4 hrs | 1.6.4 |

**Exit gate:** network disconnect for 30 min → 20 events buffered → all 20 flushed on reconnect → 0 losses.

#### WBS-1.7 — End-to-end verification (~16 hrs)

| # | Task | Est. | Depends on |
|---|---|---|---|
| 1.7.1 | Real ESP32 → broker → Telegraf → `power_metrics` (verify in psql) | 2 hrs | 1.4.2 |
| 1.7.2 | Real ESP32 → broker → Node-RED → `machine_events` (verify in psql) | 2 hrs | 1.5.3 |
| 1.7.3 | Verify Grafana Panel 1 (Line Status) shows real machine state | 1 hr | 1.7.2 |
| 1.7.4 | Verify Grafana Panel 2 (Live Power) shows real power trend | 1 hr | 1.7.1 |
| 1.7.5 | Verify Grafana Panel 4 (State Timeline) shows real transitions | 1 hr | 1.7.2 |
| 1.7.6 | 48-hour continuous run (log every hour: uptime, free_heap, buffered_events, WiFi RSSI) | 48 hrs elapsed | 1.7.1-1.7.5 |
| 1.7.7 | Power cycle test (disconnect power, reconnect, verify time preserved, no data lost) | 2 hrs | 1.7.6 |
| 1.7.8 | Network disconnect test (unplug network 10 min, verify buffer accumulates, reconnect, verify flush) | 4 hrs | 1.7.6 |
| 1.7.9 | Real machine test (replace mock load with real sewing machine, verify current signature) | 4 hrs | 1.7.6 |

**Exit gate:** all 9 tests pass. Real machine generates recognizable current signature. 48-hour run has no crashes.

#### WBS-1.8 — Documentation (~12 hrs)

| # | Task | Est. | Depends on |
|---|---|---|---|
| 1.8.1 | Firmware README (build instructions, wiring diagram, config options) | 4 hrs | WBS-1.7 complete |
| 1.8.2 | Bench setup document (photos, wiring, calibration procedure) | 4 hrs | WBS-1.7 complete |
| 1.8.3 | Update SAD §7 (quality attributes) with measured Phase 1 results | 2 hrs | WBS-1.7 complete |
| 1.8.4 | LinkedIn Post 5 draft (lessons learned from Phase 1) | 2 hrs | WBS-1.7 complete |

### 3.5 Phase 1 Deliverables

| Deliverable | Location | Format |
|---|---|---|
| ESP32-S3 firmware | `firmware/` (new directory) | `.ino` or ESP-IDF project |
| Firmware README + wiring diagram | `firmware/README.md` | Markdown + images |
| Bench setup documentation | `docs/phase1-bench-setup.md` | Markdown + photos |
| Real data in `power_metrics` and `machine_events` | TimescaleDB | Verified via psql |
| Grafana dashboard with real data | Screenshots | PNG |
| Updated SAD | `sad-v1.0.md` §7 | Markdown |
| LinkedIn Post 5 draft | Chat draft | Markdown |

### 3.6 Phase 1 Acceptance Criteria

All 8 criteria must pass before declaring Phase 1 complete:

- [ ] **AC-1.1:** 48-hour continuous run with no ESP32 crashes (uptime ≥ 47.5 hours)
- [ ] **AC-1.2:** Power readings match Modbus meter within ±5% over 100 consecutive samples
- [ ] **AC-1.3:** 100 button presses → exactly 100 events in `machine_events` (no dupes, no losses)
- [ ] **AC-1.4:** Network disconnect for 30 min → 20 events buffered → all flushed on reconnect
- [ ] **AC-1.5:** Power cycle → DS3231 time preserved within ±2 seconds over 24 hours
- [ ] **AC-1.6:** Grafana panels 1, 2, 4 show real (not simulated) data
- [ ] **AC-1.7:** Real sewing machine current signature is recognizable (RUNNING current > 1A, IDLE < 0.3A)
- [ ] **AC-1.8:** Firmware is documented enough that a second engineer could build it

### 3.7 Go/No-Go Decision

**After 48-hour run (WBS-1.7.6):** if any of these are true, pause and fix before continuing:

| Signal | Action |
|---|---|
| ESP32 crashed during 48-hour run | Investigate crash log, fix watchdog/brown-out/power issues before continuing |
| CT clamp readings > 10% off meter | Fall back to Modbus meter only; document CT clamp limitations |
| Events lost during network disconnect | Fix LittleFS buffer; do not proceed until AC-1.4 passes |
| DS3231 time drifted > 30 seconds | Add more frequent NTP sync or replace RTC battery |

### 3.8 Rollback Plan

If Phase 1 proves unviable (e.g., CT clamp unusable, ESP32 crashes fundamentally), rollback:

1. **Stop the bench work.** Return or resell hardware (most is generic).
2. **Revert to Phase 0 state** — the simulator is untouched; the pipeline still works.
3. **Document the findings** — what failed, why, and what alternative approach would be tried next (e.g., Modbus meter only, different ESP32 variant).
4. **Delay Phase 2** until the fix is found — do NOT deploy to a customer with broken hardware.

**The Phase 0 system is never at risk.** Phase 1 work is additive — the simulator pipeline remains intact.

---

## 4. Phase 2 — Pilot Line

### 4.1 Goal

**Deploy the full system on one real customer's production line (10–20 machines). Pass all 8 security gates. Collect 4–6 weeks of real data. Produce at least one specific, actionable insight.**

### 4.2 Duration & Effort

- **Calendar:** 6–10 weeks (4–6 weeks deployment + 2 weeks data collection + 2 weeks analysis)
- **Effort:** ~200 hours
- **Revenue:** $3,000–8,000 (pilot fee)

### 4.3 Prerequisites

| Prerequisite | Owner | Lead time |
|---|---|---|
| Customer signed pilot agreement | Ovais (sales) | 4–8 weeks (ongoing LinkedIn + outreach) |
| Security gates G-01 to G-08 implemented | Ovais | 1 week |
| Hardware × 15 machines ordered | Ovais | 2–3 weeks |
| Site survey completed (network, power, machine accessibility) | Ovais + customer IT | 1 week |
| All 20 `[ASSUMPTION]` items validated | Ovais + customer | 1 day meeting |

### 4.4 Work Breakdown Structure

#### WBS-2.1 — Security hardening (~40 hrs)

| # | Task | Est. |
|---|---|---|
| 2.1.1 | Generate CA + server certificates for MQTT TLS | 2 hrs |
| 2.1.2 | Configure Mosquitto on port 8883 with TLS | 2 hrs |
| 2.1.3 | Create per-device credentials (15 usernames/passwords) | 2 hrs |
| 2.1.4 | Write ACL file (each device → only its own topics) | 4 hrs |
| 2.1.5 | Provision ESP32 firmware with per-device credentials + CA cert | 6 hrs |
| 2.1.6 | Enable Node-RED admin UI login + `fail2ban` | 2 hrs |
| 2.1.7 | Disable Grafana anonymous access | 1 hr |
| 2.1.8 | Postgres: no `trust` auth, strong password, localhost binding | 2 hrs |
| 2.1.9 | SSH: key-only, `fail2ban`, disable password auth | 2 hrs |
| 2.1.10 | Nightly `pg_dump` to backup.vmdk + monthly restore test | 4 hrs |
| 2.1.11 | Security audit: verify all 8 gates | 4 hrs |
| 2.1.12 | Test: unauthenticated publish attempt is rejected | 2 hrs |
| 2.1.13 | Test: device can only publish to its own topics | 2 hrs |
| 2.1.14 | Test: restore from backup into a fresh VM | 5 hrs |

**Exit gate:** all 8 security gates pass (§6.2 of SAD). No anonymous access anywhere.

#### WBS-2.2 — Customer onboarding (~30 hrs)

| # | Task | Est. |
|---|---|---|
| 2.2.1 | Validate all 20 `[ASSUMPTION]` items with plant manager | 4 hrs |
| 2.2.2 | Site survey: network reachability, power availability, machine models | 4 hrs |
| 2.2.3 | Agree on which 15 machines, which line | 2 hrs |
| 2.2.4 | Agree on shift definitions (A-01, A-07) | 2 hrs |
| 2.2.5 | Agree on fault code catalogue (replace placeholder E-101 to E-110) | 2 hrs |
| 2.2.6 | Agree on "Job Complete" semantics (per piece vs per bundle) | 2 hrs |
| 2.2.7 | Agree on install schedule (no production disruption) | 2 hrs |
| 2.2.8 | Sign off on pilot success criteria (what does "successful pilot" mean to them?) | 4 hrs |
| 2.2.9 | Document all agreements in `docs/pilot-agreement.md` | 4 hrs |
| 2.2.10 | Train plant manager + supervisor on dashboard basics | 4 hrs |

**Exit gate:** signed pilot agreement with success criteria, all assumptions validated, training complete.

#### WBS-2.3 — Hardware deployment (~50 hrs)

| # | Task | Est. |
|---|---|---|
| 2.3.1 | Assemble 15 ESP32 + CT clamp + enclosure units | 15 hrs |
| 2.3.2 | Pre-configure each unit (credentials, machine_id, calibration) | 8 hrs |
| 2.3.3 | Install on machines (30 min/machine × 15) | 8 hrs |
| 2.3.4 | Network setup (VLAN 200, DHCP, firewall rules) | 4 hrs |
| 2.3.5 | Gateway VM deployment (same as Phase 0, but on factory network) | 4 hrs |
| 2.3.6 | Smoke test: verify all 15 machines publishing | 4 hrs |
| 2.3.7 | Calibration: verify current/power readings match line meter | 4 hrs |
| 2.3.8 | Documentation: install log with per-machine notes | 3 hrs |

**Exit gate:** all 15 machines publishing data, visible in Grafana, within 5% of ground truth.

#### WBS-2.4 — Data collection (~6 weeks elapsed, ~20 hrs effort)

| # | Task | Est. |
|---|---|---|
| 2.4.1 | Monitor daily (check for anomalies, alert on issues) | 1 hr/week × 6 = 6 hrs |
| 2.4.2 | Weekly report to plant manager (OEE trends, anomalies) | 2 hrs/week × 6 = 12 hrs |
| 2.4.3 | Weekly data quality check (duplicate rate, capture rate, uptime) | 1 hr/week × 6 = 6 hrs |
| 2.4.4 | Fix issues as they arise | ~10 hrs total |

**Exit gate:** 4+ weeks of clean data (≥ 99% capture rate, < 0.1% duplicates).

#### WBS-2.5 — Analysis & post-pilot report (~30 hrs)

| # | Task | Est. |
|---|---|---|
| 2.5.1 | Data analysis: line OEE baseline, per-machine breakdown, time-of-day patterns | 8 hrs |
| 2.5.2 | Identify at least one specific, actionable insight (e.g., "Machine 7 has 40 stops/shift, all between 2-3 PM") | 4 hrs |
| 2.5.3 | Write post-pilot report (10-15 pages, data-driven, includes customer quotes) | 8 hrs |
| 2.5.4 | Present report to plant manager + owner | 2 hrs |
| 2.5.5 | Discuss scale-up proposal if pilot successful | 4 hrs |
| 2.5.6 | Case study draft (for use with customer #2) | 4 hrs |

**Exit gate:** report delivered, at least one specific insight documented, customer gives feedback on value.

### 4.5 Phase 2 Deliverables

| Deliverable | Purpose |
|---|---|
| **Pilot agreement** (`docs/pilot-agreement.md`) | Legal document, signed by customer |
| **Security gates documentation** (`docs/security-gates.md`) | Proof that all 8 gates pass |
| **Deployed pilot line** (15 machines) | Live system at customer |
| **Post-pilot report** | Data-driven analysis, delivered to customer |
| **Case study draft** | Marketing asset for future customers |
| **Updated SAD** | Reflect any pilot-discovered architecture changes |
| **LinkedIn case study post** | (with customer permission) |

### 4.6 Phase 2 Acceptance Criteria

- [ ] **AC-2.1:** All 8 security gates pass, verified by external audit
- [ ] **AC-2.2:** 15 machines publishing continuously for 4+ weeks
- [ ] **AC-2.3:** Data quality: ≥ 99% capture rate, < 0.1% duplicate rate
- [ ] **AC-2.4:** At least one specific, actionable insight delivered
- [ ] **AC-2.5:** Plant manager uses dashboard at least 3× per week
- [ ] **AC-2.6:** Post-pilot report delivered, customer provides feedback
- [ ] **AC-2.7:** Customer agrees to discuss scale-up (verbally or in writing)

### 4.7 Go/No-Go Decision

**After 4 weeks of data collection:** if any of these are true, consider stopping the pilot:

| Signal | Action |
|---|---|
| Capture rate < 95% | Investigate and fix before continuing; if not fixable, pilot has failed |
| Plant manager hasn't opened dashboard in 2 weeks | Product doesn't fit their workflow — interview them to understand why |
| No specific insights discovered | Data is being captured but not used — pilot has failed to produce value |
| Customer says "this doesn't help us" | Pilot has failed; capture lessons for next attempt |

**It's OK for a pilot to fail.** Failing fast is better than a failed long-term engagement. Document the lessons and use them for customer #2.

### 4.8 Rollback Plan

If the pilot fails or customer relationship breaks down:

1. **Complete the pilot fee collection** (per contract terms — usually partial payment for work done)
2. **Remove hardware** (customer keeps it per agreement, or you remove it)
3. **Leave the software running for 30 days** (customer keeps dashboard; this is part of the pilot value)
4. **Document the lessons** in `docs/pilot-lessons-<customer>.md`
5. **Return to Phase 1 state** — bench work continues, LinkedIn continues, next customer is the goal

**The architecture is not at risk.** A failed pilot is a customer/execution failure, not an architecture failure. No code should need to be reverted.

---

## 5. Phase 3 — OEE Calculation

### 5.1 Goal

**Compute and display OEE (Availability × Performance × Quality) in Grafana. Validate the numbers against manual counts from the pilot line.**

### 5.2 Duration & Effort

- **Calendar:** 1–2 weeks
- **Effort:** ~40 hours
- **Cost:** $0 (software only)

### 5.3 Prerequisites

- Phase 2 complete (4+ weeks of pilot data)
- All 20 `[ASSUMPTION]` items validated
- `sku_cycle_times` table populated (real SAM data from industrial engineering)

### 5.4 Work Breakdown Structure

| # | Task | Est. |
|---|---|---|
| 3.1 | Add `sku_cycle_times` table (garment_sku, ideal_cycle_s, updated_at) | 2 hrs |
| 3.2 | Populate with real SAM data (customer provides, or estimate from observed cycle times) | 4 hrs |
| 3.3 | Add `shifts` table (shift_id, start_time, end_time, planned_minutes) | 2 hrs |
| 3.4 | Add `oee_metrics` table (time, machine_id, line_id, shift_id, availability, performance, quality, oee, run_time_s, downtime_s, total_count, good_count) | 3 hrs |
| 3.5 | Python batch job: read `machine_events`, compute time-in-state, join to `sku_cycle_times`, write to `oee_metrics` | 12 hrs |
| 3.6 | Schedule batch job (cron or systemd timer, hourly) | 2 hrs |
| 3.7 | Grafana panel: real-time OEE gauge | 4 hrs |
| 3.8 | Grafana panel: OEE trend (last 30 days) | 4 hrs |
| 3.9 | Grafana panel: OEE by machine (table) | 4 hrs |
| 3.10 | Validation: compare computed OEE to manual count from 10 random shifts | 4 hrs |
| 3.11 | Documentation: OEE calculation methodology in data contract | 3 hrs |

### 5.5 Phase 3 Deliverables

- `sku_cycle_times` and `shifts` tables populated with real data
- `oee_metrics` table (populated hourly)
- Python batch job (`tools/oee_batch.py`)
- 3 new Grafana panels
- OEE methodology documented in `data-contract-v1.0.1.md` §2
- Validation report (computed vs manual, 10 shifts)

### 5.6 Phase 3 Acceptance Criteria

- [ ] **AC-3.1:** OEE computed for all 15 machines, per shift, for last 30 days
- [ ] **AC-3.2:** Computed OEE matches manual count within ±3% on 9/10 shifts
- [ ] **AC-3.3:** Grafana shows real-time OEE gauge + historical trend
- [ ] **AC-3.4:** Plant manager understands OEE calculation and trusts the numbers
- [ ] **AC-3.5:** OEE methodology documented

### 5.7 Go/No-Go Decision

If computed OEE is > 5% off manual count on 3+ shifts: **do not deploy OEE dashboards.** Investigate discrepancy first (likely wrong SAM data, wrong shift definitions, or missed events).

---

## 6. Phase 4 — Hardening

### 6.1 Goal

**Close the known reliability gaps identified in Phase 0. Make the system production-grade for ongoing customer use.**

### 6.2 Duration & Effort

- **Calendar:** 2 weeks
- **Effort:** ~60 hours
- **Cost:** $0

### 6.3 Work Breakdown Structure

| # | Task | Est. | Addresses |
|---|---|---|---|
| 4.1 | Wire `parse` output 2 → `dead_letter` INSERT in Node-RED | 2 hrs | SAD L-03 |
| 4.2 | Add catch nodes on `INSERT event` and `UPSERT status` (log failures) | 3 hrs | SAD L-02 |
| 4.3 | Enable file-backed context in Node-RED `settings.js` | 2 hrs | SAD L-01 |
| 4.4 | Add CI test: `tests/test_architecture.sh` (fails if Telegraf subscribes to events) | 4 hrs | SAD L-04 |
| 4.5 | Add Node-RED health check (`/health` endpoint via `node-red-contrib-healthcheck`) | 4 hrs | — |
| 4.6 | Add Grafana alert: `status_lag > 120s` (Node-RED health) | 4 hrs | — |
| 4.7 | Add alerting on `POWER_STALE` and `OFFLINE` (email or webhook) | 6 hrs | — |
| 4.8 | Automate nightly `pg_dump` + retention policy | 4 hrs | SAD L-08 |
| 4.9 | Automated restore test (monthly cron: restore to temp DB, verify schema) | 6 hrs | SAD L-08 |
| 4.10 | Load test: 1,000 simulated machines (using Phase 0 simulator scaled up) | 8 hrs | SAD L-09 |
| 4.11 | Document runbook for common failures (`docs/runbook.md`) | 8 hrs | — |
| 4.12 | Update SAD §9 (known limitations) to reflect closed gaps | 3 hrs | — |
| 4.13 | Test all Phase 4 changes on pilot line (during low-production window) | 6 hrs | — |

### 6.4 Phase 4 Deliverables

- `dead_letter` is wired (malformed events captured)
- Node-RED catch nodes log DB failures
- File-backed context (state survives restart)
- `tests/test_architecture.sh` in Git
- Health check + alerting (email/webhook)
- Automated backups + tested restore
- Load test report (1,000 simulated machines)
- `docs/runbook.md` for operational support

### 6.5 Phase 4 Acceptance Criteria

- [ ] **AC-4.1:** Malformed MQTT payload → captured in `dead_letter` (not dropped)
- [ ] **AC-4.2:** DB failure during INSERT → logged + retried (not lost)
- [ ] **AC-4.3:** Node-RED restart → state preserved (machines don't flip to STOPPED)
- [ ] **AC-4.4:** `tests/test_architecture.sh` passes on `git clone`
- [ ] **AC-4.5:** Grafana alert fires when Node-RED state is stale > 120s
- [ ] **AC-4.6:** Backup restore test completes successfully
- [ ] **AC-4.7:** Load test at 1,000 machines: < 50% CPU, < 4 GB RAM, no message loss

### 6.6 Go/No-Go Decision

If load test at 1,000 machines shows > 80% CPU or message loss, **do not proceed to Phase 6 scale.** Investigate bottleneck first (likely TimescaleDB write throughput, CAGG refresh contention, or Node-RED event loop saturation). May need to move state machine to Python earlier than planned.

---

## 7. Phase 5 — Line 2 + Optional Migration

### 7.1 Goal

**Deploy on a second production line (proving multi-line architecture). Optionally migrate state machine to Python if Node-RED is no longer sufficient.**

### 7.2 Duration & Effort

- **Calendar:** 1–2 weeks
- **Effort:** ~40 hours
- **Cost:** $100–200 (additional hardware for 15 machines)

### 7.3 Work Breakdown Structure

| # | Task | Est. | Depends on |
|---|---|---|---|
| 5.1 | Order 15 ESP32 + CT clamp units for Line 2 | 1 hr | Phase 4 complete |
| 5.2 | Site survey for Line 2 (network, power) | 2 hrs | 5.1 |
| 5.3 | Deploy hardware on Line 2 (15 machines) | 8 hrs | 5.1 arrival |
| 5.4 | Update Grafana to support two lines (already supported via `$line_id` variable) | 2 hrs | 5.3 |
| 5.5 | Verify Line 2 data flows independently of Line 1 | 2 hrs | 5.3 |
| 5.6 | **Decision point: state machine migration?** (see §7.5) | 2 hrs | 5.5 |
| 5.7 | If migrating: Python state machine service (see §7.6) | 20 hrs | 5.6 |
| 5.8 | If migrating: dual-run period (Node-RED + Python, compare outputs) | 4 hrs | 5.7 |
| 5.9 | If migrating: cut over to Python, keep Node-RED running as backup for 2 weeks | 2 hrs | 5.8 |
| 5.10 | Documentation: multi-line architecture, deployment procedure | 4 hrs | 5.5 |

### 7.4 Phase 5 Deliverables

- Line 2 fully operational (30 machines total)
- Multi-line Grafana dashboards working
- (Optional) Python state machine service
- Multi-line deployment procedure documented

### 7.5 Phase 5 Decision Point — State Machine Migration

**Migrate to Python if ANY of the following is true:**

- Node-RED state machine code exceeds 200 lines across function nodes
- A state-loss incident occurred in production (customers lost trust)
- Node-RED is hitting throughput limits (> 500 events/sec sustained)
- File-backed context is insufficient (frequent restarts needed)

**Do NOT migrate if:**

- Node-RED is working reliably
- State machine is under 200 lines
- No production incidents occurred
- Throughput has plenty of headroom (< 100 events/sec)

**The honest default: don't migrate.** Premature migration is scope creep. Let the operational history tell you if it's needed.

### 7.6 Phase 5.7 — Python Migration (if triggered)

| # | Task | Est. |
|---|---|---|
| 5.7.1 | Python project setup (`asyncpg`, `paho-mqtt`, `transitions`) | 2 hrs |
| 5.7.2 | State machine logic (port from Node-RED function nodes) | 8 hrs |
| 5.7.3 | Database writes (INSERT `machine_events`, UPSERT `machine_status`) | 4 hrs |
| 5.7.4 | Retained MQTT state publish | 2 hrs |
| 5.7.5 | Watchdog (heartbeat → OFFLINE detection) | 4 hrs |
| 5.7.6 | Deployment (Docker container, systemd, health check) | 4 hrs |
| 5.7.7 | Dual-run comparison tool (compare Node-RED vs Python outputs) | 4 hrs |
| 5.7.8 | Cutover procedure + rollback plan | 4 hrs |

**Migration effort: ~32 hours total.** Not to be done unless triggered.

### 7.7 Phase 5 Acceptance Criteria

- [ ] **AC-5.1:** Line 2 publishing data (15 new machines, 30 total)
- [ ] **AC-5.2:** Grafana dashboard shows both lines (via `$line_id` variable)
- [ ] **AC-5.3:** Line 2 data does not affect Line 1 performance or data quality
- [ ] **AC-5.4:** Multi-line deployment procedure documented
- [ ] **AC-5.5:** (If migration) Python state machine produces identical output to Node-RED over 2 weeks

---

## 8. Phase 6 — Factory Scale

### 8.1 Goal

**Deploy to the full factory (50 lines, 1,000 machines). Load test at scale. Achieve production-grade reliability and performance.**

### 8.2 Duration & Effort

- **Calendar:** 8–12 weeks
- **Effort:** ~300 hours
- **Cost:** $10,000–20,000 (additional hardware for ~970 machines + meters per line)

### 8.3 Prerequisites

- Phase 5 complete (2 lines working reliably)
- Load test at 1,000 simulated machines passed (Phase 4 WBS-4.10)
- Customer commitment to full-factory deployment
- Hardware ordered for all remaining machines

### 8.4 Work Breakdown Structure

#### WBS-6.1 — Infrastructure upgrade (~40 hrs)

| # | Task | Est. |
|---|---|---|
| 6.1.1 | Migrate from single VM to three VMs (core / db / visualization) | 6 hrs |
| 6.1.2 | Configure vSphere HA (if ≥ 2 hosts) | 4 hrs |
| 6.1.3 | Dedicated storage for `pgdata.vmdk` (thick-provisioned) | 4 hrs |
| 6.1.4 | PgBouncer setup (if connection count > 50) | 6 hrs |
| 6.1.5 | Load test on new three-VM setup | 8 hrs |
| 6.1.6 | Documentation update (SAD §5.2) | 4 hrs |
| 6.1.7 | Rollback test (revert to single VM if needed) | 8 hrs |

#### WBS-6.2 — Hardware rollout (~120 hrs)

| # | Task | Est. |
|---|---|---|
| 6.2.1 | Order ~970 ESP32 units + Modbus meters per line | 2 hrs |
| 6.2.2 | Assemble hardware (assembly line approach: 10/day for 100 days) | 100 hrs |
| 6.2.3 | Pre-configure units (script-based, 30 sec/unit) | 8 hrs |
| 6.2.4 | Deploy units (30 min/machine, in batches by line) | ~485 hrs (49 days) |
| 6.2.5 | Calibration (5 min/machine, batched) | 80 hrs |

**Note:** hardware rollout at 1,000 machines is ~600 hours (15 weeks at 40 hrs/week). This assumes a second person joins for the rollout — solo at 30 hrs/week, this becomes 20 weeks. **Recommend hiring a technician for Phase 6 rollout.**

#### WBS-6.3 — Load testing and tuning (~40 hrs)

| # | Task | Est. |
|---|---|---|
| 6.3.1 | Load test at 100, 500, 750, 1,000 machines (5 scenarios) | 8 hrs |
| 6.3.2 | Tune TimescaleDB (`shared_buffers`, `work_mem`, `max_connections`) | 8 hrs |
| 6.3.3 | Tune Mosquitto (`max_connections`, `max_inflight_messages`) | 4 hrs |
| 6.3.4 | Tune Telegraf (`metric_batch_size`, `flush_interval`) | 4 hrs |
| 6.3.5 | Grafana query optimization (continuous aggregates, indexes) | 8 hrs |
| 6.3.6 | Documentation of load test results | 4 hrs |
| 6.3.7 | Performance regression test suite | 4 hrs |

#### WBS-6.4 — Operational readiness (~40 hrs)

| # | Task | Est. |
|---|---|---|
| 6.4.1 | Monitoring: Prometheus + Grafana self-monitoring | 8 hrs |
| 6.4.2 | Alerting: escalate to on-call (email + SMS) | 4 hrs |
| 6.4.3 | Runbook: common failures (expand from Phase 4) | 8 hrs |
| 6.4.4 | Runbook: backup recovery, disaster recovery | 4 hrs |
| 6.4.5 | Capacity planning: disk, memory, CPU growth projections | 4 hrs |
| 6.4.6 | Support SLA documentation (if customer paying for support) | 4 hrs |
| 6.4.7 | Training: customer IT team on system administration | 8 hrs |

#### WBS-6.5 — Documentation and handover (~20 hrs)

| # | Task | Est. |
|---|---|---|
| 6.5.1 | Update all docs to Phase 6 state | 8 hrs |
| 6.5.2 | Final SAD revision | 4 hrs |
| 6.5.3 | Final PRD revision (actual customer metrics) | 4 hrs |
| 6.5.4 | Case study published | 4 hrs |

### 8.5 Phase 6 Deliverables

- 1,000 machines deployed and calibrated
- Three-VM architecture with HA
- Load test report (measurements at each scale)
- Operational runbook
- Monitoring + alerting
- Support SLA (if applicable)
- Case study
- Final documentation update

### 8.6 Phase 6 Acceptance Criteria

- [ ] **AC-6.1:** All 1,000 machines connected and calibrated
- [ ] **AC-6.2:** Load test at 1,000 machines: < 50% CPU, < 8 GB RAM, no message loss, < 2s p99 latency
- [ ] **AC-6.3:** Uptime over 30 days: > 99.5%
- [ ] **AC-6.4:** Data quality: capture rate ≥ 99.5%, duplicates < 0.01%
- [ ] **AC-6.5:** Alerting fires within 2 minutes of failure
- [ ] **AC-6.6:** Backup + restore tested on new infrastructure
- [ ] **AC-6.7:** Customer IT trained, runbook delivered

### 8.7 Go/No-Go Decision

**Before hardware rollout at scale (Phase 6 WBS-6.2):** if load test at 1,000 machines shows > 80% CPU or message loss, **do not proceed with hardware rollout.** Return to Phase 4 load testing, fix bottlenecks, retest.

**Hardware rollout is the point of no return.** Once 1,000 machines are deployed, changing the architecture becomes very expensive.

---

## 9. Cross-Cutting Activities

These activities happen in every phase, not as separate tasks.

### 9.1 Documentation

| Artifact | Update trigger | Owner |
|---|---|---|
| **PRD** | Phase change (customer findings, new metrics) | Ovais |
| **SAD** | Architecture change (new component, decision) | Ovais |
| **Data contract** | Schema change, new event type, assumption validated | Ovais |
| **README** | New capability, new phase | Ovais |
| **Runbook** | After every production incident | Ovais |
| **Case study** | After successful pilot | Ovais + customer |

### 9.2 Testing

| Test type | Frequency | Where |
|---|---|---|
| **Manual smoke test** | After every deployment | Bench / pilot line |
| **Contract validation** (`tools/validate_contract.py`) | Every commit | CI |
| **Architecture CI** (`tests/test_architecture.sh`) | Every commit | CI |
| **Load test** | Phase 4, Phase 6 | Simulator at scale |
| **Disaster recovery test** | Monthly | Backup restore to fresh VM |
| **Security audit** | Phase 2, annually | External (or self-assessment checklist) |

### 9.3 LinkedIn Content (parallel track)

| Post | Trigger | Purpose |
|---|---|---|
| **Post 1** ✅ | Phase 0 complete | Bug story (ON CONFLICT) |
| **Post 2** ✅ | Phase 0 complete | Architecture decision (Telegraf vs Node-RED) |
| **Post 3** ✅ | Phase 0 complete | Dual-writer bug |
| **Post 4** | Phase 0 complete | Video (dashboard demo) |
| **Post 5** | Phase 1 complete | Lessons learned from real hardware |
| **Post 6** | Phase 2 complete | Pilot line case study (with customer permission) |
| **Post 7** | Phase 3 complete | OEE calculation story |
| **Post 8+** | Milestone-based | Ongoing series |

**Content cadence:** one post every 5–7 days. Each post is a story, not an announcement. Real bugs, real lessons, real numbers.

### 9.4 Customer Communication (during Phase 2+)

| Frequency | Format | Content |
|---|---|---|
| **Weekly** | Email report | Data quality summary, any incidents, upcoming changes |
| **Monthly** | Call / meeting | OEE trends, insights, improvement suggestions |
| **Quarterly** | On-site | Full review, roadmap, feedback |

---

## 10. Resource Requirements

### 10.1 Time (by phase)

| Phase | Developer hours | Calendar (30 hrs/wk) | Calendar (40 hrs/wk) |
|---|---|---|---|
| Phase 1 | ~120 hrs | 6–8 weeks | 3–4 weeks |
| Phase 2 | ~200 hrs | 8–10 weeks | 5–6 weeks |
| Phase 3 | ~40 hrs | 1–2 weeks | 1 week |
| Phase 4 | ~60 hrs | 2 weeks | 1.5 weeks |
| Phase 5 | ~40 hrs | 1–2 weeks | 1 week |
| Phase 6 | ~300 hrs (+600 rollout) | 12–20 weeks | 8–12 weeks |
| **Total (solo, 30 hrs/wk)** | **~760 hrs** | **~30 weeks** | — |
| **Total (solo, 40 hrs/wk)** | **~760 hrs** | — | **~20 weeks** |

**With a technician for Phase 6 rollout:** adds ~600 hrs of hardware work but reduces developer time to ~300 hrs for Phase 6.

### 10.2 Money (by phase)

| Phase | Hardware | Supplies | Travel | Total |
|---|---|---|---|---|
| Phase 1 | $100–200 | $50 | $0 | **$150–250** |
| Phase 2 | $1,200–2,000 | $200 | $500–1,000 | **$1,900–3,200** |
| Phase 3 | $0 | $0 | $0 | **$0** |
| Phase 4 | $0 | $0 | $0 | **$0** |
| Phase 5 | $1,200–2,000 | $200 | $500 | **$1,900–2,700** |
| Phase 6 | $8,000–15,000 | $1,000 | $2,000 | **$11,000–18,000** |
| **Total** | — | — | — | **~$15,000–24,000** |

**Revenue assumption:** Phase 2 pilot fee $3,000–8,000. Phase 6 scale-up $50,000–150,000/year. **By end of Phase 2, the project is cash-positive on hardware costs** (pilot fee > Phase 1+2 hardware).

### 10.3 Skills Required

| Skill | Level | Notes |
|---|---|---|
| **ESP32 firmware (C++, Arduino/ESP-IDF)** | Intermediate | Learned during Phase 1 |
| **Python (asyncio, asyncpg, paho-mqtt)** | Intermediate | Phase 3+ batch jobs, optional Phase 5 migration |
| **Node-RED (function nodes, MQTT, PostgreSQL)** | Intermediate | Phase 0 built the foundation |
| **SQL (PostgreSQL, TimescaleDB)** | Intermediate | Schema design, query optimization |
| **Docker / Docker Compose** | Intermediate | 5 containers, volumes, bind mounts |
| **Linux (SSH, systemd, networking)** | Intermediate | Gateway VM, backups, monitoring |
| **Electrical (mains wiring, CT clamps)** | Basic | Mock load, MCB, terminal blocks — **careful, mains voltage** |
| **Grafana (provisioning, dashboards)** | Intermediate | Phase 0 complete |
| **LinkedIn content + customer discovery** | Intermediate | Ongoing sales |

**The stack is intentionally approachable for a solo developer.** No K8s, no microservices, no cloud. Everything runs on one VM or bench.

### 10.4 External Dependencies

| Dependency | Phase | Risk |
|---|---|---|
| **Hardware shipping (AliExpress / local)** | Phase 1, 2, 5, 6 | 1–3 week lead times; occasional stockouts |
| **Modbus meter supplier** | Phase 1 | AliExpress availability; can fall back to CT clamp only |
| **Customer commitment** | Phase 2+ | Biggest risk (no customer = no Phase 2) |
| **Customer IT cooperation (network)** | Phase 2+ | Moderate risk; some factories lock down networks |
| **Industrial engineering data (SAM)** | Phase 3 | Moderate risk; SAM data may not be maintained |

---

## 11. Timeline View

```
2026 Q4 (Oct-Dec)    2027 Q1 (Jan-Mar)    2027 Q2 (Apr-Jun)    2027 Q3 (Jul-Sep)
├─ Phase 0 ✅         ├─ Phase 2 pilot      ├─ Phase 3 OEE       ├─ Phase 6 rollout
│  (complete)         │  (deploy + collect) │  (implement)        │  (hardware at scale)
│                     │                     │                     │
├─ Phase 1 bench      ├─ Phase 4 hardening ├─ Phase 5 line 2     │
│  (6-8 weeks)        │  (2 weeks)          │  (1-2 weeks)        │
│                     │                     │                     │
└─ LinkedIn Post 5    └─ LinkedIn Post 6    └─ LinkedIn Post 7    └─ Case study
```

**Key milestones:**

| Date (target) | Milestone |
|---|---|
| **2026-12-15** | Phase 1 complete (real hardware on bench) |
| **2027-02-15** | Phase 2 pilot signed (customer commitment) |
| **2027-04-01** | Phase 2 complete (4+ weeks pilot data, report delivered) |
| **2027-04-15** | Phase 3 complete (OEE live and validated) |
| **2027-05-01** | Phase 4 complete (production-grade hardening) |
| **2027-05-15** | Phase 5 complete (Line 2 live, decision on Python migration) |
| **2027-08-01** | Phase 6 complete (1,000 machines, factory scale) |

**These are targets, not commitments.** Real-world slippage is expected, especially on customer-dependent phases (Phase 2, Phase 6).

---

## 12. Risks & Contingency

### 12.1 Phase-by-phase risk register

| # | Risk | Phase | Likelihood | Impact | Mitigation |
|---|---|---|---|---|---|
| T-01 | Hardware shipping delayed > 4 weeks | 1 | Medium | High | Order early; use local supplier for critical parts |
| T-02 | CT clamp unusable (noise, drift) | 1 | Medium | High | Fall back to Modbus meter only; CT clamp becomes secondary |
| T-03 | ESP32 crashes under electrical noise | 1 | Medium | High | Opto-isolation, ferrite beads, watchdog, separate power supply |
| T-04 | No customer interest in Phase 0 output | 2 | Medium | High | LinkedIn series continues; direct outreach; reduce pilot price |
| T-05 | Customer IT blocks network access | 2 | Medium | High | Site survey first; alternative deployment on isolated switch if needed |
| T-06 | Pilot OEE calculation disagrees with manual | 2 | High | Medium | Validate assumptions; involve industrial engineer from customer side |
| T-07 | Phase 2 pilot fails to produce insights | 2 | Medium | High | If data doesn't show insights, interview operators; may indicate wrong data source |
| T-08 | Assumptions wildly different from defaults | 2 | High | Medium | Full validation in first meeting; adjust data contract before deployment |
| T-09 | SAM data unavailable / wrong | 3 | Medium | Medium | Estimate from observed cycle times if SAM not available; validate against manual count |
| T-10 | Load test fails at 1,000 machines | 4, 6 | Low | High | Vertical scaling first; three-VM split; PgBouncer if needed; may delay Phase 6 |
| T-11 | Customer expands faster than expected | 6 | Low | Medium | Pre-order hardware; hire technician |
| T-12 | Key person (self) unavailable for 2+ weeks | Any | Medium | Medium | Document everything; Phase 0 documentation helps here |

### 12.2 Contingency plans

**If Phase 1 fails (CT clamp unusable, ESP32 unreliable):**

- Fall back to Modbus meter for all power measurement (higher cost per line but more reliable)
- Delay Phase 2 by 2–4 weeks to find alternative hardware
- Consider different ESP32 variant (P4 with Ethernet) if the S3 fundamentally cannot handle noise

**If customer says "not interested" after 2+ conversations:**

- Document why (price? complexity? competing solution? no perceived need?)
- Adjust product (price, features) based on feedback
- Target different customer segment (e.g., smaller factories, different geography)
- Consider a free pilot (customer pays only hardware cost) to reduce commitment barrier

**If pilot OEE doesn't match manual:**

- Do NOT deploy OEE dashboards. The trust loss is worse than no OEE.
- Interview customer to understand where manual and computed disagree
- Fix the discrepancy before showing OEE to the plant manager

**If load test at 1,000 machines fails:**

- Do NOT proceed with Phase 6 hardware rollout
- Move state machine to Python earlier than planned (Phase 4 instead of Phase 5)
- Consider three-VM architecture earlier (Phase 4 instead of Phase 6)
- Worst case: cap customer at 500 machines for 2027, expand in 2028

---

## 13. Definition of Done

Each phase has a Definition of Done. A phase is not complete until all its criteria pass.

### 13.1 Phase 1 — Done when:

- [ ] AC-1.1 through AC-1.8 all pass
- [ ] Firmware committed to Git and documented
- [ ] Bench setup documented with photos
- [ ] Updated SAD §7 with measured results
- [ ] LinkedIn Post 5 draft ready

### 13.2 Phase 2 — Done when:

- [ ] AC-2.1 through AC-2.7 all pass
- [ ] All 8 security gates verified
- [ ] Pilot agreement documented
- [ ] Post-pilot report delivered to customer
- [ ] Case study draft ready
- [ ] Customer willing to discuss scale-up

### 13.3 Phase 3 — Done when:

- [ ] AC-3.1 through AC-3.5 all pass
- [ ] OEE matches manual count within ±3% on 9/10 shifts
- [ ] OEE dashboards live in Grafana
- [ ] OEE methodology in data contract
- [ ] Plant manager understands and trusts numbers

### 13.4 Phase 4 — Done when:

- [ ] AC-4.1 through AC-4.7 all pass
- [ ] Load test at 1,000 simulated machines passes
- [ ] All known limitations (L-01 to L-04) closed
- [ ] Runbook written
- [ ] Backup/restore tested

### 13.5 Phase 5 — Done when:

- [ ] AC-5.1 through AC-5.5 all pass
- [ ] Line 2 operational for 2+ weeks
- [ ] Multi-line deployment procedure documented
- [ ] Migration decision made (migrate or stay on Node-RED)

### 13.6 Phase 6 — Done when:

- [ ] AC-6.1 through AC-6.7 all pass
- [ ] 1,000 machines operating for 30+ days
- [ ] Uptime 99.5%+ over 30 days
- [ ] Customer IT trained
- [ ] Case study published (with customer permission)
- [ ] Final documentation update

---

## 14. Change Log

| Version | Date | Changes |
|---|---|---|
| 1.0 | 2026-11-15 | Initial implementation plan after Phase 0 completion. Phase 1 starts immediately. |

---

*End of Technical Implementation Plan v1.0*
