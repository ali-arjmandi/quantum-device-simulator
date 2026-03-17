"""In-memory per-device event log store for monitoring (connection, errors, disconnect, etc.)."""
import threading
import time
import uuid
from collections import deque

from models.event_log import EventLog

# device_id -> deque of EventLog (newest at index 0), max 200 per device
_logs: dict[str, deque[EventLog]] = {}
_lock = threading.Lock()
_MAX_LOGS_PER_DEVICE = 200


def append_log(
    device_id: str,
    event_type: str,
    message: str,
    level: str = "info",
    metadata: dict | None = None,
) -> None:
    """Append a log entry for the device. Thread-safe."""
    entry = EventLog(
        id=uuid.uuid4().hex,
        device_id=device_id,
        event_type=event_type,
        message=message,
        level=level or "info",
        timestamp=time.time(),
        metadata=metadata or None,
    )
    with _lock:
        if device_id not in _logs:
            _logs[device_id] = deque(maxlen=_MAX_LOGS_PER_DEVICE)
        _logs[device_id].appendleft(entry)


def get_logs(device_id: str, limit: int = 100) -> list[EventLog]:
    """Return newest-first log entries for the device. Thread-safe."""
    with _lock:
        queue = _logs.get(device_id)
        if not queue:
            return []
        return list(queue)[:limit]
