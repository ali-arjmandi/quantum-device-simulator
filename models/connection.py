"""Connection model - saved client connection config (Serial or TCP) to any device."""
from dataclasses import dataclass
from typing import Optional


@dataclass
class Connection:
    """Represents a saved connection config to connect to a device (Serial or TCP/IP).
    address: for Serial, the port path (e.g. /dev/ttys002); for TCP, "host:port" or use metadata host/port.
    """

    id: str
    name: str
    connection_type: str  # "Serial" | "TCP/IP"
    address: str  # Serial: path; TCP: "host:port" or host in metadata
    device_id: Optional[str] = None  # optional link e.g. for quick-add from simulator
    metadata: Optional[dict] = None  # e.g. host, port, baud_rate, chart_keys
