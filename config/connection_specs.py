"""Connection-type-specific field definitions and form parsing.

Builds and validates device.metadata["connection_params"] from request.form
for each connection type (Serial, TCP/IP, USB, I2C, SPI).
"""
from typing import Any

# Connection type values as used in forms and Device.connection_type
CONNECTION_TYPES = ("Serial", "TCP/IP", "USB", "I2C", "SPI")

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


SERIAL_SPEC = [
    ("conn_port", "port", _str, True),
    ("conn_baud_rate", "baud_rate", lambda s: _int(s) if s else None, True),
    ("conn_data_bits", "data_bits", lambda s: _int(s) if s else None, False),
    ("conn_stop_bits", "stop_bits", lambda s: _int(s) if s else None, False),
    ("conn_parity", "parity", _str, False),
]

TCP_SPEC = [
    ("conn_host", "host", _str, True),
    ("conn_tcp_port", "port", lambda s: _int(s) if s else None, True),
]

USB_SPEC = [
    ("conn_vendor_id", "vendor_id", _str, True),
    ("conn_product_id", "product_id", _str, True),
    ("conn_bus", "bus", _str, False),
    ("conn_device_path", "device_path", _str, False),
    ("conn_serial_number", "serial_number", _str, False),
]

I2C_SPEC = [
    ("conn_i2c_bus", "bus", lambda s: _int(s) if s else None, True),
    ("conn_i2c_address", "device_address", lambda s: _int(s) if s else None, False),
]

SPI_SPEC = [
    ("conn_spi_bus", "bus", _str, True),
    ("conn_spi_cs", "chip_select", _str, True),
    ("conn_spi_mode", "mode", lambda s: _int(s) if s is not None and str(s).strip() != "" else None, True),
    ("conn_spi_max_speed", "max_speed", lambda s: _int(s) if s else None, False),
    ("conn_spi_bit_order", "bit_order", _str, False),
]

SPEC_BY_TYPE = {
    "Serial": SERIAL_SPEC,
    "TCP/IP": TCP_SPEC,
    "USB": USB_SPEC,
    "I2C": I2C_SPEC,
    "SPI": SPI_SPEC,
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
    if connection_type == "I2C":
        addr = params.get("device_address")
        if addr is not None and isinstance(addr, int) and (addr < 0x03 or addr > 0x77):
            errors.append("I2C device address must be between 0x03 and 0x77 (7-bit)")
    if connection_type == "SPI":
        mode = params.get("mode")
        if mode is not None and (not isinstance(mode, int) or mode < 0 or mode > 3):
            errors.append("SPI mode must be 0, 1, 2, or 3")
    return errors
