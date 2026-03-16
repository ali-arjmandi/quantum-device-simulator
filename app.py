"""Quantum Device Simulator - minimal Flask app."""
import os

from dotenv import load_dotenv
from flask import Flask, render_template

load_dotenv()

app = Flask(__name__)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-key")


@app.route("/")
def home():
    return render_template("home.html")


if __name__ == "__main__":
    app.run()
