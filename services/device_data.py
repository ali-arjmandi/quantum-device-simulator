"""Device payload generation by type (sensor, actuator, satellite payload) with optional noise and drift."""
import json
import math
import random
import time
from typing import Any

# Default intervals (seconds) per device type
_INTERVAL_SENSOR = 1.0
_INTERVAL_ACTUATOR = 2.0
_INTERVAL_PAYLOAD = 0.5

# Drift/noise parameters
_NOISE_SIGMA = 0.15
_DRIFT_AMPLITUDE = 2.0
_ACTUATOR_STATES = ("on", "ready", "standby")


def _simulator_config(metadata: dict | None) -> dict:
    """Return simulator_config with defaults for noise and drift."""
    cfg = (metadata or {}).get("simulator_config") or {}
    return {
        "noise": cfg.get("noise", False),
        "drift": cfg.get("drift", False),
    }


def _add_noise(value: float, sigma: float = _NOISE_SIGMA) -> float:
    return value + random.gauss(0, sigma)


def _drift_offset(device_id: str, timestamp: float, amplitude: float = _DRIFT_AMPLITUDE) -> float:
    """Slow drift based on time and device_id for variety."""
    return amplitude * math.sin(timestamp * 0.1 + hash(device_id) % 100 / 100.0 * math.pi * 2)


def get_payload(
    device_id: str,
    device_type: str,
    metadata: dict | None,
    timestamp: float,
) -> tuple[dict, float]:
    """Generate one payload dict and interval_sec. Uses simulator_config for noise/drift."""
    config = _simulator_config(metadata)
    noise_on = config["noise"]
    drift_on = config["drift"]
    ts = timestamp

    if device_type == "sensor":
        base_temp = 25.0 + (hash(device_id) % 10) / 10.0
        if drift_on:
            base_temp += _drift_offset(device_id, ts)
        temp = _add_noise(base_temp, _NOISE_SIGMA) if noise_on else base_temp
        humidity = (40.0 + (hash(device_id) % 20) / 10.0)
        if drift_on:
            humidity += _drift_offset(device_id, ts * 0.7) * 0.5
        if noise_on:
            humidity = _add_noise(humidity, _NOISE_SIGMA * 2)
        payload = {
            "type": "sensor",
            "device_id": device_id,
            "temp": round(temp, 2),
            "humidity": round(humidity, 2),
            "ts": round(ts, 2),
        }
        return payload, _INTERVAL_SENSOR

    if device_type == "actuator":
        seq = int(ts) % 100000
        state = _ACTUATOR_STATES[seq % len(_ACTUATOR_STATES)]
        payload = {
            "type": "actuator",
            "device_id": device_id,
            "state": state,
            "seq": seq,
            "ts": round(ts, 2),
        }
        return payload, _INTERVAL_ACTUATOR

    if device_type == "satellite payload":
        base_alt = 1200.0 + (hash(device_id) % 100)
        base_lat = 45.0 + (hash(device_id) % 10) / 10.0
        base_lon = -93.0 - (hash(device_id) % 10) / 10.0
        if drift_on:
            base_alt += _drift_offset(device_id, ts) * 50
            base_lat += _drift_offset(device_id, ts * 0.8) * 0.1
            base_lon += _drift_offset(device_id, ts * 0.6) * 0.1
        alt = base_alt
        lat = base_lat
        lon = base_lon
        if noise_on:
            alt = _add_noise(alt, _NOISE_SIGMA * 20)
            lat = _add_noise(lat, _NOISE_SIGMA * 0.5)
            lon = _add_noise(lon, _NOISE_SIGMA * 0.5)
        payload = {
            "type": "payload",
            "device_id": device_id,
            "alt": round(alt, 2),
            "lat": round(lat, 4),
            "lon": round(lon, 4),
            "ts": round(ts, 2),
        }
        return payload, _INTERVAL_PAYLOAD

    # Fallback: treat as sensor
    base_temp = 25.0 + (hash(device_id) % 10) / 10.0
    if drift_on:
        base_temp += _drift_offset(device_id, ts)
    temp = _add_noise(base_temp, _NOISE_SIGMA) if noise_on else base_temp
    payload = {
        "type": "sensor",
        "device_id": device_id,
        "temp": round(temp, 2),
        "ts": round(ts, 2),
    }
    return payload, _INTERVAL_SENSOR


def format_serial(payload: dict) -> str:
    """Format payload as a single line for Serial (PTY). Ends with newline."""
    ptype = payload.get("type", "sensor")
    if ptype == "sensor":
        temp = payload.get("temp", 0)
        ts = payload.get("ts", 0)
        if "humidity" in payload:
            return f"SENSOR,TEMP,{temp},HUM,{payload['humidity']},TS,{ts}\n"
        return f"SENSOR,TEMP,{temp},TS,{ts}\n"
    if ptype == "actuator":
        return f"ACTUATOR,STATE,{payload.get('state', '')},SEQ,{payload.get('seq', 0)},TS,{payload.get('ts', 0)}\n"
    if ptype == "payload":
        return "PAYLOAD,ALT,{alt},LAT,{lat},LON,{lon},TS,{ts}\n".format(
            alt=payload.get("alt", 0),
            lat=payload.get("lat", 0),
            lon=payload.get("lon", 0),
            ts=payload.get("ts", 0),
        )
    return f"SENSOR,TEMP,{payload.get('temp', 0)},TS,{payload.get('ts', 0)}\n"


def format_tcp(payload: dict) -> str:
    """Format payload as a JSON line for TCP. Ends with newline."""
    return json.dumps(payload) + "\n"
