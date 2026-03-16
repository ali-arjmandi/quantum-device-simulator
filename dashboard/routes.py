"""Dashboard blueprint and routes."""
from flask import Blueprint, render_template

bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


@bp.route("/")
def index():
    """Dashboard index."""
    return render_template("dashboard/index.html")


@bp.route("/simulator")
def simulator():
    """Device simulator page."""
    return render_template("dashboard/simulator.html")
