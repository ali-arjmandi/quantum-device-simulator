"""In-memory device store."""
from models.device import Device

_devices: dict[str, Device] = {}


def get_all_devices() -> list[Device]:
    """Return all devices in insertion order."""
    return list(_devices.values())


def get_device(device_id: str) -> Device | None:
    """Return the device with the given id, or None if not found."""
    return _devices.get(device_id)


def add_device(device: Device) -> None:
    """Add a device to the store."""
    _devices[device.id] = device


def update_device(device_id: str, **kwargs) -> None:
    """Update a device by id. Accepts keyword args for Device fields (e.g. powered_on)."""
    device = _devices.get(device_id)
    if device is None:
        return
    for key, value in kwargs.items():
        if hasattr(device, key):
            setattr(device, key, value)
