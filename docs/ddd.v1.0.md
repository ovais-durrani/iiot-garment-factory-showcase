# Garment Factory IIoT Platform — Database Design Document

| Field | Value |
|---|---|
| Document ID | `DDD-IIOT-001` |
| Version | `1.0` |
| Status | Phase 0 complete — as-built schema |
| Owner | Ovais Durrani |
| Last updated | 2026-11-15 |
| Database | TimescaleDB 2.15.0 (PostgreSQL 16) |
| Related docs | `prd-v1.0.md`, `sad-v1.0.md`, `data-contract-v1.0.1.md`, `implementation-plan-v1.0.md` |

---

## 0. Purpose & Scope

This document describes the **physical database design** of the IIoT platform — every table, column, index, trigger, view, and constraint. It is the source of truth for what the database actually contains.

**In scope:**
- Entity-relationship model
- Complete schema for all 6 tables (2 hypertables, 2 regular, 1 continuous aggregate, 1 dead-letter)
- Indexes, constraints, triggers, and their rationale
- Partitioning, compression, and retention policies
- Naming conventions and data type rationale
- Common queries and their execution patterns
- Migration procedures and change management

**Out of scope:**
- Application code (see `github.com/YOUR_USERNAME/iiot-garment-factory-showcase`)
- Business logic (state machine, OEE calculation — see `data-contract-v1.0.1.md`)
- Deployment (see `sad-v1.0.md` §5)

**Audience:** Database administrators, backend engineers, contributors extending the schema, anyone debugging data issues.

---

## 1. Design Principles

Every table, index, and constraint in this schema traces back to one of these seven principles.

| # | Principle | What it means in practice |
|---|---|---|
| **P-1** | **Two classes of data, two physical designs** | High-frequency append-only time-series (hypertables) vs. low-frequency mutable current-state (regular tables). Never mix them. |
| **P-2** | **One writer per table** | `power_metrics` written only by Telegraf. `machine_events` + `machine_status` written only by Node-RED. No exceptions. |
| **P-3** | **Deduplication via unique index on device timestamp** | `(event_id, time)` unique index. `time` must be device timestamp, not server time. |
| **P-4** | **Derived tables via triggers, not application code** | `power_latest` is maintained by a PostgreSQL trigger, not by Telegraf. This guarantees transactional consistency. |
| **P-5** | **No database-side business logic** | State machine, OEE calculation, hysteresis — all in application (Node-RED or Python). The DB stores facts, not meanings. |
| **P-6** | **O(1) reads for real-time panels** | Every dashboard panel that refreshes every 5s reads a small table (`machine_status`, `power_latest`), never a hypertable. |
| **P-7** | **TimescaleDB constraints respected, not worked around** | Unique indexes must include `time`. Chunk intervals chosen for compression and query efficiency, not arbitrary. |

---

## 2. Entity-Relationship Model

The schema has 6 tables with implicit relationships (no foreign keys — see §3.6 for why).

```
                    ┌─────────────────────────┐
                    │    power_metrics        │  Raw power samples
                    │    (hypertable)         │  ~17.3M rows/day at 1,000 machines
                    │    chunk: 1 day         │  90-day retention (raw)
                    │                         │
                    │  time           (part)  │
                    │  machine_id     (tag)   │
                    │  line_id        (tag)   │
                    │  voltage_v, current_a,  │
                    │  power_w, energy_kwh,   │
                    │  power_factor, freq,    │
                    │  quality, source        │
                    └───────────┬─────────────┘
                                │
                                │ TRIGGER: trg_power_latest
                                │ (AFTER INSERT → UPSERT)
                                ▼
                    ┌─────────────────────────┐
                    │    power_latest         │  Current power per machine
                    │    (regular table)      │  1 row per machine (constant)
                    │                         │
                    │  machine_id     (PK)    │
                    │  last_power_w           │
                    │  last_current_a         │
                    │  last_power_time        │
                    └─────────────────────────┘
                    
                                ▲
                                │
                    ┌───────────┴─────────────┐
                    │    power_1min           │  1-minute rollups
                    │    (continuous agg)     │  ~1.44M rows/day at 1,000 machines
                    │                         │  2-year retention
                    │  bucket         (part)  │
                    │  machine_id     (group) │
                    │  avg_power_w, max_power_w, │
                    │  avg_current_a, max_energy_kwh │
                    └─────────────────────────┘


                    ┌─────────────────────────┐
                    │    machine_events       │  All discrete events
                    │    (hypertable)         │  ~2.85M rows/day at 1,000 machines
                    │    chunk: 7 days        │  2-year retention
                    │                         │
                    │  time           (part)  │
                    │  event_id       (UUID)  │  ◄── part of unique index
                    │  machine_id, line_id    │
                    │  event_type, source     │
                    │  payload        (JSONB) │
                    │  previous_state, new_state │
                    │  device_ts, schema_version │
                    │                         │
                    │  UNIQUE (event_id, time)│  ◄── THE critical constraint
                    └───────────┬─────────────┘
                                │
                                │ Node-RED UPSERT
                                │ (INSERT ... ON CONFLICT DO UPDATE)
                                ▼
                    ┌─────────────────────────┐
                    │    machine_status       │  Current state per machine
                    │    (regular table)      │  1 row per machine (constant)
                    │                         │
                    │  machine_id     (PK)    │
                    │  line_id                │
                    │  state, state_since     │
                    │  last_event_time        │
                    │  job_id, operator_id    │
                    │  fault_code, updated_at │
                    └─────────────────────────┘


                    ┌─────────────────────────┐
                    │    dead_letter          │  Parse failures
                    │    (hypertable)         │  Near-zero rows (failures only)
                    │    chunk: 7 days        │  30-day retention
                    │                         │
                    │  time, topic            │
                    │  raw_payload, error     │
                    └─────────────────────────┘
```

**Relationships are implicit, not enforced:**
- `power_metrics.machine_id` = `power_latest.machine_id` (aggregate → current)
- `machine_events.machine_id` = `machine_status.machine_id` (historical → current)
- `machine_events.time` = `power_metrics.time` (correlatable by time window)
- `machine_events.payload->>'job_id'` = `machine_status.job_id` (when current)

**Why no foreign keys:** see §3.6.

---

## 3. Tables

### 3.1 `power_metrics` — Raw power samples

**Purpose:** Append-only time-series of every power reading from every machine. The system of record for all power analytics.

**Type:** Hypertable, 1-day chunks.

**Schema:**

```sql
CREATE TABLE power_metrics (
  time           TIMESTAMPTZ NOT NULL,
  machine_id     TEXT NOT NULL,
  line_id        TEXT NOT NULL,
  voltage_v      DOUBLE PRECISION,
  current_a      DOUBLE PRECISION,
  power_w        DOUBLE PRECISION,
  energy_kwh     DOUBLE PRECISION,
  power_factor   DOUBLE PRECISION,
  frequency_hz   DOUBLE PRECISION,
  quality        TEXT,
  source         TEXT
);
SELECT create_hypertable('power_metrics', 'time', chunk_time_interval => INTERVAL '1 day');
CREATE INDEX ON power_metrics (machine_id, time DESC);
```

**Column rationale:**

| Column | Type | Why this type | Constraints |
|---|---|---|---|
| `time` | TIMESTAMPTZ | Device timestamp (from payload), NOT server `now()`. `TIMESTAMPTZ` handles timezone correctly. | NOT NULL — partition column, required |
| `machine_id` | TEXT | String IDs (`L01-M05`) match contract §3. Not UUID (readability, debuggability). | NOT NULL |
| `line_id` | TEXT | Denormalized from `machine_id` prefix — faster filtering without parsing. | NOT NULL |
| `voltage_v` | DOUBLE PRECISION | Float — power measurements are inherently approximate. | Nullable (some meters omit V) |
| `current_a` | DOUBLE PRECISION | Same as voltage. | Nullable |
| `power_w` | DOUBLE PRECISION | Same. | Nullable |
| `energy_kwh` | DOUBLE PRECISION | Optional cumulative counter (not all meters provide). | Nullable |
| `power_factor` | DOUBLE PRECISION | Optional (0–1). | Nullable |
| `frequency_hz` | DOUBLE PRECISION | Optional (45–65 Hz typical). | Nullable |
| `quality` | TEXT | `good` / `suspect` / `bad` (contract §6.1). | Nullable |
| `source` | TEXT | `esp32_L01-M05` / `meter_schneider_01` / `simulator` — distinguishes device vs. simulator. | Nullable |

**Why DOUBLE PRECISION, not NUMERIC:**
- Power measurements have inherent sensor noise (±1%); numeric precision beyond float64 (15 significant digits) is wasted
- Float is 4× faster for aggregations on TimescaleDB
- `NUMERIC` would be correct for financial data; power measurements aren't financial

**Row estimates:**

| Metric | At 1,000 machines |
|---|---|
| Row count (raw) | ~17.3M/day |
| Row count (90 days) | ~1.56B |
| Compressed size (90 days) | ~15–25 GB |
| Uncompressed size (90 days) | ~200 GB |

### 3.2 `power_latest` — Current power per machine

**Purpose:** Materialized "latest value" cache. Enables O(1) reads for real-time Grafana panels. Updated automatically by trigger (§5.1).

**Type:** Regular table (NOT hypertable). 1 row per machine.

**Schema:**

```sql
CREATE TABLE power_latest (
  machine_id       TEXT PRIMARY KEY,
  last_power_w     DOUBLE PRECISION,
  last_current_a   DOUBLE PRECISION,
  last_power_time  TIMESTAMPTZ
);
```

**Column rationale:**

| Column | Type | Why |
|---|---|---|
| `machine_id` | TEXT PRIMARY KEY | One row per machine. Primary key enables O(1) UPSERT. |
| `last_power_w` | DOUBLE PRECISION | The gauge value. |
| `last_current_a` | DOUBLE PRECISION | Secondary gauge value. |
| `last_power_time` | TIMESTAMPTZ | When was this sample taken? Enables staleness detection. |

**Only 4 columns — deliberately minimal.** Every column is one more value to update in the UPSERT, and one more read on every Grafana panel refresh. Only the fields real-time panels display are stored here.

**Row count:** 1,000 (constant). Never grows with time.

**Update path:** `power_metrics` INSERT → `trg_power_latest` → `INSERT ... ON CONFLICT (machine_id) DO UPDATE` on `power_latest`. Transactionally consistent.

### 3.3 `power_1min` — 1-minute power aggregates

**Purpose:** Pre-computed rollups for historical queries. Enables fast `SELECT` on "last 30 days" without scanning the full hypertable.

**Type:** Continuous aggregate (materialized view that refreshes incrementally).

**Schema:**

```sql
CREATE MATERIALIZED VIEW power_1min
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 minute', time) AS bucket,
       machine_id,
       avg(power_w)    AS avg_power_w,
       max(power_w)    AS max_power_w,
       avg(current_a)  AS avg_current_a,
       max(energy_kwh) AS max_energy_kwh
FROM power_metrics
GROUP BY bucket, machine_id
WITH NO DATA;

SELECT add_continuous_aggregate_policy('power_1min',
  start_offset => INTERVAL '1 hour',
  end_offset   => INTERVAL '1 minute',
  schedule_interval => INTERVAL '1 minute');
```

**Column rationale:**

| Column | Type | Aggregation |
|---|---|---|
| `bucket` | TIMESTAMPTZ | `time_bucket('1 minute', time)` — 1-minute boundaries |
| `machine_id` | TEXT | Grouping key |
| `avg_power_w` | DOUBLE PRECISION | Mean power (for trend) |
| `max_power_w` | DOUBLE PRECISION | Peak power (for anomaly detection) |
| `avg_current_a` | DOUBLE PRECISION | Mean current (secondary trend) |
| `max_energy_kwh` | DOUBLE PRECISION | Cumulative energy at end of minute |

**Refresh policy:**
- `start_offset = 1 hour` — process new data starting from 1 hour ago (allows late arrivals)
- `end_offset = 1 minute` — don't materialize the current minute (data still arriving)
- `schedule_interval = 1 minute` — refresh every minute

**Why continuous aggregate, not regular materialized view:** TimescaleDB CAGGs only process new rows per refresh (incremental). Regular matviews rebuild the entire query. At 17.3M rows/day, a full rebuild would take minutes and block queries.

**Row count:** 1,000 machines × 1,440 minutes/day = **1.44M rows/day**. 2-year retention = ~1B rows. Compressed size: ~5–10 GB.

### 3.4 `machine_events` — All discrete events

**Purpose:** Append-only log of every event — job completions, faults, state changes (including synthetic OFFLINE / heartbeat_restored events from the watchdog).

**Type:** Hypertable, 7-day chunks.

**Schema:**

```sql
CREATE TABLE machine_events (
  time           TIMESTAMPTZ NOT NULL,
  event_id       UUID NOT NULL,
  machine_id     TEXT NOT NULL,
  line_id        TEXT NOT NULL,
  event_type     TEXT NOT NULL,
  source         TEXT,
  payload        JSONB,
  previous_state TEXT,
  new_state      TEXT,
  device_ts      TIMESTAMPTZ,
  schema_version INT DEFAULT 1
);
SELECT create_hypertable('machine_events', 'time', chunk_time_interval => INTERVAL '7 days');
CREATE INDEX ON machine_events (machine_id, time DESC);
CREATE INDEX ON machine_events (event_type, time DESC);
CREATE UNIQUE INDEX machine_events_event_id_time_uniq
  ON machine_events (event_id, time);
```

**Column rationale:**

| Column | Type | Why |
|---|---|---|
| `time` | TIMESTAMPTZ | Device timestamp — for deduplication. NOT NULL (partition column). |
| `event_id` | UUID | UUID v4 from device or Node-RED. **Part of unique index.** |
| `machine_id` | TEXT | `L01-M05` |
| `line_id` | TEXT | Denormalized for fast filtering |
| `event_type` | TEXT | `JOB_COMPLETE` / `FAULT` / `STATE_CHANGE` / `DEVICE_RESET` |
| `source` | TEXT | `esp32_L01-M05` / `node-red` / `simulator` |
| `payload` | JSONB | Event-specific data — `{job_id, operator_id, ...}` for JOB_COMPLETE; `{fault_code, severity, ...}` for FAULT; `{reason, duration_s, ...}` for STATE_CHANGE |
| `previous_state` | TEXT | State before the event |
| `new_state` | TEXT | State after the event |
| `device_ts` | TIMESTAMPTZ | Duplicate of `time` — kept for reference (in case `time` is ever filtered/shifted) |
| `schema_version` | INT DEFAULT 1 | Payload schema version, for forward compatibility |

**The critical constraint:**

```sql
CREATE UNIQUE INDEX machine_events_event_id_time_uniq
  ON machine_events (event_id, time);
```

**Why `(event_id, time)` and not `event_id` alone:**
1. TimescaleDB hypertables partition by `time`; unique indexes must include the partitioning column
2. `CREATE UNIQUE INDEX ON machine_events (event_id)` **succeeds silently** but **creates nothing**
3. The failure surfaces only at the first `ON CONFLICT (event_id) DO NOTHING` — days after deployment
4. This cost 3 days of debugging (see LinkedIn Post 1)

**Why `time` must be device timestamp:**
For deduplication to work, `(event_id, time)` must be **identical across retries**. If `time = now()` (server time), each retry produces a different value and no conflict fires. Device timestamps are stable across retries because the ESP32 buffer preserves the original `timestamp`.

**JSONB payload advantages:**
- Event-specific fields stored without schema migration
- Queryable: `payload->>'job_id'`, `payload->>'fault_code'`
- Indexable if needed: `CREATE INDEX ON machine_events ((payload->>'fault_code'))`
- Flexible: adding a new event type doesn't require `ALTER TABLE`

**Row count:** ~2.85M/day at 1,000 machines (11 events/sec × 86,400 sec × 3 machines factoring). 2-year retention = ~2B rows. Compressed: ~10–20 GB.

### 3.5 `machine_status` — Current state per machine

**Purpose:** Materialized "current state" — updated via UPSERT by Node-RED on every event. Enables O(1) reads for real-time Grafana panels.

**Type:** Regular table. 1 row per machine.

**Schema:**

```sql
CREATE TABLE machine_status (
  machine_id      TEXT PRIMARY KEY,
  line_id         TEXT NOT NULL,
  state           TEXT NOT NULL,
  state_since     TIMESTAMPTZ NOT NULL,
  last_event_time TIMESTAMPTZ,
  last_seen       TIMESTAMPTZ,
  job_id          TEXT,
  operator_id     TEXT,
  fault_code      TEXT,
  updated_at      TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX ON machine_status (line_id, state);
```

**Column rationale:**

| Column | Type | Why |
|---|---|---|
| `machine_id` | TEXT PRIMARY KEY | One row per machine |
| `line_id` | TEXT | Denormalized for line-filtering |
| `state` | TEXT | `RUNNING` / `IDLE` / `STOPPED` / `FAULT` / `OFFLINE` |
| `state_since` | TIMESTAMPTZ | When did the current state start? Enables "how long has this been happening?" queries. |
| `last_event_time` | TIMESTAMPTZ | When was the last event for this machine? |
| `last_seen` | TIMESTAMPTZ | **Currently unused** — reserved for Phase 2 "last heartbeat received" |
| `job_id` | TEXT | Current job on this machine (from last JOB_COMPLETE) |
| `operator_id` | TEXT | Current operator (from last JOB_COMPLETE) |
| `fault_code` | TEXT | Active fault code (cleared when state != FAULT) |
| `updated_at` | TIMESTAMPTZ | When was this row last modified? (server time, differs from `state_since` which is device time) |

**The `last_seen` caveat:** this column exists in the schema but is **never written** by the current Node-RED flow. It was reserved for "last heartbeat received" but the current watchdog doesn't update it. **Live query warnings:**
- ❌ Don't query `last_seen` for freshness — it's always NULL
- ✅ Use `power_latest.last_power_time` or `power_metrics.max(time)` as freshness proxy
- ✅ Use `updated_at` for "last event" freshness (set on every UPSERT)

**Phase 2 cleanup:** either remove `last_seen` or wire it up in the watchdog.

**Row count:** 1,000 (constant). Never grows with time.

**Update path:** Node-RED `build status upsert` → `INSERT ... ON CONFLICT (machine_id) DO UPDATE` on every event.

### 3.6 `dead_letter` — Parse failures

**Purpose:** Capture malformed events, so failures are visible instead of silently dropped.

**Type:** Hypertable, 7-day chunks.

**Schema:**

```sql
CREATE TABLE dead_letter (
  time        TIMESTAMPTZ NOT NULL DEFAULT now(),
  topic       TEXT,
  raw_payload TEXT,
  error       TEXT
);
SELECT create_hypertable('dead_letter', 'time', chunk_time_interval => INTERVAL '7 days');
```

**Column rationale:**

| Column | Type | Why |
|---|---|---|
| `time` | TIMESTAMPTZ | Server time — when the error was detected |
| `topic` | TEXT | Which MQTT topic the payload came from |
| `raw_payload` | TEXT | The raw bytes (preserves the original for debugging) |
| `error` | TEXT | The error message (from `JSON.parse()` or schema validation) |

**Status:** the table exists, but the Node-RED flow does not yet write to it (parse node's output 2 is unwired). **Phase 4 hardening task.**

**Row count:** near-zero (only when malformed payloads arrive). 30-day retention.

### 3.7 Why no foreign keys

None of the tables declare FK relationships, despite the implicit relationships (machine_id, line_id, etc.).

**Why:**

1. **TimescaleDB + FK performance:** foreign keys on hypertables add write overhead on every insert (which is the hot path — 200 inserts/sec at 1,000 machines). The check is unnecessary because the writer logic is centralized.

2. **The single-writer rule makes FKs redundant:** `power_metrics` is written only by Telegraf. `machine_events` is written only by Node-RED. If a machine_id is malformed, the writer's own validation (and the data contract) catches it — the FK check on every insert is overkill.

3. **Partial data is intentional:** a `power_metrics` row for `L01-M07` might arrive before any `machine_events` row for that machine. FKs would reject it. In practice, we want all data to land — the contract validator (`tools/validate_contract.py`) enforces format, not referential integrity.

4. **TimescaleDB + FK complexity:** adding FKs to hypertables requires careful ordering (parent tables must exist first), and FK constraints can interfere with compression. Not worth the complexity for a schema that's already structurally clean.

**Trade-off accepted:** referential integrity is enforced at the application layer (device firmware uses validated machine_id from config; Node-RED trusts device-supplied machine_id only after contract validation). No DB-level safety net, but no DB-level performance cost either.

---

## 4. Indexes

### 4.1 Index inventory

| Index | Table | Columns | Purpose |
|---|---|---|---|
| `power_metrics_pkey` | `power_metrics` | (implicit, none) | Hypertables don't have explicit PKs |
| `power_metrics_machine_id_time_idx` | `power_metrics` | `(machine_id, time DESC)` | Per-machine time-range queries (Grafana Panel 2) |
| `power_latest_pkey` | `power_latest` | `(machine_id)` PRIMARY KEY | One row per machine; enables O(1) UPSERT |
| `power_1min` (implicit) | `power_1min` | CAGG internal | Auto-maintained by TimescaleDB |
| `machine_events_machine_id_time_idx` | `machine_events` | `(machine_id, time DESC)` | Per-machine event history |
| `machine_events_event_type_time_idx` | `machine_events` | `(event_type, time DESC)` | Type-specific queries (e.g., "all FAULT events today") |
| `machine_events_event_id_time_uniq` | `machine_events` | `(event_id, time)` **UNIQUE** | **Deduplication** — the critical constraint |
| `machine_status_pkey` | `machine_status` | `(machine_id)` PRIMARY KEY | One row per machine |
| `machine_status_line_id_state_idx` | `machine_status` | `(line_id, state)` | Line-wide status queries (Grafana Panel 1) |
| `dead_letter_time_idx` | `dead_letter` | (implicit) | Hypertable default |

### 4.2 Index design rationale

**`(machine_id, time DESC)` on `power_metrics` and `machine_events`:**
- Most common query pattern: `WHERE machine_id = X AND time > now() - interval 'Nh'`
- `machine_id` first (equality filter) → narrows index range quickly
- `time DESC` second (range filter) → enables efficient backward scan for "most recent N"
- Without this index, the query would scan the entire chunk.

**`(event_type, time DESC)` on `machine_events`:**
- Queries like "all FAULT events today" (Grafana alerting, analysis)
- Event types have low cardinality (5–6 values) but high filtering benefit
- `time DESC` because queries almost always filter by time window

**`(event_id, time)` UNIQUE on `machine_events`:**
- **Deduplication is the ONLY reason this exists.**
- The unique index is required by `ON CONFLICT (event_id, time) DO NOTHING`
- TimescaleDB rejects `UNIQUE (event_id)` alone (partition column requirement)
- Failure mode: **silent** at `CREATE INDEX` time; loud at first `ON CONFLICT`

**`(line_id, state)` on `machine_status`:**
- Grafana Panel 1 filters by `line_id` (all machines on a line)
- `state` in the same index enables `WHERE line_id = X AND state = 'FAULT'` without a second lookup
- Small table (~1,000 rows), so index is fast regardless, but composite helps dashboards

**`(machine_id)` PK on `power_latest` and `machine_status`:**
- Primary key = unique row + O(1) UPSERT target
- `INSERT ... ON CONFLICT (machine_id) DO UPDATE` uses this index
- Without it, UPSERT would be a full table scan (catastrophic at scale)

### 4.3 Indexes NOT added (and why)

| Considered | Not added because |
|---|---|
| **`(time)` alone on `power_metrics`** | TimescaleDB's chunk-level index already covers time-range queries. Redundant. |
| **`(source)` on any table** | Source filters are rare and low-cardinality. Full scan is fine. |
| **`(payload->>'job_id')` on `machine_events`** | Job-specific queries are rare in Phase 0. Add in Phase 3 if needed for OEE. |
| **`(quality)` on `power_metrics`** | Quality filters are diagnostic, not dashboard-driven. Full scan is fine. |
| **`(updated_at)` on `machine_status`** | Freshness queries use `power_latest.last_power_time` instead. |

---

## 5. Triggers

### 5.1 `trg_power_latest` — Automatic latest-value maintenance

**Purpose:** Keep `power_latest` in sync with `power_metrics` on every insert, transactionally.

**Definition:**

```sql
CREATE OR REPLACE FUNCTION fn_update_power_latest() RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO power_latest (machine_id, last_power_w, last_current_a, last_power_time)
  VALUES (NEW.machine_id, NEW.power_w, NEW.current_a, NEW.time)
  ON CONFLICT (machine_id) DO UPDATE
    SET last_power_w    = EXCLUDED.last_power_w,
        last_current_a  = EXCLUDED.last_current_a,
        last_power_time = EXCLUDED.last_power_time;
  RETURN NEW;
END; $$ LANGUAGE plpgsql;

CREATE TRIGGER trg_power_latest
AFTER INSERT ON power_metrics
FOR EACH ROW EXECUTE FUNCTION fn_update_power_latest();
```

**Why a trigger instead of application code:**

| Approach | Pros | Cons |
|---|---|---|
| **Trigger (current)** | ✅ Transactional (consistent with `power_metrics`) <br> ✅ Telegraf doesn't need to know `power_latest` exists <br> ✅ No race conditions | ❌ Slight write amplification (2 rows per insert) <br> ❌ Trigger logic lives in DB, harder to unit test |
| **Telegraf does two INSERTs** | ✅ Explicit in config | ❌ Non-transactional (if `power_latest` insert fails, `power_metrics` and `power_latest` diverge) <br> ❌ Telegraf config must know about both tables |
| **Node-RED does the UPSERT** | ✅ Visible in flow | ❌ Wrong layer — Node-RED shouldn't process power data <br> ❌ Violates single-writer rule <br> ❌ Adds 200 msg/s to Node-RED |

**Trigger approach chosen:** transactional consistency + single responsibility for Telegraf + architectural correctness.

**Performance impact:** at 200 inserts/sec, the trigger fires 200 times/sec. Each trigger call is ~50µs → 10ms total per second → 1% overhead. Negligible.

---

## 6. Continuous Aggregates

### 6.1 `power_1min`

**Purpose:** Pre-computed 1-minute rollups of `power_metrics` for fast historical queries.

**Refresh schedule:** every 1 minute, processing data from `now() - 1 hour` to `now() - 1 minute`.

**Why 1-minute resolution:**
- 1-second would be too many rows (~86M/day at 1,000 machines) with no dashboard use
- 1-hour would be too coarse for "last 2 hours" views
- 1-minute balances: ~1.44M rows/day, supports "last 30 days" queries in < 1 second

**Query pattern that uses it:**

```sql
-- Trend: average power per machine, last 30 days
SELECT bucket, machine_id, avg_power_w
FROM power_1min
WHERE bucket > now() - interval '30 days'
  AND machine_id = 'L01-M05'
ORDER BY bucket;
```

**Without CAGG:** this would scan ~518M rows in `power_metrics` (30 days × 17.3M). With CAGG: scans ~43K rows. **~12,000× faster.**

**Adding new aggregates (Phase 3+):**

```sql
-- Example: 1-hour aggregate for OEE trends
CREATE MATERIALIZED VIEW power_1hour
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 hour', time) AS bucket,
       machine_id,
       avg(power_w) AS avg_power_w,
       max(power_w) AS max_power_w,
       max(energy_kwh) AS energy_kwh
FROM power_metrics
GROUP BY bucket, machine_id
WITH NO DATA;
```

---

## 7. Partitioning & Chunking

### 7.1 Chunk interval rationale

| Table | Chunk interval | Rationale |
|---|---|---|
| `power_metrics` | **1 day** | 17.3M rows/day. 90-day retention = 90 chunks. Manageable for compression, query planner, and disk I/O. |
| `machine_events` | **7 days** | ~2.85M rows/day. 2-year retention = ~104 chunks. Larger chunks reduce overhead per chunk. |
| `dead_letter` | **7 days** | Near-zero rows. Larger chunks reduce catalog size. |

**Why not smaller chunks:**
- More chunks = more catalog overhead, more query planning time, more `INSERT` overhead (chunk lookup)
- At 1-day intervals, `power_metrics` has 90 chunks — manageable
- TimescaleDB's sweet spot is 10–1,000 chunks per hypertable

**Why not larger chunks:**
- Larger chunks take longer to compress (chunk-level operation)
- Larger chunks reduce query pruning effectiveness (more data scanned per chunk)

### 7.2 Chunk pruning

TimescaleDB automatically prunes chunks by time-based WHERE clauses:

```sql
-- Scans only the last 1-2 chunks (not all 90)
SELECT * FROM power_metrics
WHERE time > now() - interval '1 hour';
```

**Verification:**

```sql
EXPLAIN (ANALYZE, BUFFERS)
SELECT count(*) FROM power_metrics
WHERE time > now() - interval '1 hour';
```

Expected: `Chunks excluded during startup: 88` (out of 90 total for 90 days).

---

## 8. Compression & Retention

### 8.1 Compression policy

**Enable compression on `power_metrics` after 7 days:**

```sql
ALTER TABLE power_metrics SET (
  timescaledb.compress,
  timescaledb.compress_segmentby = 'machine_id',
  timescaledb.compress_orderby = 'time DESC'
);
SELECT add_compression_policy('power_metrics', INTERVAL '7 days');
```

**`segmentby = machine_id`:** groups rows by machine within compressed chunks. Queries filtering by `machine_id` decompress only their machine's data.

**`compress_orderby = 'time DESC'`:** within a segment, sorted by time descending. This matches the primary query pattern (`ORDER BY time DESC`) and maximizes compression (adjacent rows have similar values).

**Compression ratio:** typically 10–15× for time-series data. `power_metrics` at 200 GB uncompressed → ~15–25 GB compressed.

### 8.2 Retention policy

**Raw retention:**

| Table | Retention | Rationale |
|---|---|---|
| `power_metrics` | 90 days | Raw data useful for recent analysis; longer retention via `power_1min` |
| `machine_events` | 2 years | Events are small; long retention enables year-over-year comparisons |
| `power_1min` | 2 years | Aggregates support long-term trends without storing raw |
| `dead_letter` | 30 days | Debug data — short retention is fine |
| `power_latest` | Current only | 1 row per machine, no retention policy needed |
| `machine_status` | Current only | 1 row per machine, no retention policy needed |

**Implementation:**

```sql
SELECT add_retention_policy('power_metrics', INTERVAL '90 days');
SELECT add_retention_policy('machine_events', INTERVAL '2 years');
SELECT add_retention_policy('power_1min', INTERVAL '2 years');
SELECT add_retention_policy('dead_letter', INTERVAL '30 days');
```

**Trade-off:** 90-day raw retention means you can't query per-5-second power data older than 90 days. For most analyses (OEE trends, monthly reports), `power_1min` at 2 years is sufficient.

---

## 9. Naming Conventions

| Entity type | Convention | Examples |
|---|---|---|
| **Table names** | Lowercase, underscores, plural for collections | `power_metrics`, `power_latest`, `power_1min`, `machine_events`, `machine_status`, `dead_letter` |
| **Column names** | Lowercase, underscores | `machine_id`, `last_power_w`, `state_since` |
| **Index names** | `<table>_<columns>_<type>` | `power_metrics_machine_id_time_idx`, `machine_events_event_id_time_uniq` |
| **Trigger names** | `trg_<purpose>` | `trg_power_latest` |
| **Function names** | `fn_<purpose>` | `fn_update_power_latest` |
| **CAGG names** | `<base_table>_<resolution>` | `power_1min`, `power_1hour` |
| **Sequence names** | Default PostgreSQL | N/A (no sequences in this schema) |

**Reserved prefixes:** none. All identifiers are domain-specific.

**Identifier length:** all ≤ 63 characters (PostgreSQL max). No truncation issues.

---

## 10. Data Types & Rationale

### 10.1 Type usage summary

| Type | Usage | Why |
|---|---|---|
| **TIMESTAMPTZ** | All timestamps | Handles timezone correctly; converts to UTC internally. Never `TIMESTAMP` (no timezone) — that would silently strip timezone info. |
| **TEXT** | All IDs, codes, states | PostgreSQL `TEXT` and `VARCHAR` are performance-identical. `TEXT` avoids arbitrary length limits. |
| **DOUBLE PRECISION** | All float measurements | Fast, adequate precision for sensor data (15 significant digits). Not `NUMERIC` (slower, unnecessary precision). |
| **UUID** | `event_id` | Native type; 16 bytes vs 36 for TEXT; built-in validation. |
| **JSONB** | `payload` | Binary representation of JSON — faster than JSON (text), indexable, supports operators (`->>`, `@>`, `?`). |
| **INT** | `schema_version` | Small range (1–255), native int. |
| **BOOLEAN** | (none used) | Reserved for future use (e.g., `is_anomaly` flags). |

### 10.2 Type-specific decisions

**`TIMESTAMPTZ` vs `TIMESTAMP`:**
```sql
-- WRONG: loses timezone
CREATE TABLE bad (time TIMESTAMP NOT NULL);

-- CORRECT: preserves timezone, converts to UTC
CREATE TABLE good (time TIMESTAMPTZ NOT NULL);
```

All timestamps in this schema use `TIMESTAMPTZ`. Device timestamps are UTC (ISO 8601 with `Z`); server timestamps are also UTC. No ambiguity.

**`TEXT` vs `VARCHAR`:**
```sql
-- WRONG: arbitrary length limit (why 16?)
CREATE TABLE bad (machine_id VARCHAR(16));

-- CORRECT: no arbitrary limit
CREATE TABLE good (machine_id TEXT);
```

In PostgreSQL, `TEXT` and `VARCHAR(n)` have identical performance. `TEXT` avoids the "string too long" errors that plague `VARCHAR(n)` schemas. Use `TEXT` for all string columns.

**`DOUBLE PRECISION` vs `NUMERIC`:**
```sql
-- WRONG: NUMERIC is 5-10× slower for aggregations
CREATE TABLE bad (power_w NUMERIC(10,2));

-- CORRECT: fast float, adequate precision
CREATE TABLE good (power_w DOUBLE PRECISION);
```

Power measurements have ±1% sensor noise — precision beyond float64 is wasted. `NUMERIC` would be correct for money; this schema doesn't store money.

**`JSONB` vs `JSON`:**
```sql
-- WRONG: JSON is text, no indexing, slower parsing
CREATE TABLE bad (payload JSON);

-- CORRECT: JSONB is binary, indexable, faster
CREATE TABLE good (payload JSONB);
```

`JSONB` is the standard for JSON data in PostgreSQL. `JSON` (text) has no performance advantage for our use case.

---

## 11. Common Queries

### 11.1 Real-time dashboard queries

**Panel 1 — Line Status (per machine, current state):**

```sql
SELECT machine_id, state, state_since, job_id
FROM machine_status
WHERE line_id = 'L01'
ORDER BY machine_id;
```

**Execution:** Index scan on `(line_id, state)`. Returns ~20 rows in < 1ms.

**Panel 2 — Live Power trend (last 10 minutes):**

```sql
SELECT time, machine_id AS metric, power_w
FROM power_metrics
WHERE line_id = 'L01'
  AND time > now() - interval '10 minutes'
ORDER BY time;
```

**Execution:** Chunk prune (2 chunks) + index scan on `(machine_id, time DESC)`. Returns ~3,600 rows in < 100ms.

**Panel 3 — Current Draw gauge (per machine):**

```sql
SELECT machine_id, last_power_w
FROM power_latest
WHERE machine_id IN ('L01-M01', 'L01-M02', 'L01-M03');
```

**Execution:** Index scan on PK. Returns 3 rows in < 1ms.

**Panel 4 — State Timeline (last 1 hour):**

```sql
SELECT time, machine_id AS metric, new_state AS state
FROM machine_events
WHERE event_type = 'STATE_CHANGE'
  AND line_id = 'L01'
  AND time > now() - interval '1 hour'
ORDER BY time;
```

**Execution:** Index scan on `(machine_id, time DESC)` + filter on `event_type`. Returns ~50–200 rows in < 50ms.

**Panel 5 — Jobs Completed Today:**

```sql
SELECT count(*) AS "jobs"
FROM machine_events
WHERE event_type = 'JOB_COMPLETE'
  AND line_id = 'L01'
  AND time > date_trunc('day', now());
```

**Execution:** Index scan on `(event_type, time DESC)`. Returns count in < 10ms.

**Panel 6 — Recent Events:**

```sql
SELECT time, machine_id, event_type, new_state, payload::text AS payload
FROM machine_events
WHERE line_id = 'L01'
ORDER BY time DESC, event_id DESC
LIMIT 50;
```

**Execution:** Chunk prune (1-2 chunks) + index scan. Returns 50 rows in < 20ms.

### 11.2 Historical queries

**Power trend (last 30 days, using CAGG):**

```sql
SELECT bucket, avg_power_w
FROM power_1min
WHERE machine_id = 'L01-M05'
  AND bucket > now() - interval '30 days'
ORDER BY bucket;
```

**Execution:** CAGG scan. Returns ~43K rows in < 500ms. **12,000× faster** than scanning `power_metrics`.

**OEE components (Phase 3+):**

```sql
-- Availability: time in RUNNING state / total time
WITH state_durations AS (
  SELECT
    machine_id,
    new_state,
    time AS state_start,
    lead(time) OVER (PARTITION BY machine_id ORDER BY time) AS state_end
  FROM machine_events
  WHERE event_type = 'STATE_CHANGE'
    AND time > now() - interval '24 hours'
)
SELECT
  machine_id,
  sum(EXTRACT(EPOCH FROM (state_end - state_start)))
    FILTER (WHERE new_state = 'RUNNING') AS run_time_s,
  sum(EXTRACT(EPOCH FROM (state_end - state_start)))
    FILTER (WHERE new_state IN ('STOPPED', 'FAULT')) AS downtime_s
FROM state_durations
WHERE state_end IS NOT NULL
GROUP BY machine_id;
```

**Execution:** Full scan of `machine_events` for the time window. Returns in < 2 seconds for one day's data. **This is where the CAGG doesn't help — state durations require window functions over raw events.**

### 11.3 Diagnostic queries

**Check for duplicate events (should be 0):**

```sql
SELECT event_id, count(*)
FROM machine_events
GROUP BY event_id
HAVING count(*) > 1;
```

**Check for stale machines (no event in > 5 min):**

```sql
SELECT machine_id, updated_at, now() - updated_at AS lag
FROM machine_status
WHERE now() - updated_at > interval '5 minutes'
ORDER BY lag DESC;
```

**Check pipeline lag (power_latest freshness):**

```sql
SELECT machine_id, last_power_time, now() - last_power_time AS lag
FROM power_latest
ORDER BY lag DESC
LIMIT 10;
```

**Check chunk compression status:**

```sql
SELECT chunk_name, is_compressed, pg_size_pretty(before_compression_total_bytes) AS before,
       pg_size_pretty(after_compression_total_bytes) AS after
FROM chunk_compression_stats('power_metrics')
ORDER BY chunk_name DESC
LIMIT 5;
```

---

## 12. Performance Analysis

### 12.1 Write path (at 1,000 machines)

| Write type | Rate | Table | Notes |
|---|---|---|---|
| **Power insert** | 200/s | `power_metrics` | Telegraf batched (500 per INSERT) → 1 INSERT per 2.5s |
| **Power latest UPSERT** | 200/s | `power_latest` | Trigger fires per row → 200 UPSERTs/s |
| **Event insert** | 11/s | `machine_events` | Node-RED per event |
| **Status UPSERT** | 11/s | `machine_status` | Node-RED per event |
| **CAGG refresh** | 1/min | `power_1min` | Background worker, incremental |

**Total writes:** ~222 inserts/sec + 200 trigger-derived UPSERTs + 11 status UPSERTs = ~430 writes/sec.

**Load test result (Phase 4 WBS-4.10 — future):** TimescaleDB on a single NVMe SSD handles this easily. Expected < 15% CPU on the DB VM, < 2ms per write.

### 12.2 Read path (at 1,000 machines, 5s Grafana refresh)

| Panel | Query type | Frequency | Expected latency |
|---|---|---|---|
| Panel 1 (Line Status) | `machine_status` index scan | 5s | < 1ms |
| Panel 2 (Live Power) | `power_metrics` chunk prune + scan | 5s | < 100ms |
| Panel 3 (Gauges) | `power_latest` PK lookup | 5s | < 1ms |
| Panel 4 (State Timeline) | `machine_events` index scan | 5s | < 50ms |
| Panel 5 (Jobs Today) | `machine_events` index scan | 5s | < 10ms |
| Panel 6 (Recent Events) | `machine_events` chunk + scan | 5s | < 20ms |
| **Total per refresh** | — | **every 5s** | **< 200ms** |

**Grafana query rate:** 6 queries × 12 refreshes/min = 72 queries/min = ~1.2 queries/sec. **Trivial load** for TimescaleDB.

### 12.3 Storage growth

| Table | Daily growth | 90 days | 2 years |
|---|---|---|---|
| `power_metrics` (raw) | 17.3M rows, ~2.2 GB | 1.56B rows, ~200 GB | (retention limit: 90d) |
| `power_metrics` (compressed) | — | — | ~15–25 GB |
| `power_1min` | 1.44M rows, ~180 MB | ~16 GB | ~130 GB |
| `machine_events` | 2.85M rows, ~250 MB | ~22 GB | ~180 GB |
| **Total disk (compressed, stable state)** | — | **~55 GB** | **~340 GB** |

**At 1,000 machines with full retention, expect ~340 GB disk usage.** Fits on a 500 GB VMDK with 30% headroom.

---

## 13. Security

### 13.1 Database-level controls

| Control | Phase 0 state | Phase 2 gate |
|---|---|---|
| **Authentication** | Password auth (`iiot` user) | ✅ Same |
| **`pg_hba.conf`** | `host all all 0.0.0.0/0 md5` | Restrict to docker network + localhost |
| **SSL/TLS** | Disabled (`sslmode=disable`) | Enable `sslmode=require` |
| **`postgres` superuser** | Disabled (using `iiot` user) | ✅ Same |
| **Network exposure** | `5432` exposed on host | Bind to localhost only |
| **Backup encryption** | Not encrypted | GPG-encrypted `pg_dump` |

### 13.2 Access control

**Phase 0:** single `iiot` user owns all tables and performs all operations. Simple but coarse.

**Phase 2+:** consider role separation:

```sql
-- Future: separate roles per writer
CREATE ROLE telegraf_writer LOGIN PASSWORD '...';
GRANT INSERT ON power_metrics TO telegraf_writer;

CREATE ROLE nodered_writer LOGIN PASSWORD '...';
GRANT INSERT ON machine_events TO nodered_writer;
GRANT INSERT, UPDATE ON machine_status TO nodered_writer;
GRANT USAGE ON ALL SEQUENCES IN SCHEMA public TO nodered_writer;

CREATE ROLE grafana_reader LOGIN PASSWORD '...';
GRANT SELECT ON ALL TABLES IN SCHEMA public TO grafana_reader;
```

**Benefits:** even if a service is compromised, it can only do what it needs to. Telegraf can't delete events; Grafana can't insert.

**Deferred to Phase 2** — adds operational complexity. Single `iiot` user is acceptable for lab and small deployments.

### 13.3 Sensitive data handling

**Current schema stores no PII.** Machine IDs, event IDs, power data — no personal information. `operator_id` is a code (`OP-042`), not a name. Employee names are not stored in the database.

**Phase 2+:** if operator attribution becomes important, store operator codes in a separate lookup table (`operator_ids` → names) that can be restricted via role-level access.

---

## 14. Backup & Recovery

### 14.1 Backup strategy

| Backup type | Frequency | Retention | Method |
|---|---|---|---|
| **Full `pg_dump`** | Nightly 02:00 | 30 days | `pg_dump -Fc` to `/backup/pg/` |
| **Continuous WAL archiving** | Continuous | 7 days | `pg_basebackup` + WAL to separate disk |
| **VM-level backup** | Weekly | 4 weeks | Veeam or equivalent |
| **Restore test** | Monthly | — | Full restore to temp VM, verify schema + row counts |

### 14.2 Backup script

```bash
#!/bin/bash
# /usr/local/bin/pg_backup.sh
set -euo pipefail

BACKUP_DIR=/backup/pg
DATE=$(date +%Y%m%d_%H%M%S)
FILENAME="$BACKUP_DIR/iiot_$DATE.dump"

docker exec iiot-timescaledb pg_dump -U iiot -d iiot -Fc -f /tmp/iiot.dump
docker cp iiot-timescaledb:/tmp/iiot.dump "$FILENAME"
docker exec iiot-timescaledb rm /tmp/iiot.dump

# Delete backups older than 30 days
find "$BACKUP_DIR" -name 'iiot_*.dump' -mtime +30 -delete

echo "Backup complete: $FILENAME"
```

**Cron:** `0 2 * * * /usr/local/bin/pg_backup.sh >> /var/log/pg_backup.log 2>&1`

### 14.3 Restore procedure

```bash
# 1. Stop all services except DB
docker compose stop telegraf nodered grafana

# 2. Restore database
docker exec -i iiot-timescaledb pg_restore -U iiot -d iiot --clean --if-exists < /backup/pg/iiot_20261115_020000.dump

# 3. Verify
docker exec iiot-timescaledb psql -U iiot -d iiot -c "
SELECT 'power_metrics' AS t, count(*) FROM power_metrics
UNION ALL SELECT 'machine_events', count(*) FROM machine_events
UNION ALL SELECT 'machine_status', count(*) FROM machine_status;"

# 4. Restart services
docker compose start telegraf nodered grafana
```

**Restore test (monthly):** restore to a fresh TimescaleDB container, verify row counts and schema match production. **A backup that has never been restored is a backup that doesn't exist.**

### 14.4 Disaster recovery

**RTO (Recovery Time Objective):** 30 minutes for full restore from backup.
**RPO (Recovery Point Objective):** 24 hours (nightly backup) — reduce to 1 hour if WAL archiving is enabled.

**Phase 2+:** consider streaming replication to a standby VM for sub-minute RTO.

---

## 15. Migration Procedures

### 15.1 Schema change policy

Every schema change follows this procedure:

1. **Draft the change** in `config/postgres/migrations/NNN_description.sql`
2. **Test on a fresh DB** (from `01_schema.sql` + all migrations)
3. **Test on a copy of production** (if available)
4. **Document in this DDD** (§17 Change Log)
5. **Update `01_schema.sql`** for fresh installs (cumulative schema)
6. **Apply migration to production** during low-traffic window
7. **Verify** with post-migration smoke test

### 15.2 Adding a column (non-breaking)

```sql
-- migrations/002_add_quality_flag.sql
ALTER TABLE power_metrics ADD COLUMN IF NOT EXISTS quality_flag TEXT;
```

**Safe:** existing rows get NULL. No table rewrite. Instantaneous.

### 15.3 Adding a column with default (may rewrite table)

```sql
-- migrations/003_add_schema_version.sql
ALTER TABLE machine_events ADD COLUMN schema_version INT DEFAULT 1;
```

**Rewrite:** PostgreSQL 11+ optimizes this (no full rewrite) for most types. Verify with `EXPLAIN ANALYZE` if table > 1M rows.

### 15.4 Adding a hypertable column (TimescaleDB-specific)

```sql
-- migrations/004_add_energy_to_power.sql
ALTER TABLE power_metrics ADD COLUMN IF NOT EXISTS apparent_power_va DOUBLE PRECISION;
```

**TimescaleDB handles this transparently** — no need to rebuild chunks. Column appears in all existing and future chunks.

### 15.5 Adding an index (may lock table)

```sql
-- migrations/005_add_source_index.sql
-- Safe: CREATE INDEX CONCURRENTLY doesn't lock the table
CREATE INDEX CONCURRENTLY IF NOT EXISTS power_metrics_source_idx
  ON power_metrics (source);
```

**`CONCURRENTLY`:** allows reads/writes during index build. Slower to complete but doesn't block production.

### 15.6 Changing a primary key or unique index

**Not possible on a hypertable in place.** Would require:
1. Create new table with new schema
2. Copy data
3. Rename tables
4. Recreate indexes and triggers

**This is why schema versioning matters.** Get the schema right in Phase 0 (which we did — the `(event_id, time)` fix was Phase 0).

### 15.7 Dropping a hypertable

```sql
-- Use TimescaleDB's drop_chunks for time-based deletion
SELECT drop_chunks('power_metrics', older_than => INTERVAL '90 days');

-- For full table drop:
DROP TABLE IF EXISTS power_metrics CASCADE;
```

**Warning:** `DROP TABLE` on a hypertable drops all chunks. Unrecoverable without backup.

---

## 16. Known Limitations

| # | Limitation | Impact | Mitigation |
|---|---|---|---|
| **L-DB-01** | No foreign keys | Referential integrity enforced only at application layer | Contract validator (`tools/validate_contract.py`); role separation in Phase 2 |
| **L-DB-02** | `machine_status.last_seen` is never written | Can't query "last heartbeat time" | Use `power_latest.last_power_time` or `updated_at`; remove or wire up in Phase 4 |
| **L-DB-03** | No partition pruning optimization for `event_type` queries older than 7 days | Full scan across all chunks when filtering by event type only | Add `(event_type, time DESC)` index (already present) |
| **L-DB-04** | CAGG `power_1min` doesn't include `source` or `quality` | Aggregated view lacks provenance | Query `power_metrics` for provenance; add CAGG columns in Phase 3 if needed |
| **L-DB-05** | No streaming replication (Phase 0) | Single point of failure; recovery requires restore from backup | Nightly backups; streaming replica in Phase 5–6 |
| **L-DB-06** | `machine_events.schema_version` never used in queries | Forward-compat field is unused | Use in Phase 3+ if schema evolves; currently informational |
| **L-DB-07** | No `dead_letter` writes (Node-RED unwired) | Malformed events are dropped silently | Wire in Phase 4 (5-minute fix) |
| **L-DB-08** | CAGG refresh lag up to 1 minute | Real-time queries must hit raw table (which they do); historical may lag 60s | Acceptable; add real-time aggregations in Phase 3 if needed |

---

## 17. Change Log

| Version | Date | Changes |
|---|---|---|
| 1.0 | 2026-11-15 | Initial DDD after Phase 0 completion. Reflects the as-built schema: 6 tables (2 hypertables, 2 regular, 1 CAGG, 1 dead_letter), 6 indexes, 1 trigger, 1 continuous aggregate. Documents the `(event_id, time)` unique index (the critical constraint from LinkedIn Post 1) and the `trg_power_latest` trigger (why Telegraf only writes one table). |

---

## 18. References

| Document | Purpose |
|---|---|
| `prd-v1.0.md` | Product requirements — why these tables exist |
| `sad-v1.0.md` | System architecture — how the DB fits in the system |
| `data-contract-v1.0.1.md` | Payload schemas — what goes into each column |
| `implementation-plan-v1.0.md` | Execution plan — when schema changes happen |
| `config/postgres/init/01_schema.sql` | Actual schema (source of truth) |
| `tools/validate_contract.py` | Contract validator — catches malformed payloads before they reach the DB |

---

*End of Database Design Document v1.0*
