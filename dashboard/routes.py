"""Dashboard blueprint and routes."""
import json
import os
import queue
import time
import uuid
from dataclasses import asdict

import markdown
from flask import Blueprint, abort, flash, jsonify, redirect, render_template, request, Response, stream_with_context, url_for

from config.connection_specs import (
    get_all_sample_connection_params,
    parse_connection_params,
    validate_connection_params,
)
from models.connection import Connection
from models.device import Device
from services.client_connector import (
    get_or_create_stream_queue,
    is_connected,
    start_connection as client_start_connection,
    stop_connection as client_stop_connection,
    unregister_stream_queue,
)
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
from services.connection_store import (
    add_connection as store_add_connection,
    delete_connection as store_delete_connection,
    get_all_connections,
    get_connection,
    update_connection as store_update_connection,
)
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


_DOCS_DIR = os.path.normpath(os.path.join(os.path.dirname(__file__), ".."))


@bp.route("/documentation")
@bp.route("/documentation/<path:filename>")
def documentation(filename="README.md"):
    """Render a markdown file from the documentation folder as HTML."""
    path = os.path.normpath(os.path.join(_DOCS_DIR, filename))
    docs_real = os.path.realpath(_DOCS_DIR)
    real_path = os.path.realpath(path)
    if not (real_path == docs_real or real_path.startswith(docs_real + os.sep)) or not os.path.isfile(real_path):
        abort(404)
    path = real_path
    try:
        with open(path, encoding="utf-8") as f:
            raw = f.read()
    except OSError:
        abort(404)
    html = markdown.markdown(raw, extensions=["extra", "codehilite"])
    return render_template("dashboard/documentation.html", content=html, filename=filename)


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


@bp.route("/simulator/device/<device_id>/add-to-connections", methods=["POST"])
def device_add_to_connections(device_id: str):
    """Quick-add: create a connection from this device (Serial path or TCP host:port) and redirect to connections."""
    device = get_device(device_id)
    if device is None:
        abort(404)
    params = (device.metadata or {}).get("connection_params") or {}
    if device.connection_type == "TCP/IP":
        host = params.get("host") or "127.0.0.1"
        port = params.get("port")
        if port is None:
            flash("Device has no TCP port configured.", "error")
            return redirect(url_for("dashboard.simulator"))
        address = f"{host}:{port}"
        metadata = {"host": str(host), "port": int(port)}
    else:
        health = check_device_health(device_id, device.powered_on)
        serial_path = health.get("serial_path") if isinstance(health, dict) else None
        if not serial_path and device.powered_on:
            flash("Serial path not available yet.", "error")
            return redirect(url_for("dashboard.simulator"))
        if not serial_path:
            flash("Power on the device first to get its Serial path, then add to connections.", "error")
            return redirect(url_for("dashboard.simulator"))
        address = serial_path
        metadata = {"path": serial_path}
    name = f"{device.name} (from simulator)"
    conn = Connection(
        id=uuid.uuid4().hex,
        name=name,
        connection_type=device.connection_type,
        address=address,
        device_id=device_id,
        metadata=metadata,
    )
    store_add_connection(conn)
    flash(f"Connection “{name}” added.", "success")
    return redirect(url_for("dashboard.connections_list"))


# --- Connections (client connections to any device: Serial or TCP) ---


@bp.route("/connections")
def connections_list():
    """List all saved connections."""
    conns = get_all_connections()
    return render_template("dashboard/connections.html", connections=conns)


@bp.route("/connections/new", methods=["GET"])
def connection_new():
    """Show form to add a new connection."""
    return render_template("dashboard/connection_new.html")


@bp.route("/connections/add", methods=["POST"])
def connection_add():
    """Create a new connection and redirect to list."""
    name = request.form.get("name", "").strip() or "Unnamed"
    connection_type = request.form.get("connection_type", "").strip() or "Serial"
    if connection_type == "Serial":
        address = request.form.get("conn_path", "").strip() or request.form.get("address", "").strip()
        if not address:
            flash("Serial path is required.", "error")
            return redirect(url_for("dashboard.connection_new"))
        metadata = {"path": address}
    else:
        host = request.form.get("conn_host", "").strip() or "127.0.0.1"
        port_s = request.form.get("conn_tcp_port", "").strip()
        if not port_s:
            flash("TCP port is required.", "error")
            return redirect(url_for("dashboard.connection_new"))
        try:
            port = int(port_s)
        except ValueError:
            flash("Port must be a number.", "error")
            return redirect(url_for("dashboard.connection_new"))
        address = f"{host}:{port}"
        metadata = {"host": host, "port": port}
    conn = Connection(
        id=uuid.uuid4().hex,
        name=name,
        connection_type=connection_type,
        address=address,
        device_id=None,
        metadata=metadata,
    )
    store_add_connection(conn)
    return redirect(url_for("dashboard.connections_list"))


@bp.route("/connections/<connection_id>/edit", methods=["GET", "POST"])
def connection_edit(connection_id: str):
    """Show edit form (GET) or update connection (POST)."""
    conn = get_connection(connection_id)
    if conn is None:
        abort(404)
    if request.method == "POST":
        name = request.form.get("name", "").strip() or "Unnamed"
        connection_type = request.form.get("connection_type", "").strip() or conn.connection_type
        if connection_type == "Serial":
            address = request.form.get("conn_path", "").strip() or request.form.get("address", "").strip()
            if not address:
                flash("Serial path is required.", "error")
                return redirect(url_for("dashboard.connection_edit", connection_id=connection_id))
            metadata = {"path": address}
        else:
            host = request.form.get("conn_host", "").strip() or "127.0.0.1"
            port_s = request.form.get("conn_tcp_port", "").strip()
            if not port_s:
                flash("TCP port is required.", "error")
                return redirect(url_for("dashboard.connection_edit", connection_id=connection_id))
            try:
                port = int(port_s)
            except ValueError:
                flash("Port must be a number.", "error")
                return redirect(url_for("dashboard.connection_edit", connection_id=connection_id))
            address = f"{host}:{port}"
            metadata = {"host": host, "port": port}
        store_update_connection(
            connection_id,
            name=name,
            connection_type=connection_type,
            address=address,
            metadata=metadata,
        )
        return redirect(url_for("dashboard.connections_list"))
    return render_template("dashboard/connection_edit.html", connection=conn)


@bp.route("/connections/<connection_id>/delete", methods=["POST"])
def connection_delete(connection_id: str):
    """Delete a connection; stop client if active."""
    client_stop_connection(connection_id)
    if not store_delete_connection(connection_id):
        abort(404)
    return redirect(url_for("dashboard.connections_list"))


@bp.route("/connections/<connection_id>/monitor")
def connection_monitor_page(connection_id: str):
    """Monitor page: live stream, charts, stats for this connection."""
    conn = get_connection(connection_id)
    if conn is None:
        abort(404)
    return render_template("dashboard/connection_monitor.html", connection=conn)


def _connection_stream_generator(connection_id: str):
    """Yield SSE events: each received line with timestamp; heartbeat when idle."""
    stream_queue = get_or_create_stream_queue(connection_id)
    if stream_queue is None:
        yield f"data: {json.dumps({'status': 'error', 'message': 'Connection not found or failed to start'})}\n\n"
        return
    try:
        yield f"data: {json.dumps({'status': 'connected'})}\n\n"
        heartbeat_interval = 15
        while True:
            try:
                data = stream_queue.get(timeout=heartbeat_interval)
                if data.get("status") == "disconnected":
                    yield f"data: {json.dumps(data)}\n\n"
                    return
                yield f"data: {json.dumps(data, default=str)}\n\n"
            except queue.Empty:
                yield f"data: {json.dumps({'heartbeat': True})}\n\n"
            except GeneratorExit:
                raise
            except Exception:
                yield f"data: {json.dumps({'heartbeat': True})}\n\n"
    finally:
        unregister_stream_queue(connection_id, stream_queue)


@bp.route("/connections/<connection_id>/stream")
def connection_stream(connection_id: str):
    """SSE stream of received lines for this connection."""
    if get_connection(connection_id) is None:
        abort(404)
    return Response(
        stream_with_context(_connection_stream_generator(connection_id)),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@bp.route("/connections/<connection_id>/status")
def connection_status(connection_id: str):
    """JSON status (connected/disconnected) for the connection."""
    if get_connection(connection_id) is None:
        return jsonify({"status": "unknown", "message": "Connection not found"}), 404
    return jsonify({"status": "connected" if is_connected(connection_id) else "disconnected"})


@bp.route("/connections/<connection_id>/connect", methods=["POST"])
def connection_connect(connection_id: str):
    """Start the client connection (idempotent). Redirect to monitor or return JSON."""
    conn = get_connection(connection_id)
    if conn is None:
        abort(404)
    ok, err = client_start_connection(connection_id)
    if request.accept_mimetypes.best_match(["application/json", "text/html"]) == "application/json":
        return jsonify({"ok": ok, "error": err or None})
    if not ok:
        flash(err or "Failed to connect", "error")
        return redirect(url_for("dashboard.connections_list"))
    redirect_to = request.args.get("redirect")
    if redirect_to == "monitor":
        return redirect(url_for("dashboard.connection_monitor_page", connection_id=connection_id))
    return redirect(url_for("dashboard.connections_list"))


@bp.route("/connections/<connection_id>/disconnect", methods=["POST"])
def connection_disconnect(connection_id: str):
    """Stop the client connection."""
    if get_connection(connection_id) is None:
        abort(404)
    client_stop_connection(connection_id)
    if request.accept_mimetypes.best_match(["application/json", "text/html"]) == "application/json":
        return jsonify({"ok": True})
    return redirect(url_for("dashboard.connections_list"))
