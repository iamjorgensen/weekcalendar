import hmac
import os
import subprocess
from pathlib import Path

from flask import Flask, abort, jsonify, request, send_file

app = Flask(__name__)
ROOT = Path(__file__).parent
IMG_JPG = ROOT / "output.jpg"   # must match main.py --out-jpg
IMG_PNG = ROOT / "output.png"   # must match main.py --out-png

# Shared secret for POST /run-main. Send it as "Authorization: Bearer <token>"
# or "X-Run-Token: <token>". If unset, /run-main is disabled.
RUN_MAIN_TOKEN = os.environ.get("RUN_MAIN_TOKEN", "")


@app.get("/")
def home():
    return "WeekCalendar Server OK - GET /image (JPEG) or /image.png (PNG)"


def _send(path: Path, mimetype: str):
    if not path.exists():
        abort(404, "No image found")
    resp = send_file(str(path), mimetype=mimetype)
    resp.headers["Cache-Control"] = "no-store"
    return resp


@app.get("/image")
def image():
    return _send(IMG_JPG, "image/jpeg")


@app.get("/image.png")
def image_png():
    return _send(IMG_PNG, "image/png")


def _token_ok() -> bool:
    supplied = request.headers.get("X-Run-Token", "")
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        supplied = auth[7:].strip()
    return bool(supplied) and hmac.compare_digest(supplied, RUN_MAIN_TOKEN)


# Trigger main.py via systemd service (non-blocking)
@app.post("/run-main")
def run_main():
    if not RUN_MAIN_TOKEN:
        abort(503, "RUN_MAIN_TOKEN is not configured on the server")
    if not _token_ok():
        abort(401)
    # sudoers must allow this exact command for the service user.
    # --no-block: return immediately instead of waiting for a oneshot render.
    subprocess.run(["sudo", "systemctl", "start", "--no-block", "weekcalendar-main.service"], check=False)
    return jsonify({"status": "started"}), 202


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=8000)
