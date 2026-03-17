"""Connection manager: starts/stops virtual Serial and TCP device simulators.

When a device is turned on, opens a virtual connection and runs a simulator thread.
TCP devices run in a separate process so killing the process on the port does not stop the Flask app.
"""
import logging
import multiprocessing
import socket
import subprocess
import threading
import time
from typing import Any

from models.device import Device

from services import device_logs as device_logs_module

logger = logging.getLogger(__name__)


def _on_device_thread_exited(device_id: str) -> None:
    """Called when a simulator thread exits (error or normal). Remove from _active and sync store."""
    with _lock:
        conn = _active.pop(device_id, None)
    if conn is not None:
        device_logs_module.append_log(
            device_id,
            "disconnected",
            "Connection exited (process killed or error).",
            level="warning",
        )
        from services.store import update_device
        update_device(device_id, powered_on=False)
        logger.info("Device %s connection exited; set powered_on=False", device_id)

_active: dict[str, "_ActiveConnection"] = {}
_lock = threading.Lock()


def _kill_processes_on_port(port: int) -> None:
    """Kill processes using the given port (Unix: lsof + kill -9). No-op if none or on error."""
    try:
        out = subprocess.run(
            ["lsof", "-ti", f":{port}"],
            capture_output=True,
            text=True,
            timeout=5,
        )
        if out.returncode != 0 or not out.stdout or not out.stdout.strip():
            return
        pids = out.stdout.strip().split()
        for pid in pids:
            try:
                subprocess.run(["kill", "-9", pid], capture_output=True, timeout=2)
            except (subprocess.TimeoutExpired, OSError):
                pass
        if pids:
            logger.info("Killed process(es) on port %s: %s", port, pids)
    except (subprocess.TimeoutExpired, OSError, ValueError) as e:
        logger.debug("Could not kill processes on port %s: %s", port, e)


class _ActiveConnection:
    """Holds resources for one active device connection."""

    def __init__(
        self,
        device_id: str,
        stop_event: threading.Event | None,
        thread: threading.Thread,
        close_handles: list[Any],
        connection_type: str = "",
        tcp_port: int | None = None,
    ):
        self.device_id = device_id
        self.stop_event = stop_event
        self.thread = thread
        self.close_handles = close_handles  # sockets, or [Process] for TCP
        self.connection_type = connection_type
        self.tcp_port = tcp_port  # for TCP health message


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
        _on_device_thread_exited(device_id)


def _tcp_server_subprocess_target(port: int, device_id: str) -> None:
    """Run in a subprocess: bind to 127.0.0.1:port and serve clients until process is killed.
    If the process is killed (e.g. kill -9 on the port), only this process dies; Flask stays up.
    """
    bind_host = "127.0.0.1"
    listener = None
    try:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.settimeout(0.5)
        listener.bind((bind_host, port))
        listener.listen(1)
    except OSError:
        if listener:
            try:
                listener.close()
            except OSError:
                pass
        raise SystemExit(1)

    try:
        while True:
            client = None
            try:
                client, _ = listener.accept()
                client.settimeout(0.5)
                while True:
                    line = f'{{"device_id":"{device_id}","temperature":25.3}}\n'
                    client.sendall(line.encode("utf-8"))
                    time.sleep(1.0)
            except (BrokenPipeError, OSError):
                pass
            finally:
                if client is not None:
                    try:
                        client.close()
                    except OSError:
                        pass
    finally:
        try:
            listener.close()
        except OSError:
            pass


def _tcp_watcher_thread(process: multiprocessing.Process, device_id: str) -> None:
    """When the TCP subprocess dies (killed or we terminated it), clean up and sync store."""
    process.join()
    with _lock:
        conn = _active.pop(device_id, None)
    if conn is not None:
        device_logs_module.append_log(
            device_id,
            "disconnected",
            "Connection exited (process killed or error).",
            level="warning",
        )
        from services.store import update_device
        update_device(device_id, powered_on=False)
        logger.info("TCP device %s process ended; set powered_on=False", device_id)


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
        device_logs_module.append_log(
            device.id, "connection_started", "Serial simulator started.", level="info"
        )
        logger.info("Virtual Serial started for device %s", device.id)
        return True

    if connection_type == "TCP/IP":
        # Run TCP server in a subprocess so killing the process on the port does not stop the Flask app
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

        process: multiprocessing.Process | None = None
        for attempt in range(2):
            process = multiprocessing.Process(
                target=_tcp_server_subprocess_target,
                args=(port, device.id),
                daemon=True,
            )
            process.start()
            time.sleep(1.2)
            if process.exitcode is None:
                break
            if process.exitcode == 1:
                logger.warning("TCP device %s could not bind to port %s, trying to free port", device.id, port)
                _kill_processes_on_port(port)
                time.sleep(1.0)
            process = None

        if process is None or process.exitcode is not None:
            device_logs_module.append_log(
                device.id,
                "error",
                "Could not start: port in use?",
                level="error",
            )
            logger.warning("TCP device %s could not bind to port %s (in use?)", device.id, port)
            return False

        watcher = threading.Thread(
            target=_tcp_watcher_thread,
            args=(process, device.id),
            daemon=True,
        )
        watcher.start()

        with _lock:
            _active[device.id] = _ActiveConnection(
                device_id=device.id,
                stop_event=None,
                thread=watcher,
                close_handles=[process],
                connection_type="TCP/IP",
                tcp_port=port,
            )
        device_logs_module.append_log(
            device.id,
            "connection_started",
            f"TCP server listening on 127.0.0.1:{port}.",
            level="info",
        )
        logger.info(
            "TCP device %s: server running on 127.0.0.1:%s (in subprocess) — connect your client to receive data",
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
    device_logs_module.append_log(
        device_id, "connection_stopped", "Connection stopped.", level="info"
    )
    if conn.stop_event is not None:
        conn.stop_event.set()
    for h in conn.close_handles:
        if h is not None:
            try:
                if hasattr(h, "terminate"):
                    h.terminate()
                    h.join(timeout=2.0)
                else:
                    h.close()
            except OSError:
                pass
    conn.thread.join(timeout=2.0)
    logger.info("Stopped device %s", device_id)


def stop_all_devices() -> None:
    """Stop all active device connections (e.g. on app shutdown). Releases ports and joins threads."""
    with _lock:
        ids = list(_active.keys())
    for device_id in ids:
        stop_device(device_id)
    logger.info("Stopped all devices (%s)", len(ids))


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
        process = conn.close_handles[0] if conn.close_handles else None
        if process is None:
            return {"status": "unhealthy", "message": "No TCP process"}
        if not process.is_alive():
            return {"status": "unhealthy", "message": "TCP server process stopped"}
        port = getattr(conn, "tcp_port", None) or "?"
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
