"""Quantum Device Simulator - minimal Flask app."""

__version__ = "1.0.1"

import os
import signal
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv
from flask import Flask, redirect, url_for

from config.connection_specs import format_connection_summary
from dashboard import dashboard_bp
from services.connection_manager import stop_all_devices, sync_from_store
from services.store import get_all_devices

load_dotenv()


if "FLASK_RUN_RELOAD" not in os.environ:
    os.environ["FLASK_RUN_RELOAD"] = "0"

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")


def _shutdown_connections() -> None:
    """Close all device connections on exit."""
    stop_all_devices()


def _on_sigint_sigterm(_signum: int, _frame) -> None:
    """Handle Ctrl+C and SIGTERM: cleanup then force exit so the server actually stops."""
    _shutdown_connections()
    os._exit(0)


signal.signal(signal.SIGINT, _on_sigint_sigterm)
signal.signal(signal.SIGTERM, _on_sigint_sigterm)


def _connection_summary_filter(device):
    """Jinja filter: human-readable connection summary for a device."""
    params = None
    if getattr(device, "metadata", None) and isinstance(device.metadata, dict):
        params = device.metadata.get("connection_params")
    return format_connection_summary(getattr(device, "connection_type", "") or "", params)


def _format_timestamp(epoch_float):
    """Jinja filter: format epoch timestamp for display."""
    if epoch_float is None:
        return ""
    try:
        dt = datetime.fromtimestamp(epoch_float, tz=timezone.utc)
        return dt.strftime("%Y-%m-%d %H:%M:%S UTC")
    except (TypeError, ValueError, OSError):
        return str(epoch_float)


app.jinja_env.filters["connection_summary"] = _connection_summary_filter
app.jinja_env.filters["format_timestamp"] = _format_timestamp

app.register_blueprint(dashboard_bp)

# Restore virtual connections for devices that were saved as powered on
sync_from_store(get_all_devices())


@app.route("/")
def index():
    """Redirect root to dashboard."""
    return redirect(url_for("dashboard.index"))


if __name__ == "__main__":
    # Disable reloader when stdin is not a TTY to avoid termios.error in some terminals (e.g. Cursor).
    # If using `flask run` and you see termios/Input output error, run: flask run --no-reload
    use_reloader = getattr(sys.stdin, "isatty", lambda: False)()
    app.run(use_reloader=use_reloader)
