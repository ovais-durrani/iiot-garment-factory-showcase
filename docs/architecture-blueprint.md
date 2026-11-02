**Note — this is the original design blueprint.**

Written before implementation, describing the intended architecture. The
actual Phase 0 implementation may differ from this document in small ways.
For the running version, the source of truth is:
- [`config/postgres/init/01_schema.sql`](../config/postgres/init/01_schema.sql) — the actual database schema
- [`docs/data-contract-v1.md`](data-contract-v1.md) — the frozen contract, with all deviations noted

**One notable divergence:** §4.2 recommends a `UNIQUE` constraint on `event_id`.
The implemented schema uses `UNIQUE INDEX ON machine_events (event_id, time)`
because TimescaleDB requires unique indexes on hypertables to include the
partitioning column. The `event_id`-only version was the bug that cost 3 days
to debug (see Post 1 of the build series). The corrected version is in `01_schema.sql`.


# Principal Enterprise IIoT Solutions Architect Blueprint  
## On-Premise Garment Factory IIoT Platform (No Redis, TimescaleDB as Single Source of Truth)

Below is a deep architectural review and design for your garment factory IIoT application. I’ll validate your stack, define clear role separation, provide data schemas, an ASCII architecture diagram, and rugged industrial mitigations. The design scales from 10–20 machines to ~1,000 machines (50 lines) while remaining fully on-premise.

---

## 1. Architectural & Role Validation

### 1.1 Stack Review (Step-by-Step Reasoning)

| Component | Verdict | Reasoning & Recommendations |
|-----------|---------|----------------------------|
| **Mosquitto (MQTT)** | ✅ Strong fit | Lightweight, mature, on-prem. For 1,000 machines and ~100–200 msg/s, Mosquitto is sufficient. Enable persistence, QoS 1, ACLs, and tune `max_connections`, `max_inflight_messages`. Use MQTT 3.1.1. For future scale, EMQX/HiveMQ are alternatives, but not required now. |
| **Telegraf** | ✅ Excellent for continuous telemetry | Handles high-frequency power data via MQTT consumer and Modbus TCP input. Batches writes to TimescaleDB. Avoid using Node-RED for high-frequency power ingestion. |
| **Node-RED** | ✅ Good for event-driven logic | Ideal for discrete events, state machines, hysteresis, and UPSERTing current status. Do **not** use Node-RED for continuous power ingestion—it adds latency and CPU overhead. |
| **TimescaleDB** | ✅ Correct choice without Redis | Handles both time-series (hypertables) and relational current-state tables. Use a dedicated `machine_status` table for instantaneous status to avoid querying large hypertables for “latest value.” |
| **Grafana** | ✅ Standard | Query `machine_status` for real-time panels and continuous aggregates for historical/OEE. |
| **Python** | ✅ Useful | Use for OEE batch jobs, ERP/MES integration, scheduled reports, and optionally a scalable state-machine service if Node-RED becomes a bottleneck at 1,000 machines. |

### 1.2 Telegraf vs. Node-RED: Split Duties to Avoid Duplication and Bottlenecks

**Principle: Single writer per data domain.**

| Data Domain | Owner | Responsibility | Topics / Inputs | Output |
|-------------|-------|----------------|-----------------|--------|
| **Continuous power metrics** (every 5–10s) | **Telegraf** | Poll Modbus TCP power meters and/or consume MQTT power topics. Parse, batch, write to `power_metrics` hypertable. | `factory/+/machine/+/power` (MQTT) or Modbus TCP registers | `power_metrics` table only |
| **Discrete events** (Job Complete, Fault, State Change) | **Node-RED** | Consume event topics, run hysteresis/state machine, write events to `machine_events`, UPSERT `machine_status`. | `factory/+/machine/+/event` (MQTT) | `machine_events` hypertable + `machine_status` table |
| **Derived state** | **Node-RED** | Publish processed state to `factory/+/machine/+/state` for other consumers (Grafana alerting, Python). | Internal | MQTT state topic |
| **Power-derived run state** (optional) | **Telegraf** | If needed, Telegraf can derive a boolean `is_running` from current and publish to `factory/+/machine/+/power_state` for Node-RED. | Power input | MQTT `power_state` topic |

**Avoiding duplicate data:**
- Telegraf **never** writes to `machine_events` or `machine_status`.
- Node-RED **never** writes raw power samples to `power_metrics`.
- If Node-RED needs power context for hysteresis, it can:
  - Query `power_metrics` for the last 10–30 seconds via the PostgreSQL node (cheap, indexed), **or**
  - Subscribe to a low-frequency `power_state` topic published by Telegraf (recommended for 1,000 machines to avoid DB queries in the state machine).

**Bottleneck avoidance:**
- Telegraf uses `outputs.postgresql` with `batch_size = 1000`, `max_idle_conns`, and `connection_string` pooling.
- Node-RED uses `node-red-contrib-postgresql` with a single connection pool. Keep flows stateless and avoid `function` nodes doing heavy JSON parsing per message; use `json` node and `change` nodes.
- For 1,000 machines, consider moving the state machine/hysteresis to a Python `asyncio` service using `asyncpg` and `paho-mqtt`. Node-RED can still handle 1,000 machines if flows are efficient, but Python is more predictable at scale.

### 1.3 TimescaleDB Optimization for Instant Real-Time Status (No Redis)

**Problem:** Querying `SELECT last(...) FROM power_metrics WHERE machine_id = ...` across a large hypertable for 1,000 machines on every dashboard refresh causes lag.

**Solution: Dual-table strategy.**

1. **`power_metrics` (hypertable)** – append-only historical time-series.
   - Partition by `time` with `chunk_time_interval = 1 day` (at ~100 msg/s, ~8.6M rows/day).
   - Index: `(machine_id, time DESC)`.
   - Compression: enable on chunks older than 7 days, `segmentby = machine_id`, `orderby = time DESC`.
   - Continuous aggregates: `power_metrics_1min` and `power_metrics_1hour` for OEE and historical dashboards.
   - Retention: raw power 90 days; aggregates 2 years.

2. **`machine_status` (regular table, ~1,000 rows)** – current state per machine.
   - Columns: `machine_id PK`, `line_id`, `state`, `last_event_time`, `last_power_w`, `last_update`, `job_id`, `operator_id`, `fault_code`.
   - Node-RED UPSERTs this row on every event or state change.
   - Telegraf can optionally UPSERT `last_power_w` via a PostgreSQL trigger or a separate small table `power_latest` updated by a trigger on `power_metrics` insert. **Recommended:** Use a PostgreSQL trigger on `power_metrics` that UPSERTs `power_latest (machine_id, last_power_w, last_power_time)`. This keeps Telegraf simple and gives Grafana an instant power value.
   - Grafana real-time panels query `machine_status` and `power_latest` directly—sub-millisecond response.

3. **`machine_events` (hypertable)** – append-only discrete events.
   - Partition by `time` with `chunk_time_interval = 7 days`.
   - Index: `(machine_id, time DESC)`, `(event_type, time DESC)`.
   - Retention: 2 years.

**Grafana query patterns:**
- Real-time status: `SELECT * FROM machine_status WHERE line_id = $line;`
- Real-time power gauge: `SELECT last_power_w FROM power_latest WHERE machine_id = $machine;`
- Historical power: `SELECT time, power_w FROM power_metrics WHERE machine_id = $machine AND time > now() - interval '1 hour';`
- OEE: query `power_metrics_1hour` and `machine_events` with `time_bucket`.

**Additional optimizations:**
- Use PgBouncer if connection count grows (Telegraf + Node-RED + Grafana + Python).
- Set `timescaledb.max_background_workers` appropriately.
- Avoid `SELECT *` in Grafana; always filter by time and machine.

---

## 2. Logical Design & Data Schemas

### 2.1 Stream A: Continuous Power Metrics

**Path:**  
Split-core CT / Modbus power meter → ESP32 (if analog) or Modbus TCP remote I/O → MQTT publish (`factory/{line_id}/machine/{machine_id}/power`) **or** Telegraf Modbus TCP poll → Telegraf → TimescaleDB `power_metrics`.

**Recommended topology:**  
- For power, prefer **industrial Modbus TCP power meters** (e.g., Schneider PM5560, Accuenergy Acuvim II) over raw CT + ESP32. They provide isolation, filtering, and reliable Modbus registers.
- Telegraf polls Modbus TCP meters directly (or consumes MQTT if ESP32 sends power). Telegraf parses and writes to TimescaleDB.

**Ideal JSON payload schema (MQTT or Telegraf internal):**

```json
{
  "timestamp": "2025-01-15T10:30:05.123Z",
  "machine_id": "LINE01-M05",
  "line_id": "LINE01",
  "voltage_v": 230.5,
  "current_a": 3.2,
  "power_w": 736.0,
  "energy_kwh": 0.204,
  "power_factor": 0.95,
  "frequency_hz": 50.0,
  "quality": "good",
  "source": "modbus_tcp_meter_01"
}
```

**Telegraf `json_v2` mapping:**
- `timestamp` → `time` (RFC3339)
- `machine_id`, `line_id` → tags
- `voltage_v`, `current_a`, `power_w`, `energy_kwh`, `power_factor`, `frequency_hz` → fields
- `quality`, `source` → tags

**TimescaleDB table:**

```sql
CREATE TABLE power_metrics (
  time TIMESTAMPTZ NOT NULL,
  machine_id TEXT NOT NULL,
  line_id TEXT NOT NULL,
  voltage_v DOUBLE PRECISION,
  current_a DOUBLE PRECISION,
  power_w DOUBLE PRECISION,
  energy_kwh DOUBLE PRECISION,
  power_factor DOUBLE PRECISION,
  frequency_hz DOUBLE PRECISION,
  quality TEXT,
  source TEXT
);
SELECT create_hypertable('power_metrics', 'time', chunk_time_interval => INTERVAL '1 day');
CREATE INDEX ON power_metrics (machine_id, time DESC);
```

**Trigger for `power_latest`:**

```sql
CREATE TABLE power_latest (
  machine_id TEXT PRIMARY KEY,
  last_power_w DOUBLE PRECISION,
  last_power_time TIMESTAMPTZ
);

CREATE OR REPLACE FUNCTION update_power_latest()
RETURNS TRIGGER AS $$
BEGIN
  INSERT INTO power_latest (machine_id, last_power_w, last_power_time)
  VALUES (NEW.machine_id, NEW.power_w, NEW.time)
  ON CONFLICT (machine_id) DO UPDATE
  SET last_power_w = EXCLUDED.last_power_w,
      last_power_time = EXCLUDED.last_power_time;
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER power_latest_trigger
AFTER INSERT ON power_metrics
FOR EACH ROW EXECUTE FUNCTION update_power_latest();
```

### 2.2 Stream B: Discrete Events (Job Complete, Fault, State Change)

**Path:**  
Push button / optical switch / fault relay → ESP32 (with opto-isolation) → MQTT publish QoS 1 (`factory/{line_id}/machine/{machine_id}/event`) → Node-RED → state machine + hysteresis → TimescaleDB `machine_events` + UPSERT `machine_status`.

**Ideal event JSON payload schema:**

**Job Complete:**
```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "timestamp": "2025-01-15T10:30:05.123Z",
  "machine_id": "LINE01-M05",
  "line_id": "LINE01",
  "event_type": "JOB_COMPLETE",
  "source": "esp32_01",
  "payload": {
    "job_id": "JOB-2025-00123",
    "operator_id": "OP-042",
    "garment_sku": "TSHIRT-BLK-L",
    "quantity": 1
  },
  "previous_state": "RUNNING",
  "new_state": "IDLE"
}
```

**Fault:**
```json
{
  "event_id": "6ba7b810-9dad-11d1-80b4-00c04fd430c8",
  "timestamp": "2025-01-15T10:31:12.456Z",
  "machine_id": "LINE01-M05",
  "line_id": "LINE01",
  "event_type": "FAULT",
  "source": "esp32_01",
  "payload": {
    "fault_code": "E-102",
    "fault_description": "Needle break",
    "severity": "critical"
  },
  "previous_state": "RUNNING",
  "new_state": "FAULT"
}
```

**State Change (published by Node-RED after hysteresis):**
```json
{
  "event_id": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
  "timestamp": "2025-01-15T10:32:00.000Z",
  "machine_id": "LINE01-M05",
  "line_id": "LINE01",
  "event_type": "STATE_CHANGE",
  "source": "node-red",
  "payload": {
    "reason": "hysteresis_stop",
    "duration_in_previous_state_s": 45
  },
  "previous_state": "RUNNING",
  "new_state": "STOPPED"
}
```

**TimescaleDB tables:**

```sql
CREATE TABLE machine_events (
  time TIMESTAMPTZ NOT NULL,
  event_id UUID NOT NULL,
  machine_id TEXT NOT NULL,
  line_id TEXT NOT NULL,
  event_type TEXT NOT NULL,
  source TEXT,
  payload JSONB,
  previous_state TEXT,
  new_state TEXT
);
SELECT create_hypertable('machine_events', 'time', chunk_time_interval => INTERVAL '7 days');
CREATE INDEX ON machine_events (machine_id, time DESC);
CREATE INDEX ON machine_events (event_type, time DESC);

CREATE TABLE machine_status (
  machine_id TEXT PRIMARY KEY,
  line_id TEXT NOT NULL,
  state TEXT NOT NULL,
  last_event_time TIMESTAMPTZ,
  last_power_w DOUBLE PRECISION,
  last_update TIMESTAMPTZ DEFAULT now(),
  job_id TEXT,
  operator_id TEXT,
  fault_code TEXT
);
CREATE INDEX ON machine_status (line_id);
```

**Node-RED UPSERT example:**
```sql
INSERT INTO machine_status (machine_id, line_id, state, last_event_time, job_id, operator_id, fault_code, last_update)
VALUES ($1, $2, $3, $4, $5, $6, $7, now())
ON CONFLICT (machine_id) DO UPDATE SET
  state = EXCLUDED.state,
  last_event_time = EXCLUDED.last_event_time,
  job_id = EXCLUDED.job_id,
  operator_id = EXCLUDED.operator_id,
  fault_code = EXCLUDED.fault_code,
  last_update = now();
```

---

## 3. High-Level Architecture Diagram

```text
+--------------------------------------------------------------------------------------------------+
|                                   APPLICATION LAYER                                              |
|  +------------------+  +------------------+  +------------------+  +------------------+          |
|  | Grafana          |  | Python Backend   |  | MES/ERP (future) |  | Alerting         |          |
|  | - Real-time      |  | - OEE batch jobs |  | - Integration    |  | - Email/SMS      |          |
|  |   status panels  |  | - Reports        |  |                  |  |                  |          |
|  | - Historical     |  | - ERP sync       |  |                  |  |                  |          |
|  |   dashboards     |  |                  |  |                  |  |                  |          |
|  +--------+---------+  +--------+---------+  +--------+---------+  +--------+---------+          |
|           |                     |                     |                     |                    |
|           +---------------------+---------------------+---------------------+                    |
|                                         | SQL (TCP 5432)                                         |
+-----------------------------------------|--------------------------------------------------------+
                                          v
+--------------------------------------------------------------------------------------------------+
|                                   STORAGE LAYER (TimescaleDB)                                    |
|  +-----------------------------+  +-----------------------------+  +---------------------------+ |
|  | power_metrics (hypertable)  |  | machine_events (hypertable) |  | machine_status (regular)  | |
|  | - time, machine_id, ...     |  | - time, machine_id, ...     |  | - machine_id (PK)         | |
|  | - 1-day chunks              |  | - 7-day chunks              |  | - state, job_id, operator | |
|  | - compression > 7d          |  | - retention 2y              |  | - last_power_w            | |
|  | - cont. aggregates 1m/1h    |  | - indexes                   |  | - UPSERT by Node-RED      | |
|  +-----------------------------+  +-----------------------------+  +---------------------------+ |
|  +-----------------------------+                                                                 |
|  | power_latest (regular)      |  <-- Trigger on power_metrics insert                            |
|  | - machine_id (PK)           |                                                                 |
|  | - last_power_w, last_time   |                                                                 |
|  +-----------------------------+                                                                 |
+--------------------------------------------------------------------------------------------------+
                                          ^
                                          | SQL (TCP 5432)
                                          |
+-----------------------------------------|--------------------------------------------------------+
|                                   PROCESSING / INGESTION LAYER                                   |
|  +-----------------------------+  +-----------------------------+  +---------------------------+ |
|  | Telegraf                    |  | Node-RED                    |  | Python (optional)         | |
|  | - Modbus TCP poller (power) |  | - MQTT consumer (events)    |  | - Scalable state machine  | |
|  | - MQTT consumer (power)     |  | - Hysteresis + state machine|  |   (if Node-RED hits       | |
|  | - Batch writes              |  | - Writes machine_events     |  |   limits at 1,000 m/c)    | |
|  | - Writes power_metrics      |  | - UPSERTs machine_status    |  | - asyncpg + paho-mqtt     | |
|  | - No event handling         |  | - Publishes state topic     |  |                           | |
|  +-----------------------------+  +-----------------------------+  +---------------------------+ |
+-----------------------------------------^--------------------------------------------------------+
                                          | MQTT (TCP 1883)
                                          |
+-----------------------------------------|--------------------------------------------------------+
|                                   MESSAGING / BROKER LAYER                                       |
|  +--------------------------------------------------------------------------------------------+  |
|  | Mosquitto MQTT Broker                                                                      |  |
|  | - Persistent sessions, QoS 1, ACLs                                                         |  |
|  | - Topics:                                                                                  |  |
|  |     factory/{line_id}/machine/{machine_id}/power   -> Telegraf                             |  |
|  |     factory/{line_id}/machine/{machine_id}/event   -> Node-RED                             |  |
|  |     factory/{line_id}/machine/{machine_id}/state   -> Node-RED publishes (consumers)       |  |
|  |     factory/{line_id}/machine/{machine_id}/power_state -> Telegraf (optional)              |  |
|  +--------------------------------------------------------------------------------------------+  |
+-----------------------------------------^--------------------------------------------------------+
                                          | MQTT / Modbus TCP
                                          |
+-----------------------------------------|--------------------------------------------------------+
|                                   EDGE LAYER                                                     |
|  +-----------------------------+  +-----------------------------+  +---------------------------+ |
|  | ESP32 Workstation Nodes     |  | Modbus TCP Remote I/O       |  | Industrial Power Meters   | |
|  | - Push button (Job Complete)|  | - Aggregates 8-16 sensors   |  | - Split-core CTs          | |
|  | - Fault relay input         |  | - Wired Ethernet            |  | - Modbus TCP/RTU          | |
|  | - Opto-isolated inputs      |  | - Digital inputs            |  | - Voltage, current, watts | |
|  | - LittleFS event buffer     |  |                             |  | - Isolated, filtered      | |
|  | - MQTT QoS 1 publish        |  |                             |  |                           | |
|  +-----------------------------+  +-----------------------------+  +---------------------------+ |
|           |                                  |                                  |                |
|           v                                  v                                  v                |
|  +------------------------------------------------------------------------------------------+    |
|  | Sensors: Push buttons, optical switches, relay contacts, CTs, voltage taps               |    |
|  +------------------------------------------------------------------------------------------+    |
+--------------------------------------------------------------------------------------------------+
```

**Data flow summary:**
- **Power:** Sensor → Modbus meter / ESP32 → MQTT power topic → Telegraf → `power_metrics` → trigger → `power_latest` → Grafana.
- **Events:** Sensor → ESP32 → MQTT event topic (QoS 1) → Node-RED → `machine_events` + `machine_status` → Grafana.
- **State:** Node-RED publishes `state` topic for other consumers (Python, alerting).

---

## 4. Rugged Industrial Mitigations

### 4.1 Hysteresis Logic: Distinguishing Short Operator Pauses from True Downtime

**Challenge:** An operator may stop the machine for 5–15 seconds to adjust fabric. This should not be counted as “Stop/Downtime” for OEE.

**Solution: Multi-signal state machine with debounce timers in Node-RED (or Python).**

**Signals:**
- Digital input: machine power/run signal (from control board or current relay).
- Current: `current_a` from power meter (more reliable than digital input alone).
- Fault relay: immediate fault.

**State definitions:**
- `RUNNING`: current > `RUN_THRESHOLD` (e.g., 1.0 A) **and** digital input high.
- `IDLE`: digital input high but current < `IDLE_THRESHOLD` (e.g., 0.3 A) for > `IDLE_DEBOUNCE` (e.g., 15 s).
- `STOPPED`: digital input low **and** current < `STOP_THRESHOLD` for > `STOP_DEBOUNCE` (e.g., 10 s).
- `FAULT`: fault relay active for > 200 ms.

**Algorithm (pseudocode for Node-RED function node or Python):**

```python
# Per-machine state
state = "STOPPED"
stop_timer = None
run_timer = None
idle_timer = None

def on_power_or_input(machine_id, current_a, digital_input, fault_active):
    global state, stop_timer, run_timer, idle_timer

    # Immediate fault
    if fault_active:
        cancel_all_timers()
        transition_to("FAULT", reason="fault_relay")
        return

    # RUNNING detection: require continuous run for RUN_DEBOUNCE (3s)
    if current_a > RUN_THRESHOLD and digital_input:
        cancel_timer(stop_timer)
        cancel_timer(idle_timer)
        if state != "RUNNING":
            if run_timer is None:
                run_timer = start_timer(RUN_DEBOUNCE, lambda: transition_to("RUNNING", reason="run_debounce"))
    else:
        cancel_timer(run_timer)

    # IDLE detection: machine powered but no current for IDLE_DEBOUNCE (15s)
    if digital_input and current_a < IDLE_THRESHOLD:
        cancel_timer(stop_timer)
        if state == "RUNNING":
            if idle_timer is None:
                idle_timer = start_timer(IDLE_DEBOUNCE, lambda: transition_to("IDLE", reason="idle_debounce"))
    else:
        cancel_timer(idle_timer)

    # STOPPED detection: no input and no current for STOP_DEBOUNCE (10s)
    if not digital_input and current_a < STOP_THRESHOLD:
        cancel_timer(run_timer)
        cancel_timer(idle_timer)
        if state in ("RUNNING", "IDLE"):
            if stop_timer is None:
                stop_timer = start_timer(STOP_DEBOUNCE, lambda: transition_to("STOPPED", reason="stop_debounce"))
    else:
        cancel_timer(stop_timer)
```

**Key parameters (tune per machine type):**
- `RUN_THRESHOLD`: 1.0 A (or 10% of typical running current).
- `IDLE_THRESHOLD`: 0.3 A.
- `STOP_THRESHOLD`: 0.3 A.
- `RUN_DEBOUNCE`: 3 s.
- `IDLE_DEBOUNCE`: 15 s (longer than typical fabric adjustment pause).
- `STOP_DEBOUNCE`: 10 s (short pauses < 10 s are ignored).

**Job Complete override:** When `JOB_COMPLETE` arrives, immediately transition to `IDLE` (not `STOPPED`) until next job starts, and reset timers.

**Result:** A 5–8 second pause does not trigger `STOPPED`; only a continuous 10+ second absence of current and input does. This prevents false downtime and improves OEE accuracy.

---

### 4.2 Network Resiliency: ESP32 Local Buffering for 30-Minute Network Drop

**Challenge:** Factory Wi-Fi/Ethernet drops for 30 minutes; “Job Complete” and fault events must not be lost.

**Solution: Store-and-forward with LittleFS circular buffer + MQTT QoS 1 + persistent session.**

**ESP32 design:**
- Use `LittleFS` (or SPIFFS) to store events as JSON files or a binary ring buffer.
- Each event has a unique `event_id` (UUID v4), `timestamp` (from RTC/NTP), `machine_id`, `event_type`, `payload`.
- MQTT client: `cleanSession = false`, `clientId = machine_id`, QoS 1, `keepAlive = 60`.
- On publish, wait for `PUBACK`. If no PUBACK within 5 s, keep in buffer and retry.
- On reconnect, flush buffer in FIFO order: publish, wait for PUBACK, then delete from flash.
- Buffer capacity: 30 minutes of events is tiny (job completes every few minutes; faults rare). Even 1,000 events × 512 bytes = 512 KB, well within ESP32 flash.
- If buffer full (unlikely), drop oldest non-critical events or stop accepting new until flushed; log a `BUFFER_OVERFLOW` event.

**Pseudocode:**

```c
// Event structure
typedef struct {
    char event_id[37];
    char timestamp[30];
    char machine_id[20];
    char event_type[20];
    char payload_json[256];
} Event;

// On button press / fault:
Event evt = create_event(...);
save_to_littlefs(evt);  // append to ring buffer
attempt_publish(evt);

// MQTT publish with QoS 1 and wait for PUBACK
bool attempt_publish(Event *evt) {
    if (mqtt_connected) {
        int msg_id = mqtt_publish(topic, evt->payload_json, QoS1);
        if (wait_for_puback(msg_id, 5000)) {
            delete_from_littlefs(evt->event_id);
            return true;
        }
    }
    return false;
}

// On MQTT reconnect:
void on_mqtt_connected() {
    // Flush buffered events in FIFO order
    while (has_buffered_events()) {
        Event evt = peek_oldest_event();
        if (attempt_publish(&evt)) {
            pop_oldest_event();
        } else {
            break;  // retry later
        }
    }
}
```

**Timekeeping:** Add a DS3231 RTC module (battery-backed) or use NTP on boot. If neither, store monotonic uptime and a base timestamp from the gateway; on reconnect, adjust timestamps. **Recommended:** DS3231 for accurate event timestamps even during network outage.

**Broker side:**
- Mosquitto `persistence true`, `persistence_location /var/lib/mosquitto/`, `autosave_interval 300`.
- Use `max_queued_messages` for offline subscribers (not publishers). Since ESP32 is publisher, broker persistence does not queue publisher messages; the ESP32 buffer is essential.
- Enable MQTT `message expiry interval` only if needed; not required here.

**Node-RED side:** Deduplicate by `event_id` using a PostgreSQL `UNIQUE` constraint on `event_id` and `ON CONFLICT DO NOTHING`. This prevents duplicate writes if the ESP32 retries after a PUBACK was lost.

---

### 4.3 Electrical Noise: Handling Inrush Current and Servo/Clutch Motor Noise

**Challenge:** Sewing machine servo/clutch motors generate inrush current spikes, EMI, and ground noise that can corrupt CT readings and crash ESP32.

**Mechanical / Hardware Mitigations:**

1. **Isolate digital inputs:** Use optocouplers (e.g., PC817, 6N137) for all push buttons, optical switches, and fault relays. This prevents ground loops and voltage spikes from reaching the ESP32.
2. **Shielded twisted pair:** Use shielded twisted pair for CT wires and digital inputs. Ground the shield at one end only (gateway/panel side) to avoid ground loops.
3. **Ferrite beads:** Clip ferrite beads on cables near the ESP32 and power meter to suppress high-frequency EMI.
4. **RC snubber:** Place an RC snubber (e.g., 100 Ω + 0.1 µF) across relay contacts and motor terminals to suppress arcing and inrush spikes.
5. **Separate power supply:** Power the ESP32 from a dedicated linear regulator or isolated DC-DC converter, not from the same rail as motors. Add a 1000 µF bulk capacitor and 0.1 µF decoupling capacitors near the ESP32.
6. **Surge protection:** Add TVS diodes (e.g., SMAJ5.0A) and MOVs on input lines and power supply.
7. **Proper grounding:** Use a star ground topology. Keep CT and signal wires away from motor cables (minimum 30 cm separation; cross at 90° if necessary).
8. **CT burden resistor and filter:** For raw CT + ESP32, use a precision burden resistor and an RC low-pass filter (e.g., 1 kΩ + 0.1 µF, cutoff ~1.6 kHz) before the ADC.
9. **Prefer Modbus power meters:** Industrial Modbus TCP meters (e.g., Schneider PM5560, Accuenergy Acuvim II) have built-in isolation, filtering, and RMS calculation. Use them for power; use ESP32 only for discrete inputs. This eliminates most noise issues and improves accuracy.

**Software / Firmware Mitigations:**

1. **ADC oversampling:** Read 16 samples and average. Use ESP32 `analogRead` with `analogSetSamples(16)` if available, or manual averaging.
2. **Median filter:** Apply a median filter of 5 consecutive readings to reject spikes.
3. **Outlier rejection:** If a reading is > 3× the rolling median, discard it and use the previous value.
4. **Debounce digital inputs:** 50–100 ms debounce in firmware (and again in Node-RED hysteresis).
5. **Watchdog timer:** Enable `esp_task_wdt` with a 5–10 s timeout. If the main loop hangs due to noise, the ESP32 resets automatically.
6. **Brown-out detector:** Enable BOD at 2.7 V to prevent unstable operation during voltage dips.
7. **Crash logging:** On boot, read `esp_reset_reason()` and publish a `DEVICE_RESET` event with the reason to MQTT for diagnostics.
8. **Avoid ADC reads during switching:** If possible, synchronize ADC reads away from motor switching edges (e.g., using zero-crossing detection). This is complex; Modbus meters handle it internally.
9. **Use external ADC for CT:** If using raw CT with ESP32, use an external 16-bit ADC (e.g., ADS1115) with a PGA and isolated I2C. The ESP32’s internal ADC is noisy and non-linear.

**Recommended hybrid architecture for power:**
- **Power:** Modbus TCP power meters → Telegraf → TimescaleDB.
- **Discrete events:** ESP32 with opto-isolated inputs → MQTT → Node-RED.
- This separates noisy power measurement from event handling and gives industrial-grade reliability.

---

## Summary of Key Recommendations

1. **Role split:** Telegraf owns continuous power ingestion; Node-RED owns discrete events and state machine. No duplicate writes.
2. **Real-time status:** Use `machine_status` (UPSERT by Node-RED) and `power_latest` (trigger from `power_metrics`) for instant Grafana queries. Use hypertables + continuous aggregates for historical/OEE.
3. **Hysteresis:** Multi-signal state machine with 10 s stop debounce and 15 s idle debounce to ignore short operator pauses.
4. **Network resiliency:** ESP32 LittleFS buffer + MQTT QoS 1 + PUBACK + RTC + deduplication by `event_id`.
5. **Electrical noise:** Opto-isolation, shielded cables, ferrite beads, RC snubbers, separate power, median filtering, watchdog, and prefer Modbus power meters over raw CT + ESP32.
6. **Scale to 1,000 machines:** Mosquitto tuning, Telegraf batching, TimescaleDB chunking/compression, Node-RED efficiency, and optional Python state-machine service.

This blueprint provides a robust, scalable, fully on-premise IIoT platform for your garment factory, with clear data ownership, real-time performance, and industrial-grade resilience.
