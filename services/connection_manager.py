"""Connection manager: starts/stops virtual Serial and TCP device simulators.

When a device is turned on, opens a virtual connection and runs a simulator thread.
When turned off, closes the connection and stops the thread.
"""
import logging
import socket
import threading
import time
from typing import Any

from models.device import Device

logger = logging.getLogger(__name__)

_active: dict[str, "_ActiveConnection"] = {}
_lock = threading.Lock()


class _ActiveConnection:
    """Holds resources for one active device connection."""

    def __init__(
        self,
        device_id: str,
        stop_event: threading.Event,
        thread: threading.Thread,
        close_handles: list[Any],
        connection_type: str = "",
    ):
        self.device_id = device_id
        self.stop_event = stop_event
        self.thread = thread
        self.close_handles = close_handles  # sockets etc. to close on stop
        self.connection_type = connection_type


def _serial_simulator_loop(device_end: socket.socket, stop_event: threading.Event, device_id: str) -> None:
    """Device side of virtual serial: send periodic fake data until stop."""
    try:
        device_end.settimeout(0.5)
        while not stop_event.is_set():
            try:
                # Send a line of fake sensor data every second
                line = f"SENSOR,TEMP,{25.0 + (hash(device_id) % 10) / 10:.1f}\n"
                device_end.sendall(line.encode("utf-8"))
            except (BrokenPipeError, OSError):
                break
            stop_event.wait(1.0)
    except Exception as e:
        logger.warning("Serial simulator thread for %s: %s", device_id, e)
    finally:
        try:
            device_end.close()
        except OSError:
            pass


def _tcp_server_loop(
    bind_host: str,
    port: int,
    device_id: str,
    stop_event: threading.Event,
    holder: dict,
) -> None:
    """Run a server at bind_host:port; when a client connects, stream device data to it."""
    listener = None
    client = None
    try:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.settimeout(0.5)
        listener.bind((bind_host, port))
        listener.listen(1)
        holder["listener"] = listener

        while not stop_event.is_set():
            try:
                client, _ = listener.accept()
                break
            except socket.timeout:
                continue
            except OSError:
                break

        if client is None:
            return
        holder["client"] = client
        client.settimeout(0.5)

        while not stop_event.is_set():
            try:
                line = f'{{"device_id":"{device_id}","temperature":25.3}}\n'
                client.sendall(line.encode("utf-8"))
            except (BrokenPipeError, OSError):
                break
            stop_event.wait(1.0)
    except OSError as e:
        logger.warning("TCP server for device %s (%s:%s): %s", device_id, bind_host, port, e)
    finally:
        for s in (client, listener):
            if s is not None:
                try:
                    s.close()
                except OSError:
                    pass


def start_device(device: Device) -> bool:
    """Start virtual connection and simulator for the device. Returns True if started."""
    params = None
    if getattr(device, "metadata", None) and isinstance(device.metadata, dict):
        params = device.metadata.get("connection_params") or {}

    connection_type = (getattr(device, "connection_type", "") or "").strip()
    if not connection_type:
        logger.warning("Device %s has no connection_type", device.id)
        return False

    with _lock:
        if device.id in _active:
            return True

    if connection_type == "Serial":
        # Virtual serial: socket pair; device thread on one end
        try:
            host_end, device_end = socket.socketpair()
        except OSError as e:
            logger.warning("Socket pair for device %s: %s", device.id, e)
            return False

        stop_event = threading.Event()
        thread = threading.Thread(
            target=_serial_simulator_loop,
            args=(device_end, stop_event, device.id),
            daemon=True,
        )
        thread.start()
        device_end.close()  # simulator holds its copy in the thread

        with _lock:
            _active[device.id] = _ActiveConnection(
                device_id=device.id,
                stop_event=stop_event,
                thread=thread,
                close_handles=[host_end],
                connection_type="Serial",
            )
        logger.info("Virtual Serial started for device %s", device.id)
        return True

    if connection_type == "TCP/IP":
        # Simulation only: server binds to 127.0.0.1 (localhost only)
        bind_host = "127.0.0.1"
        port = params.get("port")
        if port is None:
            logger.warning("TCP device %s missing port in connection_params", device.id)
            return False
        try:
            port = int(port)
        except (TypeError, ValueError):
            logger.warning("TCP device %s invalid port: %s", device.id, port)
            return False
        if not (1 <= port <= 65535):
            logger.warning("TCP device %s port out of range: %s", device.id, port)
            return False

        holder: dict = {}

        stop_event = threading.Event()
        thread = threading.Thread(
            target=_tcp_server_loop,
            args=(bind_host, port, device.id, stop_event, holder),
            daemon=True,
        )
        thread.start()

        # Wait briefly for server to start listening
        for _ in range(20):
            if stop_event.is_set():
                break
            time.sleep(0.05)
            if "listener" in holder:
                break
        else:
            stop_event.set()
            thread.join(timeout=2.0)
            logger.warning("TCP device %s could not bind to port %s (in use?)", device.id, port)
            return False

        with _lock:
            _active[device.id] = _ActiveConnection(
                device_id=device.id,
                stop_event=stop_event,
                thread=thread,
                close_handles=[holder.get("listener")],
                connection_type="TCP/IP",
            )
        logger.info(
            "TCP device %s: server running on 127.0.0.1:%s — connect your client to receive data",
            device.id, port,
        )
        return True

    logger.warning("Unknown connection_type %r for device %s", connection_type, device.id)
    return False


def stop_device(device_id: str) -> None:
    """Stop simulator and close connection for the device."""
    with _lock:
        conn = _active.pop(device_id, None)
    if conn is None:
        return
    conn.stop_event.set()
    for h in conn.close_handles:
        if h is not None:
            try:
                h.close()
            except OSError:
                pass
    conn.thread.join(timeout=2.0)
    logger.info("Stopped device %s", device_id)


def check_device_health(device_id: str, powered_on: bool) -> dict[str, str]:
    """Check if the device connection is actually working.

    Returns dict with keys: status ('healthy' | 'unhealthy' | 'off'), message.
    """
    if not powered_on:
        return {"status": "off", "message": "Device is off"}

    with _lock:
        conn = _active.get(device_id)

    if conn is None:
        return {"status": "unhealthy", "message": "Device is on but connection not active"}

    if conn.connection_type == "Serial":
        if conn.thread.is_alive():
            return {"status": "healthy", "message": "Serial simulator thread running"}
        return {"status": "unhealthy", "message": "Serial simulator thread stopped"}

    if conn.connection_type == "TCP/IP":
        listener = conn.close_handles[0] if conn.close_handles else None
        if listener is None:
            return {"status": "unhealthy", "message": "No listener socket"}
        if not conn.thread.is_alive():
            return {"status": "unhealthy", "message": "TCP server thread stopped"}
        try:
            port = listener.getsockname()[1]
        except OSError:
            return {"status": "unhealthy", "message": "Listener socket closed"}
        # Do not connect() here: the server accepts only one client; connecting would
        # become that client, and closing would break the server. Just verify listener is bound.
        return {"status": "healthy", "message": f"TCP server listening on port {port}"}

    return {"status": "unhealthy", "message": "Unknown connection type"}


def sync_from_store(devices: list[Device]) -> None:
    """Start connections for all powered_on devices; stop those no longer powered on."""
    powered_on_ids = {d.id for d in devices if getattr(d, "powered_on", False)}

    with _lock:
        active_ids = set(_active.keys())

    for device in devices:
        if device.powered_on and device.id not in active_ids:
            start_device(device)

    for did in active_ids:
        if did not in powered_on_ids:
            stop_device(did)
