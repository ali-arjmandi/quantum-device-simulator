"""Device store with JSON file persistence."""
import json
import os
from dataclasses import asdict

from models.device import Device

_devices: dict[str, Device] = {}
_data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
_file_path = os.path.normpath(os.path.join(_data_dir, "devices.json"))


def _load() -> None:
    """Load devices from JSON file into _devices."""
    if not os.path.isfile(_file_path):
        return
    try:
        with open(_file_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return
    _devices.clear()
    for d in data:
        try:
            device = Device(
                id=d["id"],
                name=d["name"],
                device_type=d["device_type"],
                connection_type=d["connection_type"],
                powered_on=d.get("powered_on", False),
                metadata=d.get("metadata"),
            )
            _devices[device.id] = device
        except (KeyError, TypeError):
            continue


def _save() -> None:
    """Write _devices to JSON file."""
    os.makedirs(_data_dir, exist_ok=True)
    data = [asdict(device) for device in _devices.values()]
    with open(_file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_all_devices() -> list[Device]:
    """Return all devices in insertion order."""
    return list(_devices.values())


def get_device(device_id: str) -> Device | None:
    """Return the device with the given id, or None if not found."""
    return _devices.get(device_id)


def add_device(device: Device) -> None:
    """Add a device to the store and persist to file."""
    _devices[device.id] = device
    _save()


def update_device(device_id: str, **kwargs) -> None:
    """Update a device by id. Accepts keyword args for Device fields (e.g. powered_on)."""
    device = _devices.get(device_id)
    if device is None:
        return
    for key, value in kwargs.items():
        if hasattr(device, key):
            setattr(device, key, value)
    _save()


def delete_device(device_id: str) -> bool:
    """Remove a device by id. Returns True if removed, False if not found."""
    if device_id not in _devices:
        return False
    del _devices[device_id]
    _save()
    return True


_load()
