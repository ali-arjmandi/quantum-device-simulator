"""Dashboard blueprint and routes."""
import uuid

from flask import Blueprint, abort, redirect, render_template, request, url_for

from models.device import Device
from services.store import (
    add_device as store_add_device,
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
    return render_template("dashboard/simulator.html", devices=devices)


@bp.route("/simulator/device/add", methods=["POST"])
def add_device():
    """Create a new device and redirect back to simulator."""
    name = request.form.get("name", "").strip()
    device_type = request.form.get("device_type", "").strip()
    connection_type = request.form.get("connection_type", "").strip()
    powered_on = request.form.get("powered_on") == "on"
    device = Device(
        id=uuid.uuid4().hex,
        name=name or "Unnamed",
        device_type=device_type or "sensor",
        connection_type=connection_type or "Serial",
        powered_on=powered_on,
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
