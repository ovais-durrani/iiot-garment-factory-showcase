# Garment Factory IIoT — Data Contract v1.0.1

| Field | Value |
|---|---|
| Document ID | `DC-IIOT-001` |
| Version | `1.0.1` |
| Status | **Phase 0 — built without customer. All `[ASSUMPTION]` items unvalidated.** |
| Owner | Solutions Architect (self) |
| Last updated | 2026-11-03 |
| Related docs | `architecture-blueprint.md`, `data-flow-diagram.md` |

---

## Implementation Status

> **This contract describes the *intended* design.** Sections marked
> `[Phase 0 status]` describe features that are designed but not yet implemented
> in the Phase 0 codebase. The schema (`config/postgres/init/01_schema.sql`) is
> the ground truth for what is currently deployed.
>
> **One TimescaleDB-specific constraint shaped the schema's deduplication index.**
> See §15 for the `(event_id, time)` requirement — it is not optional, and
> getting it wrong fails silently at `CREATE INDEX` time.

---

## 0. Purpose & How to Read This Document

This contract is the **single source of truth** for:
- Every MQTT topic published or subscribed on the plant network.
- Every JSON payload shape and its required fields.
- The machine state model and allowed transitions.
- Metric definitions used in OEE and dashboards.
- Naming, timekeeping, QoS, and retention rules.

**Rule:** No device, service, or dashboard may publish or consume a payload that is not defined here. Any change requires a version bump (§11) and a Git commit.

**Rule:** Items tagged **`[ASSUMPTION]`** are educated industry defaults chosen in the absence of a customer. Each has a *Validate by* (what to check once a real factory is available) and *If wrong, impact* (what to change). Do **not** remove the tags until validated against a real line.

**Rule:** Items tagged **`[Phase 0 status]`** describe features that are designed but not yet implemented. They are part of the intended architecture, not the deployed system. See the Implementation Status note above.

---

## 1. Glossary

| Term | Meaning |
|---|---|
| **Machine** | One industrial sewing machine (the tracked asset). |
| **Line** | A group of 10–20 machines producing one garment family. |
| **Job** | One production run: a bundle of identical garments on one machine, tracked by `job_id`. |
| **Piece / Garment** | One finished item. "Job Complete" = operator signals one piece finished. |
| **State** | One of `RUNNING`, `IDLE`, `STOPPED`, `FAULT`, `OFFLINE` (§4). |
| **Event** | A discrete, timestamped, individually-valuable occurrence (job complete, fault, state change). |
| **Sample** | A continuous telemetry reading (power) at a fixed cadence. Individually disposable. |
| **Edge Device** | ESP32 (or Modbus remote I/O) at the workstation. |
| **Gateway** | The on-prem mini-PC running the full stack. |
| **System of Record** | TimescaleDB. There is no other database. |

---

## 2. Assumptions Log (READ FIRST)

Every factory-dependent decision, with its validation path. **This table is the checklist for the first customer conversation.**

### 2.1 OEE & Metric Definitions

| ID | Assumption | Default chosen | Validate by | If wrong, impact |
|---|---|---|---|---|
| A-01 | **Shift length** | `[ASSUMPTION]` Single 8-hour shift, 480 min. Two 10-min breaks + 30-min meal = **420 min planned production time**. | Ask supervisor for actual shift calendar. | OEE Availability denominator changes. Dashboard only. |
| A-02 | **Is IDLE downtime?** | `[ASSUMPTION]` **No.** IDLE (operator waiting for bundle, threading, etc.) is *not* counted as unplanned downtime for Availability. | Supervisor confirms. | If IDLE *is* downtime, Availability math and dashboards change. Data capture unaffected. |
| A-03 | **Is STOPPED downtime?** | `[ASSUMPTION]` **Yes.** STOPPED (machine off / no operator) during planned production time = unplanned downtime. | Supervisor confirms. | Availability math. |
| A-04 | **Ideal cycle time** | `[ASSUMPTION]` Per-garment-SKU constant, e.g. T-shirt = 45 s/piece. Stored in a lookup table, not in payload. | Ask industrial engineering for SAM (Standard Allowed Minutes) per SKU. | Performance metric. |
| A-05 | **Quality denominator** | `[ASSUMPTION]` `Total Count = JOB_COMPLETE events`. `Good Count = JOB_COMPLETE − rework/reject events`. Rework tracking is **out of scope for v1** (see A-12). | Confirm how rejects are recorded today. | Quality metric. v1 will report Quality ≈ 100% until reject tracking added. |
| A-06 | **Timezone** | `[ASSUMPTION]` Factory local time `Asia/Karachi` (UTC+5). All `time_bucket` OEE math uses this timezone. | Confirm factory timezone and whether it observes DST (Karachi does not). | OEE shift boundaries. |
| A-07 | **Shift boundaries** | `[ASSUMPTION]` Shifts start 08:00, 16:00, 00:00 local. | Confirm actual shift start times. | OEE daily/shift rollups. |

### 2.2 Operational Behaviour

| ID | Assumption | Default chosen | Validate by | If wrong, impact |
|---|---|---|---|---|
| A-08 | **Debounce windows** | `[ASSUMPTION]` STOP debounce **10 s**, IDLE debounce **15 s**, RUN debounce **3 s**, FAULT debounce **200 ms**. | Observe real operators for 1 day; tune. | False/true state transitions. Parameter-only change (Node-RED config). |
| A-09 | **Heartbeat interval** | `[ASSUMPTION]` **30 s**; `OFFLINE` after **60 s** no heartbeat (2 missed). | Confirm acceptable detection latency. | OFFLINE detection speed. |
| A-10 | **Power sample cadence** | `[ASSUMPTION]` **5 s** per machine. | Confirm with electrical team; 5–10 s is fine. | DB volume (see A-17). |
| A-11 | **Job granularity** | `[ASSUMPTION]` Operator presses "Job Complete" **per piece** (not per bundle). | CRITICAL — confirm with supervisor. Per-bundle would 10× fewer events. | JOB_COMPLETE volume; Performance metric definition. |
| A-12 | **Rework / reject tracking** | `[ASSUMPTION]` **Out of scope v1.** No reject button. Quality = 100% placeholder. | Confirm if rejects must be tracked in v1. | Quality metric; may need a new `REJECT` event type in v1.1. |
| A-13 | **Operator identity** | `[ASSUMPTION]` Operator logs into the machine via badge/code at shift start; `operator_id` included in events. | Confirm login mechanism (badge reader? keypad? none?). | If none, `operator_id` is `null` and attribution is manual. |
| A-14 | **Job ID source** | `[ASSUMPTION]` `job_id` is **not** auto-generated by the IIoT system; it comes from production planning (ERP/MES) and is entered/selected at the machine. | Confirm how jobs are assigned today. | If IIoT must generate jobs, scope grows significantly. |

### 2.3 Electrical & Environment

| ID | Assumption | Default chosen | Validate by | If wrong, impact |
|---|---|---|---|---|
| A-15 | **Supply voltage** | `[ASSUMPTION]` **230 V AC single-phase**, 50 Hz, per-machine. | Measure at factory. | Power calc; meter selection. |
| A-16 | **Motor type** | `[ASSUMPTION]` **Servo motor** (modern) — low inrush. Older clutch motors have high inrush. | Inspect 2–3 machines. | Noise mitigation depth (§8); meter sampling rate. |
| A-17 | **DB volume** | `[ASSUMPTION]` 1,000 machines × 1 sample/5 s ≈ **17.3M rows/day** in `power_metrics`. | N/A (self-determined). | Chunking/compression/retention sizing. |

### 2.4 Network & Security

| ID | Assumption | Default chosen | Validate by | If wrong, impact |
|---|---|---|---|---|
| A-18 | **Network model** | `[ASSUMPTION]` Flat factory LAN (10.0.0.0/16) with DHCP; gateway has static IP `10.0.0.10`. | Confirm with IT. | Device IP assignment; broker address in firmware. |
| A-19 | **No internet** | `[ASSUMPTION]` Gateway is fully offline (no cloud, no NTP to internet). Factory has a local NTP server **or** devices use RTC. | Confirm NTP availability. | Timestamp accuracy (§6). |
| A-20 | **TLS in pilot** | `[ASSUMPTION]` **Plain MQTT (1883) acceptable for lab & bench.** TLS (8883) **mandatory** before pilot line (§10). | Confirm IT security policy. | Broker config; ESP32 TLS cert provisioning. |

---

## 3. Naming Conventions

| Entity | Format | Regex | Examples |
|---|---|---|---|
| `line_id` | `L` + 2 digits | `^L[0-9]{2}$` | `L01`, `L02`, `L50` |
| `machine_id` | `{line_id}-M` + 2 digits | `^L[0-9]{2}-M[0-9]{2}$` | `L01-M05`, `L01-M17` |
| `job_id` | `JOB-` + date + seq | `^JOB-[0-9]{4}-[0-9]{5}$` | `JOB-2025-00123` |
| `operator_id` | `OP-` + 3–5 digits | `^OP-[0-9]{3,5}$` | `OP-042` |
| `event_id` | UUID v4 | standard | `550e8400-e29b-41d4-a716-446655440000` |
| `fault_code` | `E-` + 3 digits | `^E-[0-9]{3}$` | `E-102` |
| `garment_sku` | Uppercase, hyphens | `^[A-Z0-9]+(-[A-Z0-9]+)+$` | `TSHIRT-BLK-L` |
| `device_id` | `{machine_id}-ESP` | derived | `L01-M05-ESP` |

**Rules:**
- IDs are **immutable** once assigned. Never reuse.
- Never use MAC addresses, IPs, or serial numbers as primary IDs. They are metadata only.
- All IDs are **case-sensitive** and always uppercase (except UUIDs, which are lowercase per RFC 4122).

---

## 4. Machine State Model (FROZEN)

### 4.1 States

| State | Code | Meaning | Counts as OEE downtime? |
|---|---|---|---|
| Running | `RUNNING` | Machine actively sewing (current > threshold, input high). | No |
| Idle | `IDLE` | Machine powered, operator present, no active work. | No `[ASSUMPTION A-02]` |
| Stopped | `STOPPED` | Machine powered down / no operator during shift. | Yes `[ASSUMPTION A-03]` |
| Fault | `FAULT` | Active fault condition (relay asserted). | Yes |
| Offline | `OFFLINE` | No heartbeat received for > 60 s. | Treated as `STOPPED` for OEE |

### 4.2 Allowed Transitions

```
          ┌──────────────┐
          │   OFFLINE    │◄──────── heartbeat lost (60 s)
          └──────┬───────┘
                 │ heartbeat restored
                 ▼
   ┌────────► IDLE ─────────┐
   │             │           │
   │  resume     │ pause     │ fault_clear
   │  (3s)       │ (15s)     │
   │             ▼           │
RUNNING ◄──── RUNNING        │
   │             │           │
   │ stop        │ stop      │
   │ (10s)       │ (10s)     │
   ▼             ▼           ▼
STOPPED ◄──── STOPPED ◄── FAULT
   │             │           ▲
   └─────────────┴───────────┘
        (any active state → FAULT on fault relay)
```

**Transition rules (normative):**

1. `RUNNING → IDLE` requires current < `IDLE_THRESHOLD` **and** input high, continuously for `IDLE_DEBOUNCE` (15 s).
2. `RUNNING → STOPPED` requires input low **and** current < `STOP_THRESHOLD` for `STOP_DEBOUNCE` (10 s).
3. `IDLE → RUNNING` requires current > `RUN_THRESHOLD` **and** input high for `RUN_DEBOUNCE` (3 s).
4. `IDLE → STOPPED` requires input low for `STOP_DEBOUNCE` (10 s).
5. `STOPPED → IDLE` requires input high for 3 s (operator returns, machine powered).
6. `any → FAULT` on fault relay active for `FAULT_DEBOUNCE` (200 ms). **Immediate**, no other condition checked.
7. `FAULT → IDLE` only on explicit `fault_clear` (operator presses reset / fault relay deasserts for 3 s).
8. `any → OFFLINE` when no heartbeat for 60 s.
9. `OFFLINE → STOPPED` on heartbeat restored (conservative: unknown state becomes stopped until proven otherwise).
10. `JOB_COMPLETE` does **not** change state. It is an event, not a transition.

### 4.3 Thresholds (initial defaults, `[ASSUMPTION A-08]`)

| Parameter | Value | Notes |
|---|---|---|
| `RUN_THRESHOLD` | 1.0 A | ≥ 10% of typical running current |
| `IDLE_THRESHOLD` | 0.3 A | Below this = not sewing |
| `STOP_THRESHOLD` | 0.3 A | Same as idle for v1 |
| `RUN_DEBOUNCE` | 3 s | |
| `IDLE_DEBOUNCE` | 15 s | > typical fabric-adjust pause |
| `STOP_DEBOUNCE` | 10 s | > typical quick pause |
| `FAULT_DEBOUNCE` | 200 ms | |
| `HEARTBEAT_INTERVAL` | 30 s | |
| `OFFLINE_AFTER` | 60 s | 2 missed heartbeats |

---

## 5. MQTT Topic Namespace (FROZEN)

```
factory/{line_id}/machine/{machine_id}/{channel}
```

| Channel | Direction | Publisher | Subscriber | QoS | Retain | Payload |
|---|---|---|---|---|---|---|
| `power` | Device → Broker | ESP32 / meter | Telegraf | **0** | false | §6.1 |
| `event` | Device → Broker | ESP32 | Node-RED | **1** | false | §6.2–6.4 |
| `state` | Broker → All | Node-RED | Grafana/consumers | **1** | **true** | §6.5 |
| `heartbeat` | Device → Broker | ESP32 | Node-RED | 0 | false | §6.6 |
| `cmd` | Broker → Device | Consumers | ESP32 | 1 | false | §6.7 |

**Wildcards used by services:**
- Telegraf: `factory/+/machine/+/power`
- Node-RED events: `factory/+/machine/+/event`
- Node-RED heartbeats: `factory/+/machine/+/heartbeat`

**Rules:**
- **No messages outside this namespace.** No `$SYS` reliance (monitoring only, not a data path).
- `power` is QoS 0: an individual sample is disposable; losing one 5-second reading is irrelevant.
- `event` is QoS 1: every event must be delivered at least once. Deduplication is handled at the DB layer via a `(event_id, time)` UNIQUE index — **not** `event_id` alone. See §8.2 and §15.
- `state` is **retained**: a new consumer instantly gets current state without waiting for the next transition.
- LWT (Last Will and Testament) for every device: topic `factory/{line}/machine/{id}/state`, payload `{"schema_version":1,"machine_id":"...","state":"OFFLINE","state_since":"...","source":"lwt"}`. This fires instantly when a device drops TCP, before the 60 s heartbeat timeout.

---

## 6. JSON Payload Schemas

**Universal envelope rules (all payloads):**
- `schema_version` (integer) — **always present, always first-class**. Increment on any breaking change.
- `timestamp` (ISO 8601 UTC, `YYYY-MM-DDTHH:MM:SS.sssZ`) — device-side event time.
- `machine_id`, `line_id` — always present, matching §3 regex.
- `source` (string) — origin identifier (`"esp32_L01-M05"`, `"meter_schneider_01"`, `"simulator"`, `"node-red"`).

### 6.0 Timestamp policy

- Devices with RTC (DS3231) → `timestamp` = RTC time, resynced to NTP/gateway every 15 min.
- Devices without RTC → `timestamp` = last known time from gateway + monotonic uptime; accuracy ±5 s.

> **[Phase 0 status]** The `ingest_time = now()` server-side ordering column and the `clock_skew_warning: true` flag described in earlier versions of this contract are **not yet implemented**. The current schema stores `device_ts` (device time) and `time` (same device time, used for partitioning). No server-time column exists. Planned for Phase 2 hardening.

**Why device-side timestamps matter for deduplication:** see §15.

---

### 6.1 Power Sample — `factory/{line}/machine/{id}/power`

```json
{
  "schema_version": 1,
  "timestamp": "2025-01-15T10:30:05.123Z",
  "machine_id": "L01-M05",
  "line_id": "L01",
  "source": "meter_schneider_01",
  "voltage_v": 230.5,
  "current_a": 3.2,
  "power_w": 736.0,
  "energy_kwh": 0.204,
  "power_factor": 0.95,
  "frequency_hz": 50.0,
  "quality": "good"
}
```

| Field | Type | Required | Unit | Range | Notes |
|---|---|---|---|---|---|
| `schema_version` | int | ✅ | — | `1` | |
| `timestamp` | string | ✅ | ISO8601 UTC | — | Device time |
| `machine_id` | string | ✅ | — | §3 regex | |
| `line_id` | string | ✅ | — | §3 regex | |
| `source` | string | ✅ | — | — | |
| `voltage_v` | float | ✅ | V | 0–300 | RMS |
| `current_a` | float | ✅ | A | 0–50 | RMS |
| `power_w` | float | ✅ | W | 0–15000 | Real power |
| `energy_kwh` | float | ❌ | kWh | ≥0 | Cumulative, optional |
| `power_factor` | float | ❌ | — | 0–1 | |
| `frequency_hz` | float | ❌ | Hz | 45–65 | |
| `quality` | string | ✅ | — | `good` / `suspect` / `bad` | `suspect` if noise detected |

**Notes:**
- `power_w` is the *derived* real power. If the meter provides it directly, use the meter value. If ESP32 computes it, use `V × I × PF`.
- `quality = "suspect"` when any reading fails the outlier check (§8.1).
- No `payload` wrapper on power — fields are flat for Telegraf `json_v2` mapping efficiency.

---

### 6.2 Event — Job Complete — `factory/{line}/machine/{id}/event`

```json
{
  "schema_version": 1,
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2025-01-15T10:30:05.123Z",
  "machine_id": "L01-M05",
  "line_id": "L01",
  "event_type": "JOB_COMPLETE",
  "source": "esp32_L01-M05",
  "payload": {
    "job_id": "JOB-2025-00123",
    "operator_id": "OP-042",
    "garment_sku": "TSHIRT-BLK-L",
    "quantity": 1
  },
  "previous_state": "RUNNING",
  "new_state": "RUNNING"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `event_id` | string (UUID v4) | ✅ | Deduplication key. Generated by device. |
| `event_type` | string | ✅ | `"JOB_COMPLETE"` |
| `payload.job_id` | string | ✅ | From production planning `[ASSUMPTION A-14]` |
| `payload.operator_id` | string \| null | ✅ | `null` if login not implemented `[ASSUMPTION A-13]` |
| `payload.garment_sku` | string | ✅ | |
| `payload.quantity` | int | ✅ | `1` for per-piece `[ASSUMPTION A-11]` |
| `previous_state` | string | ✅ | State before event |
| `new_state` | string | ✅ | State after event (`JOB_COMPLETE` does not change state — same as previous) |

---

### 6.3 Event — Fault — `factory/{line}/machine/{id}/event`

```json
{
  "schema_version": 1,
  "event_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
  "timestamp": "2025-01-15T10:31:12.456Z",
  "machine_id": "L01-M05",
  "line_id": "L01",
  "event_type": "FAULT",
  "source": "esp32_L01-M05",
  "payload": {
    "fault_code": "E-102",
    "fault_description": "Needle break",
    "severity": "critical"
  },
  "previous_state": "RUNNING",
  "new_state": "FAULT"
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `payload.fault_code` | string | ✅ | §3 regex, from §7 code list |
| `payload.fault_description` | string | ✅ | Human-readable |
| `payload.severity` | string | ✅ | `critical` / `warning` / `info` |

---

### 6.4 Event — State Change — `factory/{line}/machine/{id}/event`

```json
{
  "schema_version": 1,
  "event_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "timestamp": "2025-01-15T10:32:00.000Z",
  "machine_id": "L01-M05",
  "line_id": "L01",
  "event_type": "STATE_CHANGE",
  "source": "node-red",
  "payload": {
    "reason": "stop_debounce",
    "duration_in_previous_state_s": 45
  },
  "previous_state": "RUNNING",
  "new_state": "STOPPED"
}
```

| `payload.reason` enum | Meaning |
|---|---|
| `run_debounce` | Debounced RUNNING |
| `idle_debounce` | Debounced IDLE |
| `stop_debounce` | Debounced STOPPED |
| `fault_relay` | Fault input asserted |
| `fault_cleared` | Fault cleared |
| `heartbeat_lost` | → OFFLINE |
| `heartbeat_restored` | OFFLINE → STOPPED |
| `manual_override` | Operator/engineer set state |

**Note:** `STATE_CHANGE` events are **generated by Node-RED**, not by devices. They are the *result* of the state machine, not raw inputs. This is the only event type with `source: "node-red"`.

---

### 6.5 State (Retained) — `factory/{line}/machine/{id}/state`

```json
{
  "schema_version": 1,
  "machine_id": "L01-M05",
  "line_id": "L01",
  "state": "RUNNING",
  "state_since": "2025-01-15T10:30:05.123Z",
  "last_event_time": "2025-01-15T10:30:05.123Z",
  "job_id": "JOB-2025-00123",
  "operator_id": "OP-042",
  "fault_code": null,
  "source": "node-red"
}
```

- Published by Node-RED on every transition.
- **Retained** so new subscribers get it immediately.
- LWT payload is identical shape with `state: "OFFLINE"` and `source: "lwt"`.

---

### 6.6 Heartbeat — `factory/{line}/machine/{id}/heartbeat`

```json
{
  "schema_version": 1,
  "timestamp": "2025-01-15T10:30:30.000Z",
  "machine_id": "L01-M05",
  "source": "esp32_L01-M05",
  "uptime_s": 3600,
  "free_heap_b": 145000,
  "rssi_dbm": -62,
  "buffered_events": 0
}
```

| Field | Type | Required | Notes |
|---|---|---|---|
| `uptime_s` | int | ❌ | For health monitoring |
| `free_heap_b` | int | ❌ | ESP32 health |
| `rssi_dbm` | int | ❌ | Wi-Fi signal |
| `buffered_events` | int | ✅ | Critical for resilience monitoring |

Every 30 s. Absence for 60 s → OFFLINE.

---

### 6.7 Command — `factory/{line}/machine/{id}/cmd`

```json
{
  "schema_version": 1,
  "command_id": "a1b2c3d4-...",
  "timestamp": "2025-01-15T10:35:00.000Z",
  "machine_id": "L01-M05",
  "command": "REBOOT",
  "payload": {}
}
```

**v1 allowed commands:** `REBOOT`, `FLUSH_BUFFER`, `SET_JOB` (optional). All are optional; the system must function with zero downlink commands. No command is required for v1 operation.

---

## 7. Fault Code List (INITIAL — `[ASSUMPTION]`)

Generic sewing-machine fault catalogue. To be replaced with the real machine control board's error codes once available.

| Code | Description | Severity | Typical cause |
|---|---|---|---|
| E-101 | Thread break | `warning` | Upper thread snapped |
| E-102 | Needle break | `critical` | Needle broken |
| E-103 | Bobbin empty | `warning` | Lower thread exhausted |
| E-104 | Motor overload | `critical` | Jam, clutch slip |
| E-105 | Motor overheat | `critical` | Continuous high load |
| E-106 | Safety guard open | `critical` | Operator safety |
| E-107 | Emergency stop pressed | `critical` | E-stop |
| E-108 | Power failure | `critical` | Supply lost |
| E-109 | Control board fault | `critical` | Electronics |
| E-110 | Unknown fault | `warning` | Relay asserted, no code |

**Validate by:** read the machine control board manual / ask maintenance for the error code table. **If wrong, impact:** only the human-readable mapping in dashboards and alert rules. Data capture unaffected (relay assertion is the signal).

---

## 8. Data Quality Rules

### 8.1 Power quality

| Rule | Condition | Action |
|---|---|---|
| Outlier | reading > 3× rolling median of last 5 samples | Discard sample; emit `quality: "suspect"` with previous value |
| Inrush | first sample after `STOPPED → RUNNING` | Flag `quality: "suspect"` for 2 s; exclude from OEE power but keep in DB |
| Stale | no power sample for 30 s while heartbeat present | `[Phase 0 status]` `POWER_STALE` alert not yet implemented — see §8.2 note |
| Negative | any of V/I/W < 0 | Set `quality: "bad"`; discard from analytics |

### 8.2 Event quality

| Rule | Condition | Action |
|---|---|---|
| Duplicate | `(event_id, time)` already in `machine_events` | `ON CONFLICT (event_id, time) DO NOTHING` — silently drop. TimescaleDB requires the unique index on a hypertable to include the partitioning column (`time`). Using `event_id` alone fails silently at `CREATE INDEX` time and only surfaces as an `ON CONFLICT` error on the first duplicate. **See §15.** |
| Clock skew | `abs(ingest_time − timestamp) > 30 s` | `[Phase 0 status]` Not yet implemented — the `ingest_time` column and `clock_skew_warning` flag are planned for Phase 2 (see §6.0) |
| Out-of-order | event `timestamp` < last event for machine | Store as-is (TimescaleDB handles); do **not** rewrite state |
| Orphan | event for unknown `machine_id` | `[Phase 0 status]` `UNKNOWN_MACHINE` alert not yet implemented. Event is stored; no alert raised. Planned for Phase 2 |
| Invalid JSON | parse failure | Log to `dead_letter` table; raise alert. `[Phase 0 status]` `dead_letter` table exists in schema, but the `parse` node's error output is currently unwired — malformed events are dropped silently. Planned for Phase 2 (see §8.3 note) |

### 8.3 `dead_letter` table

```sql
CREATE TABLE dead_letter (
  time        TIMESTAMPTZ NOT NULL DEFAULT now(),
  topic       TEXT,
  raw_payload TEXT,
  error       TEXT
);
SELECT create_hypertable('dead_letter','time', chunk_time_interval => INTERVAL '7 days');
```

> **[Phase 0 status]** The `dead_letter` table exists in the schema, but the Node-RED flow does not currently write to it. The `parse` node's output 2 (error output) is unwired — malformed MQTT payloads are dropped silently. Wiring it is a 5-minute Phase 2 hardening task once the flow is stable.

---

## 9. Retention & Storage Policy

| Table | Raw retention | Aggregated retention | Compression | Notes |
|---|---|---|---|---|
| `power_metrics` | 90 days | `power_1min`: 2 years | after 7 days | `[ASSUMPTION A-17]` |
| `machine_events` | 2 years | — | optional | Events are small; keep long |
| `machine_status` | current only | — | n/a | 1 row/machine |
| `power_latest` | current only | — | n/a | 1 row/machine |
| `dead_letter` | 30 days | — | — | For debugging |
| Mosquitto persistence | 7 days | — | — | Config: `autosave_interval 300` |

**Why 90 days raw power?** 90 days × 17.3M rows/day ≈ 1.56B rows. With compression (segmentby `machine_id`, orderby `time DESC`) expect ~10–15× compression → ~15–25 GB on disk. Acceptable for a single SSD on a mini-PC. **Validate:** actual disk usage after 2 weeks in pilot; adjust if needed.

---

## 10. Security & QoS Gates

### 10.1 Lab / Bench (Phase 0–1)
- `allow_anonymous true`, no TLS. **Acceptable.**
- Only on an isolated VLAN or standalone switch.
- No real production data.

### 10.2 Pilot Line Gate (MANDATORY before Phase 2)

These are **hard gates** — pilot line does not go live until all are met:

| # | Gate | Detail |
|---|---|---|
| G-01 | **TLS on broker** | Port 8883, Let's Encrypt or self-signed CA distributed to all devices |
| G-02 | **Per-device credentials** | Unique username/password per ESP32; password rotated on RMA |
| G-03 | **ACL** | Each device can only publish to its own `factory/{line}/machine/{id}/*` topics |
| G-04 | **Node-RED auth** | Login required for UI access |
| G-05 | **Grafana auth** | Login required; anonymous access disabled |
| G-06 | **DB auth** | No `trust` auth; strong password; localhost-only binding |
| G-07 | **SSH to gateway** | Key-only, no password, `fail2ban` |
| G-08 | **Backups** | Nightly `pg_dump` to separate disk; tested restore |

### 10.3 QoS Policy (normative)

| Channel | QoS | Rationale |
|---|---|---|
| `power` | 0 | Sample is disposable |
| `heartbeat` | 0 | Next one in 30 s anyway |
| `event` | 1 | At-least-once; dedup at DB via `(event_id, time)` |
| `state` | 1 + retain | Must reach all consumers; last value always available |
| `cmd` | 1 | Must reach device |

**Rule:** No QoS 2 anywhere. It adds handshake overhead for no benefit in this architecture (dedup is at the application layer via `(event_id, time)`).

---

## 11. Versioning Policy

### 11.1 Schema version rules

- `schema_version` is an integer per payload.
- **Breaking changes** (remove field, change type, change meaning) → **major bump** (`1 → 2`). Requires: update this document, create `data-contract-v2.md`, dual-publish during transition, update all consumers.
- **Additive changes** (new optional field) → **minor bump** in document version (`1.0 → 1.1`), `schema_version` stays `1` (additive fields are ignored by old consumers).
- **Bug fixes** (typo in description) → **patch** (`1.0.1 → 1.0.2`).

### 11.2 Topic versioning

Topics are **not** versioned. Payload `schema_version` is the versioning mechanism. This avoids topic churn.

### 11.3 Compatibility matrix

| Producer `schema_version` | Consumer must accept |
|---|---|
| 1 | `1` (ignore unknown fields) |
| 2 | `1` and `2` (during transition) |

---

## 12. Conformance Testing

Before any device joins the network, it must pass:

| Test | Method | Pass |
|---|---|---|
| Topic conformance | `mosquitto_sub -t 'factory/#' -v` | Only defined topics appear |
| Schema validation | `tools/validate_contract.py` against §6 | 100% valid |
| Naming conformance | Regex check on `machine_id`, `line_id`, `event_id` | 100% match |
| State model | Manual scripted scenarios (see `simulator/sim_machines.py` for the transitions used to test) | All transitions correct |
| QoS | `mosquitto_sub -q 1` receives every event | 0 lost in 1 h |
| Retention | New subscriber to `state` gets retained message | Immediate payload |

**Validation script:** `tools/validate_contract.py` — validates any MQTT payload against §6 schemas. No third-party dependencies (Python 3.9+ stdlib only).

---

## 13. Change Log

| Version | Date | Author | Changes |
|---|---|---|---|
| 1.0.0 | 2025-01-15 | Architect | Initial draft. All `[ASSUMPTION]` items unvalidated. |
| 1.0.1 | 2026-11-03 | Architect | Corrected §5 and §8.2: `event_id` UNIQUE → `(event_id, time)` UNIQUE (TimescaleDB constraint). Added §15 documenting the constraint. Added `[Phase 0 status]` notes to §6.0, §8.1, §8.2, §8.3 for aspirational features. Fixed §12 references (`build-plan.md` → `data-flow-diagram.md`, `test/state_scenarios.yaml` → `simulator/sim_machines.py`, `jsonschema` → `tools/validate_contract.py`). No `schema_version` bump — payload shapes unchanged. |

---

## 14. Validation Checklist (for first customer meeting)

Print this. Fill in on Day 1 of engagement. **Do not proceed past Phase 1 until all rows are resolved.**

- [ ] A-01 Shift length & breaks → _______
- [ ] A-02 Is IDLE downtime? → _______
- [ ] A-03 Is STOPPED downtime? → _______
- [ ] A-04 Ideal cycle time per SKU → _______
- [ ] A-05 How are rejects tracked today? → _______
- [ ] A-06 Timezone → _______
- [ ] A-07 Shift boundaries → _______
- [ ] A-08 Observe 5 operators, tune debounce → _______
- [ ] A-09 Heartbeat interval acceptable? → _______
- [ ] A-10 Power sample cadence → _______
- [ ] A-11 Per-piece vs per-bundle job complete → _______
- [ ] A-12 Reject tracking in v1? → _______
- [ ] A-13 Operator login mechanism → _______
- [ ] A-14 Job ID source → _______
- [ ] A-15 Supply voltage → _______
- [ ] A-16 Motor type (servo vs clutch) → _______
- [ ] A-18 Network model → _______
- [ ] A-19 NTP availability → _______
- [ ] A-20 TLS policy for pilot → _______
- [ ] §7 Fault code list (get from maintenance) → _______

---

## 15. TimescaleDB Deduplication — The `(event_id, time)` Requirement

**This is a TimescaleDB-specific constraint that is easy to miss and expensive to debug.**

PostgreSQL allows `CREATE UNIQUE INDEX ON machine_events (event_id)`. TimescaleDB **does not** — hypertables partition by `time`, and any unique index must include the partitioning column. The `CREATE UNIQUE INDEX` statement returns success but **creates nothing** at the storage layer. The first `INSERT ... ON CONFLICT (event_id)` then fails at runtime with:

```
there is no unique or exclusion constraint matching the ON CONFLICT specification
```

### The correct design

```sql
CREATE UNIQUE INDEX machine_events_event_id_time_uniq
  ON machine_events (event_id, time);
```

```sql
INSERT INTO machine_events (time, event_id, ...) VALUES ($1, $2, ...)
ON CONFLICT (event_id, time) DO NOTHING
```

### Why `time` must be the device timestamp, not `now()`

For deduplication to work, `(event_id, time)` must be **identical across retries**. That requires `time` to be the event's original device-side timestamp — not the server's `now()` when the INSERT runs:

- **Correct:** `time = payload.timestamp` — same on every retry → conflict fires → duplicate skipped
- **Wrong:** `time = new Date()` — different on every retry → no conflict → duplicate lands

This is why §6.0 mandates device-side timestamps with RTC accuracy, and why the ESP32 buffer flushes events with their **original** timestamps, not the flush time.

### Verification

```bash
docker exec iiot-timescaledb psql -U iiot -d iiot -c "\d machine_events" | grep unique
```

**Expected:**

```
"machine_events_event_id_time_uniq" UNIQUE, btree (event_id, "time")
```

If this returns nothing, the unique index does not exist — `ON CONFLICT` will fail on the first duplicate. **This is the check to run after any schema change on a hypertable.**

### Broader principle

Every TimescaleDB unique index on a hypertable must include the partitioning column. If you add more hypertables with unique constraints in future phases, apply the same rule. The failure mode is identical: `CREATE INDEX` succeeds, `INSERT` fails, and the failure only surfaces at the first duplicate — sometimes days after deployment.

---

*End of Data Contract v1.0.1*
