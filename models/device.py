"""Device model - placeholder in-memory structure."""
from dataclasses import dataclass
from typing import Optional


@dataclass
class Device:
    """Represents a simulated quantum device."""

    id: str
    name: str
    device_type: str
    connection_type: str
    powered_on: bool = False
    # Optional metadata for later use
    metadata: Optional[dict] = None
