#!/usr/bin/env python3
"""
validate_contract.py — Conformance validator for Garment Factory IIoT Data Contract v1.0.0
Document ID: DC-IIOT-001

Validates any MQTT payload (power, event, state, heartbeat, command) against
the frozen contract in docs/data-contract-v1.md.

Usage:
    # Single payload from stdin
    echo '{"schema_version":1,...}' | python3 tools/validate_contract.py

    # Explicit mode (auto-detected if omitted)
    python3 tools/validate_contract.py --type power < payload.json
    python3 tools/validate_contract.py --type event < payload.json
    python3 tools/validate_contract.py --type state < payload.json
    python3 tools/validate_contract.py --type heartbeat < payload.json
    python3 tools/validate_contract.py --type cmd < payload.json

    # Validate a JSONL file (one payload per line)
    python3 tools/validate_contract.py --file samples.jsonl

    # Subscribe live from MQTT broker and validate every message
    python3 tools/validate_contract.py --mqtt localhost --topic 'factory/#'

Exit codes:
    0 = all payloads valid
    1 = at least one payload invalid
    2 = usage / IO error

Requires: Python 3.9+. No third-party packages.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from datetime import datetime, timezone
from typing import Any

# ─────────────────────────────────────────────────────────────────────────────
# §3 Naming conventions (frozen)
# ─────────────────────────────────────────────────────────────────────────────
LINE_RE      = re.compile(r"^L[0-9]{2}$")
MACHINE_RE   = re.compile(r"^L[0-9]{2}-M[0-9]{2}$")
JOB_RE       = re.compile(r"^JOB-[0-9]{4}-[0-9]{5}$")
OP_RE        = re.compile(r"^OP-[0-9]{3,5}$")
FAULT_RE     = re.compile(r"^E-[0-9]{3}$")
SKU_RE       = re.compile(r"^[A-Z0-9]+(-[A-Z0-9]+)+$")

# §4.1 State model (frozen)
VALID_STATES = {"RUNNING", "IDLE", "STOPPED", "FAULT", "OFFLINE"}

# §6.4 STATE_CHANGE reason enum
VALID_REASONS = {
    "run_debounce", "idle_debounce", "stop_debounce",
    "fault_relay", "fault_cleared",
    "heartbeat_lost", "heartbeat_restored",
    "manual_override",
}

# §7 Fault codes (initial catalogue — extend as real codes are learned)
VALID_FAULT_CODES = {f"E-{i:03d}" for i in range(101, 111)}
VALID_SEVERITIES  = {"critical", "warning", "info"}

# §6.7 Command enum
VALID_COMMANDS = {"REBOOT", "FLUSH_BUFFER", "SET_JOB"}

# §6.1 Power quality enum
VALID_QUALITY = {"good", "suspect", "bad"}

# §6.2–6.4 Event types
VALID_EVENT_TYPES = {"JOB_COMPLETE", "FAULT", "STATE_CHANGE"}


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────
def is_iso8601_utc(s: Any) -> bool:
    """Accept `YYYY-MM-DDTHH:MM:SS.sssZ` and `...Z` without milliseconds."""
    if not isinstance(s, str):
        return False
    if not s.endswith("Z"):
        return False
    try:
        # Python 3.11+ handles 'Z' natively; for 3.9/3.10 replace it.
        datetime.fromisoformat(s.replace("Z", "+00:00"))
        return True
    except ValueError:
        return False


def is_uuid4(s: Any) -> bool:
    if not isinstance(s, str):
        return False
    try:
        u = uuid.UUID(s)
        return u.version == 4
    except (ValueError, AttributeError):
        return False


def is_number(v: Any) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def is_number_in(v: Any, lo: float, hi: float) -> bool:
    return is_number(v) and lo <= v <= hi


def require(p: dict, key: str, errs: list[str], label: str | None = None) -> None:
    """Require key to be present (any value, including null)."""
    if key not in p:
        errs.append(f"missing required field '{label or key}'")


def require_str(p: dict, key: str, errs: list[str], label: str | None = None) -> None:
    require(p, key, errs, label)
    if key in p and not isinstance(p[key], str):
        errs.append(f"field '{label or key}' must be a string")


def require_number(p: dict, key: str, errs: list[str],
                   lo: float | None = None, hi: float | None = None,
                   label: str | None = None) -> None:
    require(p, key, errs, label)
    if key not in p:
        return
    v = p[key]
    if not is_number(v):
        errs.append(f"field '{label or key}' must be a number")
        return
    if lo is not None and v < lo:
        errs.append(f"field '{label or key}' = {v} below minimum {lo}")
    if hi is not None and v > hi:
        errs.append(f"field '{label or key}' = {v} above maximum {hi}")


# ─────────────────────────────────────────────────────────────────────────────
# §6 universal envelope
# ─────────────────────────────────────────────────────────────────────────────
def validate_envelope(p: dict, errs: list[str]) -> None:
    if not isinstance(p, dict):
        errs.append("payload is not a JSON object")
        return

    # schema_version
    require(p, "schema_version", errs)
    if "schema_version" in p:
        if not isinstance(p["schema_version"], int) or isinstance(p["schema_version"], bool):
            errs.append("'schema_version' must be an integer")
        elif p["schema_version"] != 1:
            errs.append(f"unsupported schema_version={p['schema_version']} (only 1 supported)")

    # timestamp
    require(p, "timestamp", errs)
    if "timestamp" in p and not is_iso8601_utc(p["timestamp"]):
        errs.append("'timestamp' must be ISO 8601 UTC ending in 'Z'")

    # machine_id
    require_str(p, "machine_id", errs)
    if "machine_id" in p and isinstance(p["machine_id"], str):
        if not MACHINE_RE.match(p["machine_id"]):
            errs.append(f"'machine_id'={p['machine_id']!r} does not match ^L[0-9]{{2}}-M[0-9]{{2}}$")

    # line_id
    require_str(p, "line_id", errs)
    if "line_id" in p and isinstance(p["line_id"], str):
        if not LINE_RE.match(p["line_id"]):
            errs.append(f"'line_id'={p['line_id']!r} does not match ^L[0-9]{{2}}$")

    # source
    require_str(p, "source", errs)


# ─────────────────────────────────────────────────────────────────────────────
# §6.1 Power sample
# ─────────────────────────────────────────────────────────────────────────────
def validate_power(p: dict) -> list[str]:
    errs: list[str] = []
    validate_envelope(p, errs)

    require_number(p, "voltage_v", errs, lo=0, hi=300)
    require_number(p, "current_a", errs, lo=0, hi=50)
    require_number(p, "power_w",   errs, lo=0, hi=15000)

    # optional fields
    if "energy_kwh" in p:
        require_number(p, "energy_kwh", errs, lo=0)
    if "power_factor" in p:
        require_number(p, "power_factor", errs, lo=0, hi=1)
    if "frequency_hz" in p:
        require_number(p, "frequency_hz", errs, lo=45, hi=65)

    # quality
    require_str(p, "quality", errs)
    if "quality" in p and isinstance(p["quality"], str) and p["quality"] not in VALID_QUALITY:
        errs.append(f"'quality'={p['quality']!r} not in {sorted(VALID_QUALITY)}")

    return errs


# ─────────────────────────────────────────────────────────────────────────────
# §6.2–6.4 Event
# ─────────────────────────────────────────────────────────────────────────────
def validate_event(p: dict) -> list[str]:
    errs: list[str] = []
    validate_envelope(p, errs)

    # event_id
    require(p, "event_id", errs)
    if "event_id" in p and not is_uuid4(p["event_id"]):
        errs.append("'event_id' must be a UUID v4 string")

    # event_type
    require_str(p, "event_type", errs)
    event_type = p.get("event_type") if isinstance(p.get("event_type"), str) else None
    if event_type is not None and event_type not in VALID_EVENT_TYPES:
        errs.append(f"'event_type'={event_type!r} not in {sorted(VALID_EVENT_TYPES)}")
        return errs  # can't validate payload without known type

    # previous_state / new_state
    for key in ("previous_state", "new_state"):
        require_str(p, key, errs)
        if key in p and isinstance(p[key], str) and p[key] not in VALID_STATES:
            errs.append(f"'{key}'={p[key]!r} not in {sorted(VALID_STATES)}")

    # payload (required, object)
    require(p, "payload", errs)
    if "payload" not in p:
        return errs
    payload = p["payload"]
    if not isinstance(payload, dict):
        errs.append("'payload' must be a JSON object")
        return errs

    # per-event-type payload rules
    if event_type == "JOB_COMPLETE":
        require_str(payload, "job_id", errs, label="payload.job_id")
        if "job_id" in payload and isinstance(payload["job_id"], str):
            if not JOB_RE.match(payload["job_id"]):
                errs.append(f"'payload.job_id'={payload['job_id']!r} does not match ^JOB-[0-9]{{4}}-[0-9]{{5}}$")

        require(payload, "operator_id", errs, label="payload.operator_id")
        if "operator_id" in payload:
            v = payload["operator_id"]
            if v is not None:
                if not isinstance(v, str):
                    errs.append("'payload.operator_id' must be a string or null")
                elif not OP_RE.match(v):
                    errs.append(f"'payload.operator_id'={v!r} does not match ^OP-[0-9]{{3,5}}$")

        require_str(payload, "garment_sku", errs, label="payload.garment_sku")
        if "garment_sku" in payload and isinstance(payload["garment_sku"], str):
            if not SKU_RE.match(payload["garment_sku"]):
                errs.append(f"'payload.garment_sku'={payload['garment_sku']!r} does not match SKU pattern")

        require(payload, "quantity", errs, label="payload.quantity")
        if "quantity" in payload:
            if not isinstance(payload["quantity"], int) or isinstance(payload["quantity"], bool):
                errs.append("'payload.quantity' must be an integer")
            elif payload["quantity"] < 1:
                errs.append("'payload.quantity' must be >= 1")

    elif event_type == "FAULT":
        require_str(payload, "fault_code", errs, label="payload.fault_code")
        if "fault_code" in payload and isinstance(payload["fault_code"], str):
            fc = payload["fault_code"]
            if not FAULT_RE.match(fc):
                errs.append(f"'payload.fault_code'={fc!r} does not match ^E-[0-9]{{3}}$")
            elif fc not in VALID_FAULT_CODES:
                # Not a hard failure — the catalogue is extensible; warn only.
                print(f"  WARN: fault_code {fc!r} is not in the v1 catalogue (§7); "
                      f"update the contract if this is a real code.", file=sys.stderr)

        require_str(payload, "fault_description", errs, label="payload.fault_description")
        require_str(payload, "severity", errs, label="payload.severity")
        if "severity" in payload and isinstance(payload["severity"], str):
            if payload["severity"] not in VALID_SEVERITIES:
                errs.append(f"'payload.severity'={payload['severity']!r} not in {sorted(VALID_SEVERITIES)}")

    elif event_type == "STATE_CHANGE":
        require_str(payload, "reason", errs, label="payload.reason")
        if "reason" in payload and isinstance(payload["reason"], str):
            if payload["reason"] not in VALID_REASONS:
                errs.append(f"'payload.reason'={payload['reason']!r} not in {sorted(VALID_REASONS)}")

        require(payload, "duration_in_previous_state_s", errs,
                label="payload.duration_in_previous_state_s")
        if "duration_in_previous_state_s" in payload:
            v = payload["duration_in_previous_state_s"]
            if not is_number(v) or v < 0:
                errs.append("'payload.duration_in_previous_state_s' must be a non-negative number")

        # STATE_CHANGE is emitted by Node-RED only
        if p.get("source") != "node-red":
            errs.append("'source' must be 'node-red' for STATE_CHANGE events (§6.4)")

    return errs


# ─────────────────────────────────────────────────────────────────────────────
# §6.5 State (retained)
# ─────────────────────────────────────────────────────────────────────────────
def validate_state(p: dict) -> list[str]:
    errs: list[str] = []
    validate_envelope(p, errs)

    require_str(p, "state", errs)
    if "state" in p and isinstance(p["state"], str) and p["state"] not in VALID_STATES:
        errs.append(f"'state'={p['state']!r} not in {sorted(VALID_STATES)}")

    require(p, "state_since", errs)
    if "state_since" in p and not is_iso8601_utc(p["state_since"]):
        errs.append("'state_since' must be ISO 8601 UTC ending in 'Z'")

    require(p, "last_event_time", errs)
    if "last_event_time" in p and not is_iso8601_utc(p["last_event_time"]):
        errs.append("'last_event_time' must be ISO 8601 UTC ending in 'Z'")

    # These are nullable but must be present as keys
    for k in ("job_id", "operator_id", "fault_code"):
        require(p, k, errs)
        if p.get(k) is not None and not isinstance(p[k], str):
            errs.append(f"'{k}' must be a string or null")

    return errs


# ─────────────────────────────────────────────────────────────────────────────
# §6.6 Heartbeat
# ─────────────────────────────────────────────────────────────────────────────
def validate_heartbeat(p: dict) -> list[str]:
    errs: list[str] = []
    validate_envelope(p, errs)

    # buffered_events is required (resilience monitoring)
    require(p, "buffered_events", errs)
    if "buffered_events" in p:
        if not isinstance(p["buffered_events"], int) or isinstance(p["buffered_events"], bool):
            errs.append("'buffered_events' must be an integer")
        elif p["buffered_events"] < 0:
            errs.append("'buffered_events' must be >= 0")

    # optional fields
    if "uptime_s" in p:
        v = p["uptime_s"]
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            errs.append("'uptime_s' must be a non-negative integer")
    if "free_heap_b" in p:
        v = p["free_heap_b"]
        if not isinstance(v, int) or isinstance(v, bool) or v < 0:
            errs.append("'free_heap_b' must be a non-negative integer")
    if "rssi_dbm" in p:
        v = p["rssi_dbm"]
        if not isinstance(v, int) or isinstance(v, bool):
            errs.append("'rssi_dbm' must be an integer")
        elif not (-120 <= v <= 0):
            errs.append("'rssi_dbm' should be between -120 and 0")

    return errs


# ─────────────────────────────────────────────────────────────────────────────
# §6.7 Command
# ─────────────────────────────────────────────────────────────────────────────
def validate_cmd(p: dict) -> list[str]:
    errs: list[str] = []
    validate_envelope(p, errs)

    require(p, "command_id", errs)
    if "command_id" in p:
        # command_id may be UUID or any unique string in v1; enforce UUID if it looks like one
        v = p["command_id"]
        if not isinstance(v, str) or not v:
            errs.append("'command_id' must be a non-empty string")

    require_str(p, "command", errs)
    if "command" in p and isinstance(p["command"], str):
        if p["command"] not in VALID_COMMANDS:
            errs.append(f"'command'={p['command']!r} not in {sorted(VALID_COMMANDS)}")

    # payload optional; if present must be object
    if "payload" in p and not isinstance(p["payload"], dict):
        errs.append("'payload' must be a JSON object if present")

    return errs


# ─────────────────────────────────────────────────────────────────────────────
# Auto-detection
# ─────────────────────────────────────────────────────────────────────────────
def detect_type(p: dict) -> str:
    """Best-effort inference when --type is omitted."""
    if not isinstance(p, dict):
        return "unknown"
    if "event_type" in p:
        return "event"
    if "power_w" in p or "voltage_v" in p or "current_a" in p:
        return "power"
    if "state" in p and "state_since" in p:
        return "state"
    if "buffered_events" in p or "uptime_s" in p:
        return "heartbeat"
    if "command" in p:
        return "cmd"
    return "unknown"


VALIDATORS = {
    "power":     validate_power,
    "event":     validate_event,
    "state":     validate_state,
    "heartbeat": validate_heartbeat,
    "cmd":       validate_cmd,
}


def validate_payload(payload: Any, forced_type: str | None = None) -> tuple[bool, str]:
    """Returns (ok, message)."""
    if not isinstance(payload, dict):
        return False, "payload is not a JSON object"

    ptype = forced_type or detect_type(payload)
    if ptype == "unknown":
        return False, "unable to detect payload type (use --type)"

    validator = VALIDATORS.get(ptype)
    if validator is None:
        return False, f"unknown payload type {ptype!r}"

    errs = validator(payload)
    if errs:
        return False, f"[{ptype}] " + "; ".join(errs)
    return True, f"[{ptype}] OK"


# ─────────────────────────────────────────────────────────────────────────────
# Modes
# ─────────────────────────────────────────────────────────────────────────────
def run_stdin(forced_type: str | None) -> int:
    raw = sys.stdin.read()
    if not raw.strip():
        print("ERROR: no input on stdin", file=sys.stderr)
        return 2
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"INVALID JSON: {e}", file=sys.stderr)
        return 1
    ok, msg = validate_payload(payload, forced_type)
    print(("VALID" if ok else "INVALID") + ": " + msg)
    return 0 if ok else 1


def run_file(path: str, forced_type: str | None) -> int:
    total = 0
    failures = 0
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            total += 1
            try:
                payload = json.loads(line)
            except json.JSONDecodeError as e:
                failures += 1
                print(f"line {lineno}: INVALID JSON: {e}", file=sys.stderr)
                continue
            ok, msg = validate_payload(payload, forced_type)
            if not ok:
                failures += 1
                print(f"line {lineno}: INVALID: {msg}", file=sys.stderr)
    print(f"{total - failures}/{total} valid")
    return 0 if failures == 0 else 1


def run_mqtt(broker: str, port: int, topic: str, forced_type: str | None) -> int:
    try:
        import paho.mqtt.client as mqtt  # optional dependency
    except ImportError:
        print("ERROR: --mqtt requires 'paho-mqtt'. Install with:", file=sys.stderr)
        print("  pip install paho-mqtt", file=sys.stderr)
        return 2

    counter = {"total": 0, "failures": 0}

    def on_connect(client, userdata, flags, rc, properties=None):
        print(f"Connected to {broker}:{port} (rc={rc}); subscribing to {topic!r}",
              file=sys.stderr)
        client.subscribe(topic, qos=1)

    def on_message(client, userdata, msg):
        counter["total"] += 1
        try:
            payload = json.loads(msg.payload)
        except json.JSONDecodeError as e:
            counter["failures"] += 1
            print(f"[{msg.topic}] INVALID JSON: {e}", file=sys.stderr)
            return
        ok, vmsg = validate_payload(payload, forced_type)
        if not ok:
            counter["failures"] += 1
            print(f"[{msg.topic}] INVALID: {vmsg}", file=sys.stderr)

            # 1. PAHO V2 COMPATIBILITY (Must be first to create the 'client' object)
        try:
            client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="validate-contract")
        except AttributeError:
            # Fallback for Paho MQTT v1.x
            client = mqtt.Client(client_id="validate-contract")

        # 2. ASSIGN CALLBACKS (Now that 'client' safely exists)
        client.on_connect = on_connect
        client.on_message = on_message

        # 3. CONNECTION & LOOP ERROR HANDLING (Your upgraded try block)
        try:
            client.connect(broker, port, 60)
            client.loop_forever()
        except ConnectionRefusedError:
            print(f"ERROR: Connection refused. Is the broker running at {broker}:{port}?", file=sys.stderr)
            return 2
        except OSError as e:
            # Catches DNS failures, network unreachable, etc.
            print(f"ERROR: Network error connecting to {broker}:{port} -> {e}", file=sys.stderr)
            return 2
        except KeyboardInterrupt:
            # Graceful exit on Ctrl+C
            pass
        finally:
            # Ensure the network loop is cleanly stopped and disconnected
            client.loop_stop()
            client.disconnect()

        print(f"\n{counter['total'] - counter['failures']}/{counter['total']} valid")
        return 0 if counter["failures"] == 0 else 1


# ─────────────────────────────────────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser(
        description="Validate IIoT payloads against data-contract-v1.0.0."
    )
    ap.add_argument(
        "--type", choices=sorted(VALIDATORS.keys()),
        help="Force payload type (default: auto-detect)",
    )
    ap.add_argument(
        "--file", metavar="PATH",
        help="Validate a JSONL file (one payload per line)",
    )
    ap.add_argument(
        "--mqtt", metavar="BROKER",
        help="Subscribe to a broker and validate every message",
    )
    ap.add_argument(
        "--port", type=int, default=1883,
        help="MQTT broker port (default: 1883)",
    )
    ap.add_argument(
        "--topic", default="factory/#",
        help="MQTT topic filter (default: factory/#)",
    )
    args = ap.parse_args()

    if args.mqtt:
        return run_mqtt(args.mqtt, args.port, args.topic, args.type)
    if args.file:
        return run_file(args.file, args.type)
    return run_stdin(args.type)


if __name__ == "__main__":
    sys.exit(main())
