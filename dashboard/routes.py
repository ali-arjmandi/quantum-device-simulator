"""Dashboard blueprint and routes."""
import json
import queue
import time
import uuid
from dataclasses import asdict

from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, Response, stream_with_context, url_for

from config.connection_specs import (
    get_all_sample_connection_params,
    parse_connection_params,
    validate_connection_params,
)
from models.device import Device
from services.connection_manager import (
    check_device_health,
    get_last_payload,
    get_or_create_monitor_queue,
    start_device as manager_start_device,
    stop_device as manager_stop_device,
    unregister_monitor_queue,
    update_simulator_config_shared,
)
from services.device_logs import append_log as device_logs_append, get_logs as get_device_logs
from services.store import (
    add_device as store_add_device,
    delete_device as store_delete_device,
    get_all_devices,
    get_device,
    update_device,
)

bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


@bp.route("/")
def index():
    """Dashboard index."""
    return render_template("dashboard/index.html")


@bp.route("/simulator", methods=["GET"])
def simulator():
    """Device simulator (admin) page with device list."""
    devices = get_all_devices()
    return render_template(
        "dashboard/simulator.html",
        devices=devices,
    )


@bp.route("/simulator/device/new", methods=["GET"])
def new_device():
    """Show create-device form."""
    sample_params_by_type = get_all_sample_connection_params()
    return render_template(
        "dashboard/simulator_create.html",
        sample_params_by_type=sample_params_by_type,
    )


@bp.route("/simulator/device/add", methods=["POST"])
def add_device():
    """Create a new device and redirect back to simulator."""
    name = request.form.get("name", "").strip()
    device_type = request.form.get("device_type", "").strip()
    connection_type = request.form.get("connection_type", "").strip() or "Serial"
    powered_on = request.form.get("powered_on") == "on"
    connection_params = parse_connection_params(connection_type, request.form)
    if connection_type == "TCP/IP":
        connection_params["host"] = "127.0.0.1"
    errors = validate_connection_params(connection_type, connection_params)
    if errors:
        for msg in errors:
            flash(msg, "error")
        return redirect(url_for("dashboard.simulator"))
    metadata = {"connection_params": connection_params}
    device = Device(
        id=uuid.uuid4().hex,
        name=name or "Unnamed",
        device_type=device_type or "sensor",
        connection_type=connection_type,
        powered_on=powered_on,
        metadata=metadata,
    )
    store_add_device(device)
    if powered_on:
        if not manager_start_device(device):
            device_logs_append(device.id, "error", "Could not start device (e.g. port in use).", "error")
            update_device(device.id, powered_on=False)
            flash("Could not start device (e.g. port in use).", "error")
    return redirect(url_for("dashboard.simulator"))


@bp.route("/simulator/device/<device_id>/toggle", methods=["POST"])
def toggle_device(device_id: str):
    """Toggle powered_on for a device and redirect back to simulator."""
    device = get_device(device_id)
    if device is None:
        abort(404)
    new_powered_on = not device.powered_on
    update_device(device_id, powered_on=new_powered_on)
    if new_powered_on:
        updated = get_device(device_id)
        if updated and not manager_start_device(updated):
            device_logs_append(device_id, "error", "Could not start device (e.g. port in use).", "error")
            update_device(device_id, powered_on=False)
            flash("Could not start device (e.g. port in use).", "error")
    else:
        manager_stop_device(device_id)
    return redirect(url_for("dashboard.simulator"))


@bp.route("/simulator/device/<device_id>/edit", methods=["GET", "POST"])
def edit_device(device_id: str):
    """Show edit form (GET) or update device (POST) and redirect to simulator."""
    device = get_device(device_id)
    if device is None:
        abort(404)
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        device_type = request.form.get("device_type", "").strip()
        connection_type = request.form.get("connection_type", "").strip() or "Serial"
        powered_on = request.form.get("powered_on") == "on"
        connection_params = parse_connection_params(connection_type, request.form)
        if connection_type == "TCP/IP":
            connection_params["host"] = "127.0.0.1"
        errors = validate_connection_params(connection_type, connection_params)
        if errors:
            for msg in errors:
                flash(msg, "error")
            return redirect(url_for("dashboard.edit_device", device_id=device_id))
        existing_metadata = device.metadata if device.metadata else {}
        metadata = {**existing_metadata, "connection_params": connection_params}
        update_device(
            device_id,
            name=name or "Unnamed",
            device_type=device_type or "sensor",
            connection_type=connection_type,
            powered_on=powered_on,
            metadata=metadata,
        )
        device_logs_append(
            device_id,
            "device_updated",
            "Device configuration updated.",
            level="info",
        )
        if powered_on:
            updated = get_device(device_id)
            if updated and not manager_start_device(updated):
                device_logs_append(device_id, "error", "Could not start device (e.g. port in use).", "error")
                update_device(device_id, powered_on=False)
                flash("Could not start device (e.g. port in use).", "error")
        else:
            manager_stop_device(device_id)
        return redirect(url_for("dashboard.simulator"))
    return render_template("dashboard/simulator_edit.html", device=device)


@bp.route("/simulator/device/<device_id>/health", methods=["GET"])
def device_health(device_id: str):
    """Return device health status as JSON (for health checker)."""
    device = get_device(device_id)
    if device is None:
        return jsonify({"status": "unknown", "message": "Device not found"}), 404
    result = check_device_health(device_id, device.powered_on)
    return jsonify(result)


@bp.route("/simulator/device/<device_id>/simulator-config", methods=["GET"])
def get_simulator_config(device_id: str):
    """Return current simulator_config for the device (for UI sync)."""
    device = get_device(device_id)
    if device is None:
        return jsonify({"message": "Device not found"}), 404
    config = (device.metadata or {}).get("simulator_config", {})
    return jsonify(config)


@bp.route("/simulator/device/<device_id>/simulator-config", methods=["PATCH"])
def patch_simulator_config(device_id: str):
    """Update simulator options (noise, drift); apply in real time for running devices."""
    device = get_device(device_id)
    if device is None:
        return jsonify({"ok": False, "message": "Device not found"}), 404
    data = request.get_json(silent=True) or {}
    noise = data.get("noise")
    drift = data.get("drift")
    metadata = dict(device.metadata) if device.metadata else {}
    sim_config = dict(metadata.get("simulator_config", {}))
    if noise is not None:
        sim_config["noise"] = bool(noise)
    if drift is not None:
        sim_config["drift"] = bool(drift)
    metadata["simulator_config"] = sim_config
    update_device(device_id, metadata=metadata)
    if getattr(device, "connection_type", "") == "TCP/IP" and device.powered_on:
        update_simulator_config_shared(
            device_id,
            getattr(device, "device_type", "") or "sensor",
            sim_config,
        )
    return jsonify({"ok": True})


@bp.route("/simulator/health", methods=["GET"])
def all_devices_health():
    """Return health status for all devices as JSON (for polling)."""
    devices = get_all_devices()
    result = {}
    for device in devices:
        health = check_device_health(device.id, device.powered_on)
        health["powered_on"] = device.powered_on
        result[device.id] = health
    return jsonify(result)


@bp.route("/simulator/device/<device_id>/logs")
def device_logs(device_id: str):
    """Show monitoring logs for a device."""
    device = get_device(device_id)
    if device is None:
        abort(404)
    logs = get_device_logs(device_id, limit=200)
    return render_template(
        "dashboard/simulator_logs.html",
        device=device,
        logs=logs,
    )


@bp.route("/simulator/device/<device_id>/logs/json")
def device_logs_json(device_id: str):
    """Return device logs as JSON (for polling or infinite scroll)."""
    device = get_device(device_id)
    if device is None:
        return jsonify({"error": "Device not found"}), 404
    logs = get_device_logs(device_id, limit=200)
    return jsonify([asdict(log) for log in logs])


def _logs_stream_generator(device_id: str, after: float | None):
    """Yield SSE events: optional snapshot, then new log entries every second."""
    if after is None:
        logs = get_device_logs(device_id, limit=200)
        arr = [asdict(log) for log in logs]
        yield f"event: snapshot\ndata: {json.dumps(arr)}\n\n"
        last_ts = max((log.timestamp or 0) for log in logs) if logs else 0.0
    else:
        last_ts = after
    while True:
        time.sleep(1)
        try:
            logs = get_device_logs(device_id, limit=200)
            new_logs = [log for log in logs if (log.timestamp or 0) > last_ts]
            for log in sorted(new_logs, key=lambda l: -(l.timestamp or 0)):
                yield f"event: log\ndata: {json.dumps(asdict(log))}\n\n"
                last_ts = max(last_ts, log.timestamp or 0)
            if new_logs:
                last_ts = max(log.timestamp or 0 for log in new_logs)
        except GeneratorExit:
            break
        except Exception:
            break


@bp.route("/simulator/device/<device_id>/logs/stream")
def device_logs_stream(device_id: str):
    """Server-Sent Events stream of device logs (real-time)."""
    device = get_device(device_id)
    if device is None:
        abort(404)
    after = request.args.get("after", type=float)
    return Response(
        stream_with_context(_logs_stream_generator(device_id, after)),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _monitor_stream_generator(device_id: str):
    """Yield SSE events: optional initial snapshot, then each new payload from the queue.
    Sends a data-event heartbeat every 15s when idle so proxies don't close the connection.
    """
    initial = get_last_payload(device_id)
    if initial is not None:
        try:
            yield f"data: {json.dumps(initial, default=str)}\n\n"
        except Exception:
            pass
    monitor_queue = get_or_create_monitor_queue(device_id)
    try:
        yield f"data: {json.dumps({'status': 'connected'})}\n\n"
        heartbeat_interval = 15
        while True:
            try:
                data = monitor_queue.get(timeout=heartbeat_interval)
                try:
                    yield f"data: {json.dumps(data, default=str)}\n\n"
                except Exception:
                    pass
            except queue.Empty:
                try:
                    yield f"data: {json.dumps({'heartbeat': True})}\n\n"
                except Exception:
                    pass
            except GeneratorExit:
                raise
            except Exception:
                try:
                    yield f"data: {json.dumps({'heartbeat': True})}\n\n"
                except Exception:
                    pass
    finally:
        unregister_monitor_queue(device_id, monitor_queue)


@bp.route("/simulator/device/<device_id>/monitor")
def device_monitor_page(device_id: str):
    """Monitor page: show live payload stream for the device."""
    device = get_device(device_id)
    if device is None:
        abort(404)
    return render_template("dashboard/simulator_monitor.html", device=device)


@bp.route("/simulator/device/<device_id>/monitor/stream")
def device_monitor_stream(device_id: str):
    """Server-Sent Events stream of generated payloads (real-time)."""
    device = get_device(device_id)
    if device is None:
        abort(404)
    return Response(
        stream_with_context(_monitor_stream_generator(device_id)),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@bp.route("/simulator/device/<device_id>/delete", methods=["POST"])
def delete_device(device_id: str):
    """Delete a device and redirect back to simulator."""
    manager_stop_device(device_id)
    if not store_delete_device(device_id):
        abort(404)
    return redirect(url_for("dashboard.simulator"))
