"""Dashboard blueprint and routes."""
import uuid

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for

from config.connection_specs import (
    get_all_sample_connection_params,
    parse_connection_params,
    validate_connection_params,
)
from models.device import Device
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
    sample_params_by_type = get_all_sample_connection_params()
    return render_template(
        "dashboard/simulator.html",
        devices=devices,
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
    return redirect(url_for("dashboard.simulator"))


@bp.route("/simulator/device/<device_id>/toggle", methods=["POST"])
def toggle_device(device_id: str):
    """Toggle powered_on for a device and redirect back to simulator."""
    device = get_device(device_id)
    if device is None:
        abort(404)
    update_device(device_id, powered_on=not device.powered_on)
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
        return redirect(url_for("dashboard.simulator"))
    return render_template("dashboard/simulator_edit.html", device=device)


@bp.route("/simulator/device/<device_id>/delete", methods=["POST"])
def delete_device(device_id: str):
    """Delete a device and redirect back to simulator."""
    if not store_delete_device(device_id):
        abort(404)
    return redirect(url_for("dashboard.simulator"))
