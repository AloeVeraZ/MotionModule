"""Student-editable mecanum example and local browser driver station."""

from __future__ import annotations

import secrets
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from werkzeug.serving import make_server

from mecanum import MecanumDrive
from motion_module.errors import MotionModuleError
from motion_module.network import NetworkClient


PROJECT_DIR = Path(__file__).resolve().parent


def create_app(module, network_client=None) -> Flask:
    app = Flask(__name__, template_folder=str(PROJECT_DIR / "templates"))
    drive = MecanumDrive(module)
    network = network_client or NetworkClient()
    sequence_lock = threading.Lock()
    network_lock = threading.Lock()
    network_state = {"busy": False, "last_error": ""}
    network_token = secrets.token_urlsafe(32)
    app.config["NETWORK_CSRF_TOKEN"] = network_token
    last_sequence = -1

    @app.get("/")
    def index():
        return render_template("index.html", network_token=network_token)

    @app.get("/api/status")
    def status():
        return jsonify(module.snapshot())

    @app.post("/api/drive")
    def drive_command():
        nonlocal last_sequence
        body = request.get_json(silent=True) or {}
        try:
            sequence = int(body.get("sequence", -1))
            with sequence_lock:
                if sequence <= last_sequence:
                    return jsonify({"ok": True, "ignored": "stale sequence"})
                last_sequence = sequence
            result = drive.drive(
                body.get("forward", 0),
                body.get("strafe", 0),
                body.get("rotate", 0),
                body.get("speed", 0.5),
            )
        except (TypeError, ValueError) as error:
            drive.stop()
            return jsonify({"ok": False, "error": str(error)}), 400
        return jsonify({"ok": True, **result})

    @app.post("/api/stop")
    def stop_command():
        drive.stop()
        return jsonify({"ok": True})

    def authorized_network_request() -> bool:
        provided = request.headers.get("X-MotionModule-Token", "")
        return bool(provided) and secrets.compare_digest(provided, network_token)

    def network_error(error: Exception, status_code: int = 503):
        return jsonify({"ok": False, "error": str(error)}), status_code

    @app.get("/api/network/status")
    def network_status():
        try:
            response = network.status()
            with network_lock:
                response["busy"] = network_state["busy"]
                response["job_error"] = network_state["last_error"]
            return jsonify(response)
        except MotionModuleError as error:
            return network_error(error)

    @app.get("/api/network/scan")
    def network_scan():
        try:
            return jsonify({"ok": True, "networks": network.scan()})
        except MotionModuleError as error:
            return network_error(error)

    def validate_switch(kind: str, body: dict) -> str | None:
        ssid = str(body.get("ssid", "")).strip()
        if kind != "preferred":
            if not ssid:
                return "Choose or enter a Wi-Fi name"
            if len(ssid.encode("utf-8")) > 32:
                return "Wi-Fi names may contain at most 32 bytes"
        password = str(body.get("password", ""))
        if kind == "hotspot":
            if password and not 8 <= len(password) <= 63:
                return "Hotspot password must contain 8-63 characters"
            if not password:
                # An omitted password means "keep the saved hotspot password".
                body.pop("password", None)
        if kind == "connect":
            security_kind = str(body.get("security_kind", "personal"))
            if security_kind not in {"open", "personal", "enterprise"}:
                return "That Wi-Fi security type is not supported"
            if security_kind == "personal" and not 8 <= len(password) <= 63:
                return "Wi-Fi password must contain 8-63 characters"
            if security_kind == "enterprise":
                if not str(body.get("username", "")).strip():
                    return "Enterprise username is required"
                if not password:
                    return "Enterprise password is required"
                if not str(body.get("domain", "")).strip():
                    return "Authentication server domain is required for a safe enterprise connection"
        return None

    def queue_network_switch(action, body: dict) -> bool:
        with network_lock:
            if network_state["busy"]:
                return False
            network_state["busy"] = True
            network_state["last_error"] = ""
        module.stop_all()

        def worker():
            try:
                # Give Flask time to deliver the 202 response before Wi-Fi drops.
                time.sleep(1.25)
                action(body) if body else action()
            except MotionModuleError as error:
                with network_lock:
                    network_state["last_error"] = str(error)
            finally:
                with network_lock:
                    network_state["busy"] = False

        threading.Thread(target=worker, name="motionmodule-network-switch", daemon=True).start()
        return True

    @app.post("/api/network/hotspot")
    def network_hotspot():
        if not authorized_network_request():
            return network_error(MotionModuleError("Invalid settings-session token"), 403)
        body = request.get_json(silent=True) or {}
        if error := validate_switch("hotspot", body):
            return network_error(MotionModuleError(error), 400)
        if not queue_network_switch(network.start_hotspot, body):
            return network_error(MotionModuleError("Another network change is already running"), 409)
        return jsonify(
            {
                "ok": True,
                "switching": True,
                "message": f"Switching to hotspot {body['ssid']}. Join it, then open http://10.42.0.1:8080.",
            }
        ), 202

    @app.post("/api/network/connect")
    def network_connect():
        if not authorized_network_request():
            return network_error(MotionModuleError("Invalid settings-session token"), 403)
        body = request.get_json(silent=True) or {}
        if error := validate_switch("connect", body):
            return network_error(MotionModuleError(error), 400)
        if not queue_network_switch(network.connect, body):
            return network_error(MotionModuleError("Another network change is already running"), 409)
        return jsonify(
            {
                "ok": True,
                "switching": True,
                "message": "Connecting now. Rejoin that Wi-Fi on this device, then open the .local address shown in Settings.",
            }
        ), 202

    @app.post("/api/network/preferred")
    def network_preferred():
        if not authorized_network_request():
            return network_error(MotionModuleError("Invalid settings-session token"), 403)
        if not queue_network_switch(network.activate_preferred, {}):
            return network_error(MotionModuleError("Another network change is already running"), 409)
        return jsonify(
            {
                "ok": True,
                "switching": True,
                "message": "Reconnecting to the saved preferred Wi-Fi. Rejoin it on this device and use the .local address.",
            }
        ), 202

    return app


def run(module, stop_event) -> None:
    """Entry point used by motion_module.runner and the systemd service."""

    app = create_app(module)
    server = make_server("0.0.0.0", 8080, app, threaded=True)
    server.timeout = 0.25
    print("Mecanum driver station: http://motionmodule.local:8080")
    try:
        while not stop_event.is_set():
            server.handle_request()
    finally:
        module.stop_all()
        server.server_close()
