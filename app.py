"""Quantum Device Simulator - minimal Flask app."""
import os

from dotenv import load_dotenv
from flask import Flask, redirect, url_for

from dashboard import dashboard_bp

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")

app.register_blueprint(dashboard_bp)


@app.route("/")
def index():
    """Redirect root to dashboard."""
    return redirect(url_for("dashboard.index"))


if __name__ == "__main__":
    app.run()
