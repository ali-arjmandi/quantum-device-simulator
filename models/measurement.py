"""Measurement model - placeholder in-memory structure."""
from dataclasses import dataclass
from typing import Any, Optional


@dataclass
class Measurement:
    """Represents a measurement or reading from a device."""

    id: str
    device_id: str
    metric_name: str
    value: Any
    unit: Optional[str] = None
    timestamp: Optional[float] = None
    metadata: Optional[dict] = None
