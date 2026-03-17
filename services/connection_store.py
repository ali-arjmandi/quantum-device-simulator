"""Connection store: persist client connections (Serial/TCP) to JSON."""
import json
import os
from dataclasses import asdict

from models.connection import Connection

_connections: dict[str, Connection] = {}
_data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
_file_path = os.path.normpath(os.path.join(_data_dir, "connections.json"))


def _load() -> None:
    """Load connections from JSON file."""
    if not os.path.isfile(_file_path):
        return
    try:
        with open(_file_path, encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError):
        return
    _connections.clear()
    for d in data:
        try:
            conn = Connection(
                id=d["id"],
                name=d["name"],
                connection_type=d["connection_type"],
                address=d["address"],
                device_id=d.get("device_id"),
                metadata=d.get("metadata"),
            )
            _connections[conn.id] = conn
        except (KeyError, TypeError):
            continue


def _save() -> None:
    """Write _connections to JSON file."""
    os.makedirs(_data_dir, exist_ok=True)
    data = [asdict(c) for c in _connections.values()]
    with open(_file_path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def get_all_connections() -> list[Connection]:
    """Return all connections in insertion order."""
    return list(_connections.values())


def get_connection(connection_id: str) -> Connection | None:
    """Return the connection by id, or None."""
    return _connections.get(connection_id)


def add_connection(connection: Connection) -> None:
    """Add a connection and persist."""
    _connections[connection.id] = connection
    _save()


def update_connection(connection_id: str, **kwargs) -> None:
    """Update a connection by id. Accepts keyword args for Connection fields."""
    conn = _connections.get(connection_id)
    if conn is None:
        return
    for key, value in kwargs.items():
        if hasattr(conn, key):
            setattr(conn, key, value)
    _save()


def delete_connection(connection_id: str) -> bool:
    """Remove a connection by id. Returns True if removed."""
    if connection_id not in _connections:
        return False
    del _connections[connection_id]
    _save()
    return True


_load()
