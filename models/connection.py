"""Connection model - placeholder in-memory structure."""
from dataclasses import dataclass
from typing import Optional


@dataclass
class Connection:
    """Represents a connection to a device (Serial, TCP, USB, I2C, SPI, etc.)."""

    id: str
    device_id: str
    connection_type: str  # e.g. "serial", "tcp", "usb", "i2c", "spi"
    address: str  # port, host:port, path, etc.
    connected: bool = False
    metadata: Optional[dict] = None
