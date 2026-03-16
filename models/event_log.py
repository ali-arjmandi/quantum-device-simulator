"""Event log model - placeholder in-memory structure."""
from dataclasses import dataclass
from typing import Optional


@dataclass
class EventLog:
    """Represents a log entry for debugging (device events, connection events, etc.)."""

    id: str
    device_id: Optional[str] = None
    event_type: str = ""
    message: str = ""
    level: str = "info"  # e.g. info, warning, error
    timestamp: Optional[float] = None
    metadata: Optional[dict] = None
