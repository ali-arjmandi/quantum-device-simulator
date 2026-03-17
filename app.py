"""Quantum Device Simulator - minimal Flask app."""
import os

from dotenv import load_dotenv
from flask import Flask, redirect, url_for

from config.connection_specs import format_connection_summary
from dashboard import dashboard_bp

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")


def _connection_summary_filter(device):
    """Jinja filter: human-readable connection summary for a device."""
    params = None
    if getattr(device, "metadata", None) and isinstance(device.metadata, dict):
        params = device.metadata.get("connection_params")
    return format_connection_summary(getattr(device, "connection_type", "") or "", params)


app.jinja_env.filters["connection_summary"] = _connection_summary_filter

app.register_blueprint(dashboard_bp)


@app.route("/")
def index():
    """Redirect root to dashboard."""
    return redirect(url_for("dashboard.index"))


if __name__ == "__main__":
    app.run()
