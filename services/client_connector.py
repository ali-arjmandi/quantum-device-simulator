"""Client connector: connect to devices via Serial or TCP and stream received lines to subscribers."""
import logging
import queue
import socket
import threading
import time
from typing import Any

from services.connection_store import get_connection

logger = logging.getLogger(__name__)

_active: dict[str, dict[str, Any]] = {}  # connection_id -> {thread, stop_event, handle}
_connection_queues: dict[str, list[queue.Queue]] = {}
_lock = threading.Lock()


def _serial_reader_loop(connection_id: str, path: str, stop_event: threading.Event) -> None:
    """Read lines from Serial/PTY path and push to all subscriber queues."""
    handle = None
    try:
        handle = open(path, "rb")
        buffer = b""
        while not stop_event.is_set():
            try:
                chunk = handle.read(256)
                if not chunk:
                    stop_event.wait(0.1)
                    continue
                buffer += chunk
                while b"\n" in buffer or b"\r" in buffer:
                    line, sep, buffer = buffer.partition(b"\n")
                    if not sep:
                        line, sep, buffer = buffer.partition(b"\r")
                    if not sep:
                        break
                    try:
                        raw = (line + sep).decode("utf-8", errors="replace").strip()
                    except Exception:
                        raw = line.decode("utf-8", errors="replace").strip()
                    if raw:
                        data = {"raw": raw, "ts": time.time()}
                        with _lock:
                            for q in _connection_queues.get(connection_id, []):
                                try:
                                    q.put_nowait(data)
                                except Exception:
                                    pass
            except (OSError, BrokenPipeError) as e:
                logger.debug("Connection %s read error: %s", connection_id, e)
                break
    except Exception as e:
        logger.warning("Connection %s serial open/read failed: %s", connection_id, e)
    finally:
        if handle is not None:
            try:
                handle.close()
            except OSError:
                pass
        with _lock:
            _active.pop(connection_id, None)
            _connection_queues.pop(connection_id, None)


def _tcp_reader_loop(
    connection_id: str, host: str, port: int, stop_event: threading.Event
) -> None:
    """Read lines from TCP socket and push to all subscriber queues."""
    sock = None
    try:
        sock = socket.create_connection((host, port), timeout=10.0)
        sock.settimeout(0.5)
        buffer = b""
        while not stop_event.is_set():
            try:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                buffer += chunk
                while b"\n" in buffer or b"\r" in buffer:
                    line, sep, buffer = buffer.partition(b"\n")
                    if not sep:
                        line, sep, buffer = buffer.partition(b"\r")
                    if not sep:
                        break
                    try:
                        raw = (line + sep).decode("utf-8", errors="replace").strip()
                    except Exception:
                        raw = line.decode("utf-8", errors="replace").strip()
                    if raw:
                        data = {"raw": raw, "ts": time.time()}
                        with _lock:
                            for q in _connection_queues.get(connection_id, []):
                                try:
                                    q.put_nowait(data)
                                except Exception:
                                    pass
            except (socket.timeout, BlockingIOError):
                continue
            except (OSError, BrokenPipeError, ConnectionResetError) as e:
                logger.debug("Connection %s TCP read error: %s", connection_id, e)
                break
    except Exception as e:
        logger.warning("Connection %s TCP connect/read failed: %s", connection_id, e)
    finally:
        if sock is not None:
            try:
                sock.close()
            except OSError:
                pass
        with _lock:
            _active.pop(connection_id, None)
            _connection_queues.pop(connection_id, None)


def start_connection(connection_id: str) -> tuple[bool, str]:
    """Start the client connection (Serial or TCP). Returns (success, error_message)."""
    conn = get_connection(connection_id)
    if conn is None:
        return False, "Connection not found"
    with _lock:
        if connection_id in _active:
            return True, ""
        _connection_queues[connection_id] = []

    if conn.connection_type == "Serial":
        path = (conn.metadata or {}).get("path") or conn.address
        stop_event = threading.Event()
        thread = threading.Thread(
            target=_serial_reader_loop,
            args=(connection_id, path, stop_event),
            daemon=True,
        )
        thread.start()
        with _lock:
            _active[connection_id] = {"thread": thread, "stop_event": stop_event}
        return True, ""

    if conn.connection_type == "TCP/IP":
        host = (conn.metadata or {}).get("host")
        port = (conn.metadata or {}).get("port")
        if host is None or port is None:
            if ":" in conn.address:
                parts = conn.address.rsplit(":", 1)
                host = parts[0].strip()
                try:
                    port = int(parts[1].strip())
                except (ValueError, IndexError):
                    return False, "Invalid address (use host:port or set metadata)"
            else:
                return False, "TCP requires host and port (in address as host:port or in metadata)"
        if not isinstance(port, int):
            try:
                port = int(port)
            except (TypeError, ValueError):
                return False, "Port must be a number"
        stop_event = threading.Event()
        thread = threading.Thread(
            target=_tcp_reader_loop,
            args=(connection_id, host, port, stop_event),
            daemon=True,
        )
        thread.start()
        with _lock:
            _active[connection_id] = {"thread": thread, "stop_event": stop_event}
        return True, ""

    return False, f"Unknown connection type: {conn.connection_type}"


def stop_connection(connection_id: str) -> None:
    """Stop the client connection; push sentinel to subscriber queues then remove."""
    with _lock:
        entry = _active.get(connection_id)
        if entry is None:
            _connection_queues.pop(connection_id, None)
            return
        stop_event = entry.get("stop_event")
        thread = entry.get("thread")
        queues = list(_connection_queues.get(connection_id, []))
        _active.pop(connection_id, None)
        _connection_queues.pop(connection_id, None)
    for q in queues:
        try:
            q.put_nowait({"status": "disconnected"})
        except Exception:
            pass
    if stop_event is not None:
        stop_event.set()
    if thread is not None and thread.is_alive():
        thread.join(timeout=2.0)


def is_connected(connection_id: str) -> bool:
    """Return True if the client connection is active."""
    with _lock:
        return connection_id in _active


def get_or_create_stream_queue(connection_id: str) -> queue.Queue | None:
    """Return a queue for this connection's stream; start connection if not active. None if connection not found."""
    conn = get_connection(connection_id)
    if conn is None:
        return None
    with _lock:
        if connection_id not in _active:
            pass  # will start below
        else:
            qu = queue.Queue()
            _connection_queues.setdefault(connection_id, []).append(qu)
            return qu
    ok, _ = start_connection(connection_id)
    if not ok:
        return None
    with _lock:
        qu = queue.Queue()
        _connection_queues.setdefault(connection_id, []).append(qu)
        return qu


def unregister_stream_queue(connection_id: str, q: queue.Queue) -> None:
    """Remove a subscriber queue. If last subscriber, stop the connection."""
    with _lock:
        subs = _connection_queues.get(connection_id, [])
        if q in subs:
            subs.remove(q)
        if not subs:
            _connection_queues.pop(connection_id, None)
    if not subs:
        stop_connection(connection_id)
