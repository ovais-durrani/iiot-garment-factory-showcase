CREATE EXTENSION IF NOT EXISTS timescaledb;

-- ============ HISTORICAL POWER ============
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
SELECT create_hypertable('power_metrics','time', chunk_time_interval => INTERVAL '1 day');
CREATE INDEX ON power_metrics (machine_id, time DESC);

-- ============ HISTORICAL EVENTS ============
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
SELECT create_hypertable('machine_events','time', chunk_time_interval => INTERVAL '7 days');
CREATE INDEX ON machine_events (machine_id, time DESC);
CREATE INDEX ON machine_events (event_type, time DESC);

-- TimescaleDB requires UNIQUE indexes to include the partitioning column (time).
-- Dedup is therefore on (event_id, time). Devices MUST send the same
-- (event_id, time) pair on retries — see data-contract-v1.md §15.
CREATE UNIQUE INDEX machine_events_event_id_time_uniq
  ON machine_events (event_id, time);

-- ============ CURRENT STATE ============
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

-- ============ LATEST POWER ============
CREATE TABLE power_latest (
  machine_id       TEXT PRIMARY KEY,
  last_power_w     DOUBLE PRECISION,
  last_current_a   DOUBLE PRECISION,
  last_power_time  TIMESTAMPTZ
);

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

-- ============ CONTINUOUS AGGREGATE ============
CREATE MATERIALIZED VIEW power_1min
WITH (timescaledb.continuous) AS
SELECT time_bucket('1 minute', time) AS bucket,
       machine_id,
       avg(power_w)    AS avg_power_w,
       max(power_w)    AS max_power_w,
       avg(current_a)  AS avg_current_a,
       max(energy_kwh) AS energy_kwh
FROM power_metrics
GROUP BY bucket, machine_id
WITH NO DATA;

SELECT add_continuous_aggregate_policy('power_1min',
  start_offset => INTERVAL '1 hour',
  end_offset   => INTERVAL '1 minute',
  schedule_interval => INTERVAL '1 minute');

-- ============ DEAD LETTER ============
CREATE TABLE dead_letter (
  time        TIMESTAMPTZ NOT NULL DEFAULT now(),
  topic       TEXT,
  raw_payload TEXT,
  error       TEXT
);
SELECT create_hypertable('dead_letter','time', chunk_time_interval => INTERVAL '7 days');
