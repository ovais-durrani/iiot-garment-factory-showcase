# IIoT for Garment Factories — Phase 0

An end-to-end IIoT pipeline for tracking industrial sewing machines.

**Status: Phase 0 complete — full pipeline working on simulated data.**

## What this is

A working, reproducible IIoT system for a garment factory floor. It tracks:

- **Job completion** — operators signal when a piece is finished
- **Machine state** — Run Time, Stop Time, Idle Time (for OEE)
- **Machine faults** — error signals from the machine control board
- **Power consumption** — voltage, current, watts per machine

Designed for 1,000 machines across 50 production lines, starting from a single prototype line.

## What this isn't (yet)

- **No real hardware.** Phase 0 uses a Python simulator. Phase 1 adds one real ESP32 + CT clamp on a bench. Phase 2 is a pilot line.
- **No OEE calculation.** The raw events that OEE needs are captured, but the calculation is Phase 3.
- **No production deployment.** No TLS, no per-device auth, no HA. Those are Phase 2 gates.

## Architecture

┌──────────┐      ┌─────────────┐      ┌──────────┐      ┌────────────┐
│Simulator │      │   MQTT      │      │ Telegraf │      │            │
│ / ESP32  │─────►│  Broker     │─────►│ (power)  │─────►│            │
└──────────┘      │             │      └──────────┘      │TimescaleDB │
                  │  topics:    │                        │            │
                  │  - power    │      ┌──────────┐      │  power_    │
                  │  - event    │─────►│ Node-RED │─────►│  metrics   │
                  │  - heartbeat│      │ (events) │      │  machine_  │
                  │  - state   ◄│──────│          │      │  events    │
                  │  (retained) │      └──────────┘      │  machine_  │
                  └─────────────┘                        │  status    │
                                                         └─────┬──────┘
                                                               │ SQL
                                                               ▼
                                                         ┌────────────┐
                                                         │  Grafana   │
                                                         └────────────┘


- **Telegraf** handles high-frequency power telemetry (200 msg/s at scale) — stateless, batched, fast
- **Node-RED** handles low-frequency events (state changes, faults, job completes) — stateful, with hysteresis and deduplication
- **TimescaleDB** is the system of record — hypertables, continuous aggregates, event dedup via `(event_id, time)`
- **Grafana** is provisioned entirely from code — dashboards survive `docker compose down -v`

## What works

- ✅ MQTT event and telemetry ingestion
- ✅ State machine with hysteresis (10s stop, 15s idle, 60s OFFLINE detection)
- ✅ Event deduplication via `(event_id, time)` unique index + device timestamps
- ✅ 6-panel Grafana dashboard with template variables
- ✅ Reproducible via `docker compose up -d`

## Quick start

```bash
git clone https://github.com/ovais-durrani/iiot-garment-factory-showcase.git
cd iiot-garment-factory-showcase
cp .env.example .env       # then edit .env with your passwords
docker compose up -d
python3 simulator/sim_machines.py --start-state RUNNING --force-event-every 10 &

# Open Grafana at http://localhost:3000
# Login: admin / (password from .env)
