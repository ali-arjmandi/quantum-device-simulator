"""Connection-type-specific field definitions and form parsing.

Builds and validates device.metadata["connection_params"] from request.form
for each connection type (Serial, TCP/IP).
Provides random valid sample params for the create-device form.
"""
import random
from typing import Any

# Connection type values as used in forms and Device.connection_type
CONNECTION_TYPES = ("Serial", "TCP/IP")

# Per-type: list of (form_field_name, param_key, type_coerce, required)
# param_key = key in connection_params dict; type_coerce = callable or None (str)
def _int(s: str) -> int | None:
    if s is None or (isinstance(s, str) and s.strip() == ""):
        return None
    try:
        return int(s.strip(), 0)  # 0 allows 0x48 for hex
    except (ValueError, TypeError):
        return None


def _str(s: Any) -> str:
    if s is None:
        return ""
    return str(s).strip()


# Serial: PTY path is chosen at runtime; port/address input removed. Baud/data/stop/parity are metadata only.
SERIAL_SPEC = [
    ("conn_baud_rate", "baud_rate", lambda s: _int(s) if s else None, False),
    ("conn_data_bits", "data_bits", lambda s: _int(s) if s else None, False),
    ("conn_stop_bits", "stop_bits", lambda s: _int(s) if s else None, False),
    ("conn_parity", "parity", _str, False),
]

TCP_SPEC = [
    ("conn_host", "host", _str, True),
    ("conn_tcp_port", "port", lambda s: _int(s) if s else None, True),
]

SPEC_BY_TYPE = {
    "Serial": SERIAL_SPEC,
    "TCP/IP": TCP_SPEC,
}


def _get_form_value(form: Any, field_name: str) -> str | None:
    """Get a single value from a form-like object (e.g. request.form)."""
    if hasattr(form, "get"):
        return form.get(field_name)
    return None


def parse_connection_params(connection_type: str, form: Any) -> dict[str, Any]:
    """Build connection_params dict from form for the given connection_type.

    Only fields for that type are read. Unknown types return {}.
    No validation is performed; use validate_connection_params for that.
    """
    spec = SPEC_BY_TYPE.get(connection_type)
    if not spec:
        return {}
    params: dict[str, Any] = {}
    for form_name, param_key, coerce, _required in spec:
        raw = _get_form_value(form, form_name)
        value = coerce(raw) if coerce else _str(raw)
        # Omit None and empty string for optional fields; include for required
        if value is not None and value != "":
            params[param_key] = value
    return params


def validate_connection_params(connection_type: str, params: dict[str, Any]) -> list[str]:
    """Validate connection_params for the given type. Returns list of error messages."""
    errors: list[str] = []
    spec = SPEC_BY_TYPE.get(connection_type)
    if not spec:
        return errors
    for _form_name, param_key, _coerce, required in spec:
        value = params.get(param_key)
        if required and (value is None or value == ""):
            errors.append(f"Missing required field: {param_key}")
    # Optional numeric ranges
    if connection_type == "Serial":
        baud = params.get("baud_rate")
        if baud is not None and (not isinstance(baud, int) or baud < 1 or baud > 921600):
            errors.append("Baud rate must be between 1 and 921600")
        data_bits = params.get("data_bits")
        if data_bits is not None and data_bits not in (7, 8, None):
            errors.append("Data bits must be 7 or 8")
        stop_bits = params.get("stop_bits")
        if stop_bits is not None and stop_bits not in (1, 2, None):
            errors.append("Stop bits must be 1 or 2")
    return errors


def generate_sample_connection_params(connection_type: str) -> dict[str, Any]:
    """Generate random but valid connection_params for the given type.

    Used to pre-fill the create-device form so users see valid example values.
    All values conform to validate_connection_params for that type.
    """
    if connection_type == "Serial":
        return {
            "baud_rate": random.choice([9600, 19200, 38400, 57600, 115200]),
            "data_bits": random.choice([7, 8]),
            "stop_bits": random.choice([1, 2]),
            "parity": random.choice(["", "Even", "Odd"]),
        }
    if connection_type == "TCP/IP":
        return {
            "host": "127.0.0.1",
            "port": random.randint(1024, 65535),
        }
    return {}


def get_all_sample_connection_params() -> dict[str, dict[str, Any]]:
    """Return random valid connection_params for every connection type.

    Keys are connection type names (e.g. 'Serial', 'TCP/IP'). Values are
    connection_params dicts suitable for form pre-fill and pass
    validate_connection_params.
    """
    return {
        conn_type: generate_sample_connection_params(conn_type)
        for conn_type in CONNECTION_TYPES
    }


def format_connection_summary(connection_type: str, connection_params: dict[str, Any] | None) -> str:
    """Return a short human-readable summary for the device list.

    Examples: "COM3 @ 115200", "192.168.1.10:502".
    Returns "—" when connection_params is missing or empty.
    """
    if not connection_params:
        return "—"
    if connection_type == "Serial":
        # PTY path is shown at runtime in Connection column when device is on
        baud = connection_params.get("baud_rate")
        if baud is not None:
            return f"Serial @ {baud}"
        return "Serial"
    if connection_type == "TCP/IP":
        port = connection_params.get("port")
        if port is not None:
            return f"127.0.0.1:{port}"
        return "—"
    return "—"
