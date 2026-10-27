#!/usr/bin/env python3
"""
simulator/sim_machines.py — Garment Factory IIoT machine simulator

Emits MQTT messages matching data-contract-v1.0.0 §6:
    factory/{line_id}/machine/{machine_id}/power      (QoS 0, every 5 s)
    factory/{line_id}/machine/{machine_id}/heartbeat  (QoS 0, every 30 s)
    factory/{line_id}/machine/{machine_id}/event      (QoS 1, on transitions)

Fixes vs the original Phase 0 code:
    1. STOPPED -> RUNNING transition (machines no longer stuck forever).
    2. uptime_s tracked per-machine from thread start (was Unix epoch).
    3. energy_kwh is now per-sample delta in kWh (was off by ~300x).
    4. duration_in_previous_state_s actually reflects elapsed time.
    5. --start-state flag to control initial state.
    6. --force-event-every N for pipeline debugging.
    7. --source flag to set the "source" field on every payload.
    8. --quiet flag for load testing (suppresses per-message logging).
    9. Graceful shutdown on SIGINT / SIGTERM.

NOTE on STATE_CHANGE source:
    In PRODUCTION, STATE_CHANGE events are emitted by Node-RED
    (see data-contract-v1.0.0 §6.4), not by devices. In Phase 0 this
    simulator plays the role of both device AND state machine, so it
    emits STATE_CHANGE with source=--source (default "simulator").

    tools/validate_contract.py enforces source="node-red" for
    STATE_CHANGE (§6.4). If you want the simulator to pass strict
    validation, run with --source node-red. Otherwise the validator
    will flag simulator-sourced STATE_CHANGE as a warning — which is
    correct: the value is a Phase 0 shortcut, not a production signal.

Usage:
    python3 simulator/sim_machines.py
    python3 simulator/sim_machines.py --start-state RUNNING
    python3 simulator/sim_machines.py --force-event-every 10
    python3 simulator/sim_machines.py --source node-red --quiet
    python3 simulator/sim_machines.py --broker 10.0.0.10 --port 1883
"""

from __future__ import annotations

import argparse
import json
import random
import signal
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Optional

import paho.mqtt.client as mqtt


# ─── Configuration ──────────────────────────────────────────────────────────
LINES = {"L01": ["L01-M01", "L01-M02", "L01-M03"]}

POWER_INTERVAL_S     = 5
HEARTBEAT_INTERVAL_S = 30

# Current draw per state (Amps) — used to make power samples realistic.
CURRENT_BASE = {
    "RUNNING": 3.2,
    "IDLE":    0.4,
    "STOPPED": 0.1,
    "FAULT":   0.0,
}
PF_BASE = {
    "RUNNING": 0.95,
    "IDLE":    0.50,
    "STOPPED": 0.50,
    "FAULT":   0.00,
}


# ─── Helpers ────────────────────────────────────────────────────────────────
def now_iso() -> str:
    """ISO 8601 UTC, millisecond precision, ending in 'Z' (contract §6.0)."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


QUIET = False

def log(msg: str) -> None:
    """Timestamped console output; suppressed when --quiet."""
    if QUIET:
        return
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}", flush=True)


def make_job_id(year: int, seq: int) -> str:
    """JOB-YYYY-NNNNN per contract §3."""
    return f"JOB-{year}-{seq:05d}"


# ─── Payload builders (match data-contract-v1.0.0 §6) ──────────────────────
def power_payload(mid: str, lid: str, state: str, source: str,
                  energy_delta_kwh: float) -> dict:
    """§6.1 Power sample."""
    base = CURRENT_BASE[state]
    cur  = max(0.0, base + random.gauss(0, 0.15))
    volt = 230 + random.gauss(0, 1.2)
    pf   = PF_BASE[state]
    return {
        "schema_version": 1,
        "timestamp": now_iso(),
        "machine_id": mid,
        "line_id": lid,
        "source": source,
        "voltage_v": round(volt, 1),
        "current_a": round(cur, 2),
        "power_w": round(volt * cur * pf, 1),
        "energy_kwh": round(energy_delta_kwh, 6),
        "power_factor": pf,
        "frequency_hz": 50.0,
        "quality": "good",
    }


def heartbeat_payload(mid: str, lid: str, source: str, uptime_s: int) -> dict:
    """§6.6 Heartbeat."""
    return {
        "schema_version": 1,
        "timestamp": now_iso(),
        "machine_id": mid,
        "line_id": lid,
        "source": source,
        "uptime_s": uptime_s,
        "free_heap_b": 145000,
        "rssi_dbm": -62,
        "buffered_events": 0,
    }


def event_payload(mid: str, lid: str, etype: str,
                  prev_state: str, new_state: str,
                  source: str, extra: Optional[dict] = None) -> dict:
    """§6.2–6.4 Event (JOB_COMPLETE / FAULT / STATE_CHANGE)."""
    return {
        "schema_version": 1,
        "event_id": str(uuid.uuid4()),
        "timestamp": now_iso(),
        "machine_id": mid,
        "line_id": lid,
        "event_type": etype,
        "source": source,
        "payload": extra or {},
        "previous_state": prev_state,
        "new_state": new_state,
    }


# ─── Per-machine simulation ────────────────────────────────────────────────
def machine_thread(client: mqtt.Client, mid: str, lid: str,
                   initial_state: str, force_event_every: Optional[int],
                   source: str) -> None:
    state                  = initial_state
    state_since_tick       = time.time()
    start_tick             = time.time()
    last_heartbeat_tick    = 0.0
    last_forced_event_tick = 0.0
    job_seq                = 1000
    energy_accum_kwh       = 0.0    # cumulative since thread start

    topic_power     = f"factory/{lid}/machine/{mid}/power"
    topic_heartbeat = f"factory/{lid}/machine/{mid}/heartbeat"
    topic_event     = f"factory/{lid}/machine/{mid}/event"

    log(f"START {mid} state={state}")

    while True:
        tick = time.time()

        # ─── 1. Compute this tick's energy delta (correct math) ────────
        # Sample represents POWER_INTERVAL_S seconds of consumption.
        # delta_kwh = power_w * dt_s / (1000 W/kW * 3600 s/h)
        state_for_sample = state  # sample captures current state's draw
        base_i = CURRENT_BASE[state_for_sample]
        cur_now = max(0.0, base_i + random.gauss(0, 0.15))
        volt_now = 230 + random.gauss(0, 1.2)
        pf_now = PF_BASE[state_for_sample]
        power_w_now = volt_now * cur_now * pf_now
        energy_delta_kwh = power_w_now * POWER_INTERVAL_S / 3_600_000.0
        energy_accum_kwh += energy_delta_kwh

        # ─── 2. Publish power sample (QoS 0) ───────────────────────────
        client.publish(
            topic_power,
            json.dumps(power_payload(mid, lid, state, source,
                                     energy_delta_kwh)),
            qos=0,
        )

        # ─── 3. Publish heartbeat every 30 s (QoS 0) ───────────────────
        if tick - last_heartbeat_tick >= HEARTBEAT_INTERVAL_S:
            client.publish(
                topic_heartbeat,
                json.dumps(heartbeat_payload(mid, lid, source,
                                             int(tick - start_tick))),
                qos=0,
            )
            last_heartbeat_tick = tick

        # ─── 4. Forced JOB_COMPLETE (debug only) ───────────────────────
        if force_event_every and (tick - last_forced_event_tick) >= force_event_every:
            job_seq += 1
            jid = make_job_id(datetime.now().year, job_seq)
            client.publish(
                topic_event,
                json.dumps(event_payload(
                    mid, lid, "JOB_COMPLETE", state, state, source, {
                        "job_id": jid,
                        "operator_id": "OP-042",
                        "garment_sku": "TSHIRT-BLK-L",
                        "quantity": 1,
                    },
                )),
                qos=1,
            )
            log(f"JOB_COMPLETE {mid} job={jid}")
            last_forced_event_tick = tick

        # ─── 5. Random state transitions ───────────────────────────────
        r = random.random()
        new_state = None
        reason = None

        if state == "STOPPED":
            # FIX: machines MUST be able to leave STOPPED.
            if r < 0.30:
                new_state = "RUNNING"
                reason = "job_started"

        elif state == "RUNNING":
            if r < 0.06:
                new_state = "IDLE"
                reason = "operator_pause"
            elif r > 0.985:
                new_state = "FAULT"
                reason = "fault_relay"

        elif state == "IDLE":
            if r < 0.25:
                new_state = "RUNNING"
                reason = "resume"
            elif r > 0.95:
                new_state = "STOPPED"
                reason = "stop_debounce"

        elif state == "FAULT":
            if r < 0.40:
                new_state = "IDLE"
                reason = "fault_cleared"

        if new_state:
            duration_s = int(tick - state_since_tick)
            if new_state == "FAULT":
                event = event_payload(
                    mid, lid, "FAULT", state, new_state, source, {
                        "fault_code": "E-102",
                        "fault_description": "Needle break",
                        "severity": "critical",
                    },
                )
            else:
                event = event_payload(
                    mid, lid, "STATE_CHANGE", state, new_state, source, {
                        "reason": reason,
                        "duration_in_previous_state_s": duration_s,
                    },
                )
            client.publish(topic_event, json.dumps(event), qos=1)
            log(f"STATE {mid} {state} -> {new_state} ({reason}, was {duration_s}s)")
            state = new_state
            state_since_tick = tick

        # ─── 6. Random JOB_COMPLETE while RUNNING (~1 per 90 s) ────────
        if state == "RUNNING" and random.random() < 0.055:
            job_seq += 1
            jid = make_job_id(datetime.now().year, job_seq)
            client.publish(
                topic_event,
                json.dumps(event_payload(
                    mid, lid, "JOB_COMPLETE", state, state, source, {
                        "job_id": jid,
                        "operator_id": "OP-042",
                        "garment_sku": "TSHIRT-BLK-L",
                        "quantity": 1,
                    },
                )),
                qos=1,
            )
            log(f"JOB_COMPLETE {mid} job={jid}")

        time.sleep(POWER_INTERVAL_S)


# ─── Main ──────────────────────────────────────────────────────────────────
def main() -> int:
    global QUIET

    ap = argparse.ArgumentParser(
        description="Simulate garment-factory sewing machines over MQTT.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--broker", default="localhost",
                    help="MQTT broker hostname (default: localhost)")
    ap.add_argument("--port", type=int, default=1883,
                    help="MQTT broker port (default: 1883)")
    ap.add_argument("--start-state", default="RUNNING",
                    choices=["STOPPED", "IDLE", "RUNNING"],
                    help="Initial state for all machines (default: RUNNING)")
    ap.add_argument("--force-event-every", type=int, default=None,
                    metavar="SECONDS",
                    help="Emit a synthetic JOB_COMPLETE every N seconds per "
                         "machine (for pipeline debugging)")
    ap.add_argument("--source", default="simulator",
                    help="Value for the 'source' field on every payload "
                         "(default: simulator). Use 'node-red' if you want "
                         "STATE_CHANGE events to pass strict validation.")
    ap.add_argument("--client-id", default="simulator",
                    help="MQTT client ID (default: simulator)")
    ap.add_argument("--quiet", action="store_true",
                    help="Suppress per-message logging (for load tests)")
    args = ap.parse_args()

    QUIET = args.quiet

    # ─── MQTT setup ───
    client = mqtt.Client(client_id=args.client_id, protocol=mqtt.MQTTv311)
    try:
        client.connect(args.broker, args.port, keepalive=60)
    except Exception as e:
        log(f"ERROR: cannot connect to {args.broker}:{args.port} — {e}")
        return 2
    client.loop_start()
    log(f"Connected to {args.broker}:{args.port} as {args.client_id!r}")

    # ─── Spawn one thread per machine ───
    threads = []
    for lid, machines in LINES.items():
        for mid in machines:
            t = threading.Thread(
                target=machine_thread,
                args=(client, mid, lid, args.start_state,
                      args.force_event_every, args.source),
                daemon=True,
                name=mid,
            )
            t.start()
            threads.append(t)

    log(
        f"Simulating {len(threads)} machines. "
        f"start_state={args.start_state} "
        f"force_event_every={args.force_event_every or 'off'} "
        f"source={args.source!r} "
        f"quiet={args.quiet}"
    )

    # ─── Graceful shutdown ───
    stop = threading.Event()

    def shutdown(signum, _frame):
        log(f"signal {signum} received, shutting down...")
        stop.set()

    signal.signal(signal.SIGINT,  shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    try:
        stop.wait()   # blocks until signal
    finally:
        client.loop_stop()
        client.disconnect()
        log("Simulator stopped.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
