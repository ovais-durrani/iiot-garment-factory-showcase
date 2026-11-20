# Garment Factory IIoT Platform — System Architecture Document

| Field | Value |
|---|---|
| Document ID | `SAD-IIOT-001` |
| Version | `1.0` |
| Status | Phase 0 complete — as-built architecture |
| Owner | Ovais Durrani |
| Last updated | 2026-11-15 |
| Related docs | `prd-v1.0.md`, `data-contract-v1.0.1.md`, `architecture-blueprint.md`, `data-flow-diagram.md` |

---

## 0. Purpose & Scope

This document describes the **as-built architecture** of the IIoT platform for garment factories, reflecting the actual Phase 0 implementation (not the pre-implementation design). Where the implementation diverges from the original `architecture-blueprint.md`, this document is the source of truth.

**In scope:**
- Logical architecture (components, responsibilities, interfaces)
- Data architecture (schemas, retention, deduplication, aggregation)
- Deployment architecture (infrastructure, network, hardware)
- Security architecture (Phase 0 state, Phase 2 gates)
- Quality attributes (performance, reliability, scalability, maintainability)
- Architectural decisions (10 decisions that shaped the system)
- Known limitations and technical debt

**Out of scope:**
- Product/business requirements (see `prd-v1.0.md`)
- Payload schemas (see `data-contract-v1.0.1.md` §6)
- Deployment procedures (see Phase 2 runbook — not yet written)
- Source code (see `github.com/YOUR_USERNAME/iiot-garment-factory-showcase`)

**Audience:** Engineers maintaining the system, architects evaluating it, customers and partners evaluating technical depth, future contributors.

---

## 1. Architectural Drivers

The architecture is shaped by six drivers. Every decision in §8 traces back to one or more of these.

| # | Driver | Consequence |
|---|---|---|
| **D-1** | **1,000 machines across 50 lines** | Throughput of ~200 msg/s power + ~11 msg/s events. Stateless batched ingestion for power. Stateful per-machine processing for events. |
| **D-2** | **100% on-premise, no cloud** | No AWS/Azure/GCP. All services self-hosted. No internet dependency for core operation. |
| **D-3** | **OEE visibility must be trustworthy** | Raw facts captured exactly. Meanings (OEE) computed from raw facts, never at ingestion. Deduplication must be reliable. Timestamps must be device-side. |
| **D-4** | **Deployable by a solo engineer** | Single VM, Docker Compose, no Kubernetes. Reproducible from Git. Operational complexity budget: ~50 hours/month. |
| **D-5** | **Hardware cost < $100/machine** | ESP32-S3 + CT clamp or Modbus meter per line. Not $500 industrial MES. |
| **D-6** | **4–6 week pilot deployment** | No 6-month integration projects. Reproducible config, minimal customer IT involvement. |

**Non-driver (explicitly not optimized for):** ultra-low latency (< 1s is a goal, not a requirement), high-frequency power (> 1 msg/s per machine), machine control (read-only for v1).

---

## 2. System Context

The system is a **single-node, on-premise deployment** that lives on the factory network. It has no external cloud dependencies. Its only external interfaces are:

1. **MQTT messages from edge devices** — on `factory/{line}/machine/{id}/*` topics
2. **HTTP from human users** — Grafana dashboard on port 3000
3. **SSH from administrator** — for maintenance
4. **DNS/NTP** — optional, only for time synchronization

```
┌─────────────────────────────────────────────────────────────────┐
│                     FACTORY NETWORK (VLAN 200)                  │
│                                                                 │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐         │
│  │ ESP32-1  │  │ ESP32-2  │  │ ESP32-3  │  │   ...    │         │
│  │ Machine 1│  │ Machine 2│  │ Machine 3│  │ ESP32-1000│        │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘         │
│       │              │              │              │            │
│       └──────────────┼──────────────┼──────────────┘            │
│                      │                                          │
│                      │ MQTT (TCP 1883 or 8883)                  │
│                      ▼                                          │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │              IIoT GATEWAY VM (see §6)                     │  │
│  │                                                           │  │
│  │  ┌──────────────┐  ┌──────────┐  ┌──────────────┐         │  │
│  │  │  Mosquitto   │  │ Telegraf │  │   Node-RED   │         │  │
│  │  │  (broker)    │  │ (power)  │  │  (events)    │         │  │
│  │  └──────┬───────┘  └────┬─────┘  └──────┬───────┘         │  │
│  │         │                │                │               │  │
│  │         └────────┬───────┴────────────────┘               │  │
│  │                  │  SQL (TCP 5432)                        │  │
│  │                  ▼                                        │  │
│  │         ┌──────────────────┐                              │  │
│  │         │   TimescaleDB    │                              │  │
│  │         └────────┬─────────┘                              │  │
│  │                  │                                        │  │
│  │                  ▼                                        │  │
│  │         ┌──────────────────┐                              │  │
│  │         │     Grafana      │──── HTTP 3000 ───► Human user│  │
│  │         └──────────────────┘                              │  │
│  │                                                           │  │
│  └───────────────────────────────────────────────────────────┘  │
│                                                                 │
│  External interfaces (optional):                                │
│    - NTP server (time sync)                                     │
│    - SSH from admin VLAN (maintenance)                          │
└─────────────────────────────────────────────────────────────────┘
```

**No cloud dependencies. No internet access required. No external services.**

---

## 3. Logical Architecture

Five logical components, each with a single responsibility:

| Component | Type | Responsibility | Interface |
|---|---|---|---|
| **Mosquitto** | Container | MQTT message broker. Fan-out to subscribers. Retained message storage for state. | MQTT 3.1.1 (TCP 1883/8883) |
| **Telegraf** | Container | Power telemetry ingestion. Parse JSON, batch, write to `power_metrics`. | MQTT consumer (in), PostgreSQL (out) |
| **Node-RED** | Container | Event state machine. Hysteresis, deduplication, `machine_events` + `machine_status` writes, retained state publish, heartbeat watchdog. | MQTT in/out, PostgreSQL |
| **TimescaleDB** | Container | System of record. 6 tables (2 hypertables, 2 regular tables, 1 continuous aggregate, 1 dead letter). | PostgreSQL (TCP 5432) |
| **Grafana** | Container | Dashboard. 6 panels, 2 variables, 5s refresh. Provisioned from Git. | HTTP (TCP 3000), PostgreSQL |

### 3.1 Component responsibilities (detailed)

#### Mosquitto (message broker)

- **Role:** fan-out messaging between devices and processing services
- **Does NOT:** interpret, transform, or persist data (persistence is for offline subscribers, not system of record)
- **Topics:** 5 channels per machine: `power`, `event`, `heartbeat`, `state`, `cmd`
- **QoS:** power = 0, event = 1, state = 1 + retained, heartbeat = 0, cmd = 1
- **Phase 0:** anonymous access (isolated VLAN only)
- **Phase 2 gate:** TLS + per-device credentials + ACLs

#### Telegraf (power pipeline)

- **Role:** high-throughput stateless power telemetry ingestion
- **Input:** MQTT `factory/+/machine/+/power` (QoS 0)
- **Parser:** `json_v2` — 4 tags (machine_id, line_id, quality, source), 6 fields (voltage, current, power, energy, power_factor, frequency), 1 timestamp path
- **Output:** batched INSERT into `power_metrics` only
- **Does NOT:** touch `machine_events`, `machine_status`, or any event
- **Phase 2 gate:** add per-topic health checks

#### Node-RED (event pipeline + state machine)

- **Role:** stateful event processing with per-machine context
- **Two tabs:** Event Processing, Heartbeat Watchdog
- **State:** `global.machineStates` — one entry per machine, in-memory
- **Input:** MQTT `factory/+/machine/+/event` (QoS 1), `factory/+/machine/+/heartbeat` (QoS 0)
- **Output:** INSERT into `machine_events`, UPSERT into `machine_status`, publish `state` (retained)
- **Timers:** per-machine 60s OFFLINE watchdog
- **Known limitation:** in-memory context lost on restart (Phase 2: file-backed context)

#### TimescaleDB (system of record)

- **Role:** persist all facts, serve all queries
- **6 tables:**
  - `power_metrics` (hypertable, 1-day chunks) — raw power samples, ~17.3M rows/day at 1,000 machines
  - `power_latest` (regular, 1 row/machine) — UPSERTed by trigger on every insert
  - `power_1min` (continuous aggregate) — 1-minute rollups, refreshed every minute
  - `machine_events` (hypertable, 7-day chunks) — append-only events
  - `machine_status` (regular, 1 row/machine) — current state per machine
  - `dead_letter` (hypertable) — parse failures
- **Critical constraint:** unique index on `machine_events` must be `(event_id, time)`, not `event_id` (TimescaleDB constraint — see §8 D-4)

#### Grafana (visualization)

- **Role:** read-only dashboards, provisioned from Git
- **Datasource:** TimescaleDB (provisioned via `config/grafana/provisioning/datasources/timescale.yml`)
- **Dashboard:** 6 panels, 2 variables (line_id single, machine multi-value + repeat)
- **Refresh:** 5 seconds, all panels
- **Provisioning:** `config/grafana/provisioning/dashboards/line01-realtime.json`

---

## 4. Data Architecture

### 4.1 Tables

| Table | Type | Rows @ 1,000 machines | Growth | Retention |
|---|---|---|---|---|
| `power_metrics` | Hypertable (1-day chunks) | 17.3M/day | Linear with time | 90 days raw, 2 years aggregated |
| `power_latest` | Regular | 1,000 (constant) | None | Current only |
| `power_1min` | Continuous aggregate | 1.44M/day | Linear | 2 years |
| `machine_events` | Hypertable (7-day chunks) | ~2.85M/day | Linear | 2 years |
| `machine_status` | Regular | 1,000 (constant) | None | Current only |
| `dead_letter` | Hypertable | Near-zero (failures only) | Rare | 30 days |

### 4.2 Deduplication strategy

**The problem:** MQTT QoS 1 guarantees at-least-once delivery. Retries, network glitches, and device buffer flushes can produce duplicate events.

**The solution:** `(event_id, time)` unique index + `ON CONFLICT DO NOTHING`.

```sql
CREATE UNIQUE INDEX machine_events_event_id_time_uniq
  ON machine_events (event_id, time);
```

**Why `time` must be included:** TimescaleDB hypertables partition by `time`; unique indexes must include the partition column. A unique index on `event_id` alone is **silently rejected** at `CREATE INDEX` time (returns success, creates nothing) and only surfaces as an `ON CONFLICT` error at the first duplicate.

**Why `time` must be device timestamp:** For retries to conflict, `(event_id, time)` must be identical across retries. If `time = now()` (server time), each retry produces a different value and no conflict fires. Device timestamps are stable.

### 4.3 Continuous aggregates

`power_1min` is refreshed by TimescaleDB's background worker every 1 minute:

```sql
SELECT add_continuous_aggregate_policy('power_1min',
  start_offset => INTERVAL '1 hour',
  end_offset   => INTERVAL '1 minute',
  schedule_interval => INTERVAL '1 minute');
```

**Why continuous aggregate, not a regular materialized view:** TimescaleDB's CAGGs only process new rows per refresh (incremental), while regular matviews rebuild the entire query. At 17.3M rows/day, a full rebuild would take minutes and block queries.

### 4.4 Trigger for `power_latest`

```sql
CREATE TRIGGER trg_power_latest
AFTER INSERT ON power_metrics
FOR EACH ROW EXECUTE FUNCTION fn_update_power_latest();
```

Fires on every `power_metrics` insert, UPSERTs `power_latest`. This is **why Telegraf only writes one table** — the trigger maintains the derived table transparently. Application code doesn't know `power_latest` exists.

### 4.5 Storage sizing (at 1,000 machines, 90 days raw)

| Table | Rows | Compressed size (est.) |
|---|---|---|
| `power_metrics` (raw, 90d) | 1.56B | 15–25 GB (compression segmentby `machine_id`, orderby `time DESC`) |
| `power_1min` (2y) | ~1B | 5–10 GB |
| `machine_events` (2y) | ~2B | 10–20 GB |
| `power_latest` | 1,000 | < 1 MB |
| `machine_status` | 1,000 | < 1 MB |

**Total estimated disk usage:** ~30–55 GB. Fits comfortably on a 500 GB VMDK.

---

## 5. Deployment Architecture

### 5.1 Phase 0–4 (current): single VM

```
┌─────────────────────────────────────────────────────────────┐
│                    ESXi HOST (or laptop)                    │
│                                                             │
│  ┌───────────────────────────────────────────────────────┐  │
│  │  VM: iiot-vm-01                                       │  │
│  │  4 vCPU, 16 GB RAM, 200 GB thick SSD                  │  │
│  │                                                       │  │
│  │  Docker Compose:                                      │  │
│  │  ┌──────────┐  ┌──────────┐  ┌──────────┐             │  │
│  │  │Mosquitto │  │ Telegraf │  │ Node-RED │             │  │
│  │  └──────────┘  └──────────┘  └──────────┘             │  │
│  │  ┌──────────┐  ┌──────────┐                           │  │
│  │  │Timescale │  │ Grafana  │                           │  │
│  │  │   DB     │  │          │                           │  │
│  │  └──────────┘  └──────────┘                           │  │
│  │                                                       │  │
│  │  Volumes: pgdata, nodered_data, grafana_data,         │  │
│  │           mosquitto_data, mosquitto_log               │  │
│  └───────────────────────────────────────────────────────┘  │
│                                                             │
│  Network: VLAN 200 (IIoT isolated)                          │
│  NTP: configured on host                                    │
│  Backups: Veeam nightly + pg_dump to backup.vmdk            │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 Phase 5–6 (future): three VMs

When scale reaches ~100+ machines or HA is required:

| VM | vCPU | RAM | Disk | Services |
|---|---|---|---|---|
| **iiot-core** | 4 | 8 GB | 100 GB | Mosquitto, Telegraf, Node-RED |
| **iiot-db** | 4 | 16 GB | 500 GB (thick) | TimescaleDB, backup.vmdk |
| **iiot-vis** | 2 | 4 GB | 50 GB | Grafana |

**Migration effort:** ~2 hours (copy configs, update hostnames in 3 places: Telegraf connection string, Node-RED config node, Grafana datasource URL).

### 5.3 ESXi specifics

- **Storage:** thick-provisioned `pgdata.vmdk` (avoids thin-provisioning performance degradation as TimescaleDB writes grow)
- **vSphere HA:** enable if ≥ 2 hosts (auto-restart within 2–5 min on host failure)
- **Snapshots:** before any upgrade; delete within 24h (don't keep snapshots as backups)
- **Backups:** Veeam nightly + `pg_dump` to `backup.vmdk` nightly + monthly restore test
- **NTP:** mandatory on all VMs (`timedatectl set-ntp true`)

### 5.4 Network

- **VLAN:** dedicated IIoT VLAN (200), no corporate LAN access
- **Firewall rules:** port 1883 (MQTT), 3000 (Grafana), 22 (SSH, admin VLAN only); 5432 and 1880 not exposed externally
- **DHCP:** all ESP32s get dynamic IPs; gateway is static (`10.0.0.10`)
- **No internet access required** — fully offline operation

---

## 6. Security Architecture

### 6.1 Phase 0 state (current, lab only)

| Control | State | Acceptable for Phase 0? |
|---|---|---|
| **MQTT TLS** | ❌ Disabled | ✅ Yes (isolated VLAN) |
| **MQTT auth** | ❌ Anonymous | ✅ Yes (lab only) |
| **MQTT ACLs** | ❌ None | ✅ Yes (lab only) |
| **Node-RED auth** | ❌ Login disabled | ⚠️ Borderline — enable before any shared network |
| **Grafana auth** | ✅ Admin login | ✅ Yes |
| **Postgres auth** | ✅ Password auth | ✅ Yes |
| **SSH auth** | ✅ Key-based | ✅ Yes |
| **Backups** | ⚠️ Not yet automated | ❌ Must fix before Phase 2 |

### 6.2 Phase 2 gate (mandatory before pilot line)

These are hard gates — the pilot line does not go live until all are met:

| # | Gate | Verification |
|---|---|---|
| G-01 | TLS on MQTT broker (port 8883) | `openssl s_client -connect localhost:8883` |
| G-02 | Per-device credentials | Each ESP32 has unique username/password |
| G-03 | ACLs per device | Each device can only publish to its own topics |
| G-04 | Node-RED UI login | Password + fail2ban |
| G-05 | Grafana anonymous access disabled | `GF_AUTH_ANONYMOUS_ENABLED=false` |
| G-06 | Postgres no `trust` auth | `pg_hba.conf` shows password auth for all |
| G-07 | SSH key-only + `fail2ban` | `PasswordAuthentication no` |
| G-08 | Nightly `pg_dump` + tested restore | Restore test passes monthly |

### 6.3 Threat model (Phase 2 target)

| Threat | Mitigation |
|---|---|
| **Unauthorized device publishes fake events** | Per-device credentials + ACLs |
| **MITM on MQTT traffic** | TLS (port 8883) |
| **Compromised ESP32 publishes to wrong machine** | ACL restricts each device to its own `factory/{line}/machine/{id}/*` |
| **Attacker on factory LAN** | VLAN isolation + firewall rules |
| **Compromised database** | Strong password, localhost binding, no external 5432 exposure |
| **Ransomware via SSH** | Key-only SSH, `fail2ban`, no password auth |
| **Data loss from disk failure** | `pg_dump` to separate disk + Veeam VM backups |
| **Post-compromise data exfiltration** | No internet access from gateway — exfiltration requires physical LAN access |

**The design principle:** the system has no internet access. Compromise requires physical factory LAN access. The security model is "hard shell, soft inside" — perimeter defense (VLAN, TLS, auth) plus minimal attack surface (no web framework, no user input parsing on the gateway, read-only Grafana).

---

## 7. Quality Attributes

### 7.1 Performance

| Metric | Target | Phase 0 measured | Headroom |
|---|---|---|---|
| **Event latency** (device → dashboard) | < 2s (p99) | 14ms | 143× |
| **Dashboard load** | < 500ms | < 200ms | 2.5× |
| **Power ingestion throughput** | 200 msg/s | ~3% CPU @ 200 msg/s (simulated) | 33× |
| **Event ingestion throughput** | 11 msg/s | ~2% CPU @ 11 msg/s (simulated) | 50× |
| **Query latency (real-time panels)** | < 100ms | < 50ms | 2× |
| **Query latency (historical)** | < 1s | < 500ms | 2× |

**Bottleneck analysis:** at 1,000 machines, the projected constraints are:
1. **TimescaleDB write throughput:** ~200 inserts/s of power + ~11/s of events + triggers + CAGG. Single NVMe SSD handles this easily.
2. **Node-RED JavaScript event loop:** 11 msg/s is trivial; even at 500 events/s Node-RED handles it. The real constraint is state machine latency, not throughput.
3. **Grafana queries:** `power_latest` and `machine_status` are O(1) lookups. Historical queries use continuous aggregates.

**The architecture has 10–100× headroom at target scale.**

### 7.2 Reliability

| Attribute | Target | Phase 0 |
|---|---|---|
| **Uptime** | 99% (pilot), 99.5% (production) | Lab only |
| **Event loss** | < 1% | 0% (simulated) |
| **Duplicate events** | 0 (guaranteed by unique index) | 0 |
| **Recovery from broker restart** | < 30s | ✅ Verified |
| **Recovery from DB restart** | < 60s | ✅ Verified |
| **Recovery from Node-RED restart** | < 30s (state lost, rebuilt from events) | ⚠️ State resets |
| **Recovery from network outage (device)** | Events buffered, flushed on reconnect | ⏳ Phase 1 |
| **Recovery from full VM restart** | < 5 min | ✅ Verified |

**Known reliability gap:** Node-RED's `global.machineStates` is in-memory. On restart, state is lost and rebuilt from the next event per machine. This causes a brief window where `machine_status` shows stale state. File-backed context (Phase 2) eliminates this.

### 7.3 Scalability

| Dimension | Target | Current capacity | Scaling limit |
|---|---|---|---|
| **Machines** | 1,000 | 3 (simulated) | ~5,000 (MQTT broker) |
| **Lines** | 50 | 1 (simulated) | ~200 |
| **Messages/second** | 211 (200 power + 11 events) | 4 (simulated) | ~5,000 (Mosquitto) |
| **Historical data retention** | 90 days raw + 2 years aggregated | ~20 days | Disk-bound (~2 years) |

**Vertical scaling** (add vCPU/RAM to the VM) handles 5× growth without architecture change. **Horizontal scaling** (three VMs) handles 10× with a 2-hour migration.

### 7.4 Maintainability

| Attribute | Target | Phase 0 |
|---|---|---|
| **Reproducible from Git** | `git clone && docker compose up -d` | ✅ Verified |
| **Config changes via Git** | All configs bind-mounted | ✅ (except Node-RED runtime state) |
| **Dashboard changes via Git** | Provisioned | ✅ |
| **New machine added** | Automatic (first event creates status row) | ✅ |
| **New line added** | Configuration (new `line_id` in topics) | ✅ (no code change) |
| **New event type** | Data contract version bump + Node-RED function node change | ⏳ ~2 hours |
| **Schema migration** | Manual (documented procedure) | ⚠️ Not yet automated |

---

## 8. Architectural Decisions

These are the 10 decisions that shaped the architecture. Each documents the decision, alternatives considered, and consequences.

### D-1: Two-processor split (Telegraf + Node-RED)

**Decision:** Telegraf handles power ingestion, Node-RED handles event processing. Both subscribe independently to MQTT. Neither writes to the other's tables.

**Alternatives considered:**
- **Both through Node-RED:** Works at 3 machines, fails at 500+ (single-threaded JS saturates under power volume, state machine timers drift)
- **Both through Telegraf:** Impossible — Telegraf has no state machine, no timers, no MQTT publish
- **Both through Python:** Works, but heavier for event logic (no visual flow, more code for MQTT/DB)

**Consequences:**
- ✅ Each tool does what it's structurally best at
- ✅ Failure isolation (Node-RED crash doesn't stop power ingestion)
- ❌ Two tools to maintain instead of one
- ❌ Two codebases to review (Node-RED function nodes + Telegraf config)

**This decision is the foundation of the entire architecture.** Everything else follows from it.

### D-2: TimescaleDB dual-table strategy

**Decision:** Power data lives in `power_metrics` (hypertable, historical) and `power_latest` (regular table, current). The trigger maintains `power_latest` automatically.

**Alternatives considered:**
- **Single `power_metrics` table, query `SELECT last(...)`:** Slow at 1.7M rows/day for real-time dashboard panels
- **Redis cache:** Explicitly excluded (user constraint — no Redis)
- **Application-level cache in Node-RED:** Same problem as single table + memory overhead

**Consequences:**
- ✅ Real-time dashboards read 1,000 rows instead of scanning the hypertable
- ✅ `power_latest` is atomically consistent with `power_metrics` (trigger runs in same transaction)
- ✅ Telegraf doesn't know `power_latest` exists (single responsibility)
- ❌ Additional table + trigger to maintain
- ❌ `power_latest` is derived data — can be rebuilt from `power_metrics` if corrupted

### D-3: Single-writer-per-topic rule

**Decision:** Each MQTT topic has exactly one designated subscriber. Telegraf subscribes only to `/power`; Node-RED subscribes only to `/event` and `/heartbeat`.

**Alternatives considered:**
- **Multiple subscribers per topic:** Flexible, but leads to duplicate writes (see D-10 — this was a real bug that cost 3 days)

**Consequences:**
- ✅ No duplicate data in any table
- ✅ Each service's responsibility is unambiguous
- ✅ Debugging: "which writer?" is always answerable
- ❌ Adding a new consumer requires updating the contract and validating no overlap
- ❌ Config drift is silent (the dual-writer bug was only caught by manual counting)

**Enforcement:** documented in `data-contract-v1.0.1.md` §5. Phase 2: add CI test that fails if any service subscribes outside its designated topic.

### D-4: `(event_id, time)` unique index

**Decision:** `machine_events` has `UNIQUE INDEX ON (event_id, time)`, not `UNIQUE ON event_id`.

**Alternatives considered:**
- **UNIQUE on `event_id` only:** Silently rejected by TimescaleDB (partition column requirement)
- **Application-level dedup (SELECT then INSERT):** 2 queries per event, race conditions
- **No dedup:** Duplicates corrupt OEE numbers

**Consequences:**
- ✅ Duplicate events eliminated
- ✅ Correct behavior for retries (device timestamps stable)
- ❌ Requires `time` in the unique index (constraint of TimescaleDB)
- ❌ Requires device-side timestamps (not server time) — this is a design constraint that propagates to the ESP32 firmware

**This decision cost 3 days of debugging** and is the subject of LinkedIn Post 1.

### D-5: Device timestamps, not server timestamps

**Decision:** All events use the device's timestamp (`payload.timestamp`), not the server's `now()`.

**Alternatives considered:**
- **Server timestamps:** Easier to implement, but retries produce different timestamps, breaking dedup
- **Hybrid (server + device):** Adds a column, more complexity, no benefit for v1

**Consequences:**
- ✅ Dedup works across retries
- ✅ Events are ordered by when they actually happened, not when the server processed them
- ❌ Requires device-side RTC (DS3231) or NTP-synced ESP32
- ❌ Requires ESP32 buffer flush to preserve original timestamps (not flush time)

**This is why Phase 1 requires a DS3231 RTC.** Without it, the ESP32's clock drifts during network outages, and device timestamps become unreliable.

### D-6: Global context for state machine

**Decision:** `global.machineStates` is a single shared object in Node-RED's global context, accessed by all function nodes across both tabs.

**Alternatives considered:**
- **Node-local `context`:** Private to each function node — caused the "missing context" bug
- **Flow context:** Per-tab only — watchdog tab couldn't read event-tab state
- **Database (read/write on every event):** Would eliminate the in-memory optimization; adds ~1ms per event

**Consequences:**
- ✅ Shared across both tabs (watchdog + event processing)
- ✅ Fast in-memory access (sub-microsecond)
- ❌ Lost on Node-RED restart (Phase 2: file-backed context)
- ❌ No persistence guarantee — the DB is the durable record, memory is the fast path

### D-7: On-premise, Docker Compose, no Kubernetes

**Decision:** Single VM per factory, 5 Docker containers, `docker compose up -d`. No K8s, no cloud, no orchestration.

**Alternatives considered:**
- **Kubernetes:** Massive overkill for 5 services on one VM; 500% operational cost for 0% benefit at this scale
- **Bare-metal services:** 5× patching overhead, config drift, no reproducibility
- **Cloud deployment:** Explicitly excluded by product principle (D-2 in §1)

**Consequences:**
- ✅ `git clone && docker compose up -d` reproduces the entire system
- ✅ Version rollback = change image tag + restart
- ✅ Reproducible from Git (critical for troubleshooting)
- ❌ Single failure domain (VM down = everything down)
- ❌ Manual scaling for Phase 5+ (three VMs, not K8s)

**The tradeoff is explicit:** we accept single-VM fragility in exchange for operational simplicity. HA is Phase 5+ if needed.

### D-8: Grafana provisioning from Git

**Decision:** Dashboards, datasources, and variables are provisioned via YAML + JSON files in `config/grafana/provisioning/`. UI changes are not persisted.

**Alternatives considered:**
- **UI-configured dashboards:** Easier for ad-hoc changes, but lost on `docker compose down -v`, no version control, no review
- **Grafana HTTP API (as code):** Works, but provisioning is simpler for static dashboards
- **Terraform Grafana provider:** Overkill for a single dashboard

**Consequences:**
- ✅ Dashboards survive `down -v`
- ✅ Dashboard changes are reviewable in `git diff`
- ✅ Reproducible across environments
- ❌ UI changes don't persist (edit the JSON file, restart Grafana)
- ❌ Export process is manual (Grafana 11.2.0 sometimes hides the Export tab — use Settings → JSON model)

### D-9: Node-RED for state machine (defer Python migration)

**Decision:** The event state machine runs in Node-RED function nodes, not in a Python service.

**Alternatives considered:**
- **Python `asyncio` service (from day 1):** Better testing, better scaling, but 2–4 weeks more work in Phase 0
- **Custom Go service:** Overkill; slower iteration than Node-RED
- **Node-RED now, Python in Phase 5+:** Current decision

**Consequences:**
- ✅ Faster Phase 0 iteration (visual debugging, click-to-deploy)
- ✅ JavaScript is sufficient for 11 msg/s
- ❌ State is in-memory (lost on restart)
- ❌ No unit test framework for state machine (must be tested manually)
- ❌ Flow JSON is not reviewable in `git diff`

**Migration trigger:** state machine exceeds 200 lines of function node code, OR a state-loss incident occurs in production, OR Phase 6 scale demands it. **Not before.**

### D-10: Telegraf does NOT subscribe to events (the dual-writer bug)

**Decision:** `telegraf.conf` subscribes to `factory/+/machine/+/power` only. It never subscribes to `/event`, `/heartbeat`, or `/state`.

**What went wrong:** An earlier version had two `mqtt_consumer` blocks — one for power, one for events (leftover from an earlier design). Both Telegraf and Node-RED wrote to `machine_events`, causing duplicates that depended on millisecond-level timing.

**Consequences:**
- ✅ Single writer per table
- ✅ Silent corruption eliminated
- ❌ Config drift can reintroduce the bug (need CI enforcement in Phase 2)

**This decision is the subject of LinkedIn Post 3.**

---

## 9. Known Limitations & Technical Debt

| # | Limitation | Impact | Deferred to |
|---|---|---|---|
| L-01 | Node-RED state is in-memory | State resets on restart; machines show STOPPED until next event | Phase 2 (file-backed context) |
| L-02 | No catch node on `INSERT event` | DB failures are logged to debug panel only, not to `dead_letter` | Phase 2 (5 min fix) |
| L-03 | `parse` output 2 unwired | Malformed events silently dropped | Phase 2 (5 min fix) |
| L-04 | No CI tests for single-writer rule | Dual-writer bug can recur via config drift | Phase 2 |
| L-05 | OEE not calculated | Dashboard shows raw data; no OEE numbers | Phase 3 |
| L-06 | No TLS / auth | Acceptable on isolated VLAN; mandatory before pilot | Phase 2 (hard gate) |
| L-07 | No HA | Single VM = single failure domain | Phase 5+ (if needed) |
| L-08 | Backups manual | Risk of data loss between backups | Phase 2 (automation) |
| L-09 | No load test at 1,000 machines | Simulated at 3; real scale untested | Phase 6 |
| L-10 | Modbus meter not yet integrated | Power uses ESP32 + CT clamp (noisier, less accurate) | Phase 1 bench test |

**Debt prioritization:** L-01 through L-04 are ~1 day of work and close the biggest reliability gaps. L-05 through L-07 are customer-blocking and must be resolved before Phase 2. L-08 through L-10 are Phase 1–6 items.

---

## 10. Glossary

See `data-contract-v1.0.1.md` §1 for full glossary. Key terms:

- **Hypertable** — TimescaleDB's time-partitioned table
- **Continuous aggregate (CAGG)** — materialized view refreshed incrementally
- **UPSERT** — `INSERT ... ON CONFLICT DO UPDATE`
- **QoS** — MQTT quality of service (0, 1, 2)
- **Hysteresis** — delay before confirming a state change
- **LWT** — MQTT Last Will and Testament
- **Device timestamp** — from the device clock (RTC or NTP)
- **Server timestamp** — from the processing server's `now()` (not used for dedup)

---

## 11. References

| Document | Purpose |
|---|---|
| `prd-v1.0.md` | Product requirements, business model, roadmap |
| `data-contract-v1.0.1.md` | Payload schemas, state model, assumptions |
| `architecture-blueprint.md` | Original design (with implementation notes) |
| `data-flow-diagram.md` | Four views of data flow |
| `README.md` | Showcase repo landing page |
| `config/postgres/init/01_schema.sql` | Actual schema (source of truth) |
| `config/telegraf/telegraf.conf` | Power pipeline config |
| `config/node-red/flows.json` | Event pipeline (sanitized) |
| `config/grafana/provisioning/` | Dashboard + datasource provisioning |

---

## 12. Change Log

| Version | Date | Changes |
|---|---|---|
| 1.0 | 2026-11-15 | Initial SAD after Phase 0 completion. Reflects as-built architecture (differs from `architecture-blueprint.md` in the `(event_id, time)` dedup, schema table names, and Node-RED state model — see §8 D-4 and D-6). |

---

*End of System Architecture Document v1.0*
