"""Versioned MotionModule browser dashboard served on the robot."""

from __future__ import annotations

import argparse
import math
import os
import secrets
import shutil
import signal
import socket
import subprocess
import threading
import time
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from werkzeug.serving import make_server

from . import __version__
from .controller import MotionModule
from .diagnostics import dashboard_checks
from .errors import MotionModuleError
from .network import NetworkClient
from .pinout import header_rows, motor_rows
from .runner import load_project
from .terminal import TerminalManager


DASHBOARD_PAGES = {"overview", "diagnostics", "code"}
PAGE_ALIASES = {"drive": "code", "hardware": "diagnostics", "network": "diagnostics"}


def servo_profiles(config) -> list[dict]:
    """Profiles exposed by the guarded dashboard servo commissioning tool."""

    common = {"zero": 0, "step": 1}
    return [
        {
            **common,
            "id": "gobilda_300_position",
            "label": "goBILDA 25-2 · 300° positional",
            "kind": "position",
            "minimum": 0,
            "maximum": 300,
            "unit": "°",
            "minimum_pulse_us": 500,
            "maximum_pulse_us": 2500,
        },
        {
            **common,
            "id": "gobilda_5_turn_position",
            "label": "goBILDA 25-2 · 5-turn positional",
            "kind": "position",
            "minimum": 0,
            "maximum": 1800,
            "unit": "°",
            "minimum_pulse_us": 500,
            "maximum_pulse_us": 2500,
        },
        {
            **common,
            "id": "gobilda_continuous",
            "label": "goBILDA 25-2 · continuous rotation",
            "kind": "continuous",
            "minimum": -100,
            "maximum": 100,
            "unit": "%",
            "minimum_pulse_us": 900,
            "maximum_pulse_us": 2100,
        },
        {
            **common,
            "id": "generic_180_position",
            "label": "Generic · 180° positional",
            "kind": "position",
            "minimum": 0,
            "maximum": 180,
            "unit": "°",
            "minimum_pulse_us": config.minimum_pulse_us,
            "maximum_pulse_us": config.maximum_pulse_us,
        },
        {
            **common,
            "id": "generic_360_position",
            "label": "Generic · 360° positional",
            "kind": "position",
            "minimum": 0,
            "maximum": 360,
            "unit": "°",
            "minimum_pulse_us": config.minimum_pulse_us,
            "maximum_pulse_us": config.maximum_pulse_us,
        },
    ]


def servo_profile_command(config, profile_id: str, value: float) -> tuple[dict, float]:
    profiles = {profile["id"]: profile for profile in servo_profiles(config)}
    if profile_id not in profiles:
        raise ValueError("Unknown servo profile")
    profile = profiles[profile_id]
    value = float(value)
    if not math.isfinite(value) or not profile["minimum"] <= value <= profile["maximum"]:
        raise ValueError(
            f"{profile['label']} value must be from {profile['minimum']} through "
            f"{profile['maximum']}{profile['unit']}"
        )
    span = profile["maximum"] - profile["minimum"]
    ratio = (value - profile["minimum"]) / span
    pulse_us = profile["minimum_pulse_us"] + ratio * (
        profile["maximum_pulse_us"] - profile["minimum_pulse_us"]
    )
    if not config.minimum_pulse_us <= pulse_us <= config.maximum_pulse_us:
        raise ValueError(
            f"Profile requires {pulse_us:.0f} microseconds, outside the configured "
            f"{config.minimum_pulse_us}-{config.maximum_pulse_us} microsecond safety envelope"
        )
    return profile, pulse_us


class IdleDrive:
    """Safe drive used only when the dashboard is started without a robot project."""

    def __init__(self, module) -> None:
        self.module = module

    def drive(self, _forward, _strafe, _rotate, _speed=0.5) -> dict:
        self.module.stop_all()
        return {"outputs": {}, "speed": 0.0}

    def stop(self) -> None:
        self.module.stop_all()


def _memory_status() -> dict:
    values: dict[str, int] = {}
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            name, raw = line.split(":", 1)
            values[name] = int(raw.strip().split()[0]) * 1024
    except (OSError, ValueError, IndexError):
        return {"total": 0, "available": 0, "used_percent": None}
    total = values.get("MemTotal", 0)
    available = values.get("MemAvailable", 0)
    used_percent = round((total - available) / total * 100, 1) if total else None
    return {"total": total, "available": available, "used_percent": used_percent}


def _temperature() -> float | None:
    try:
        return round(int(Path("/sys/class/thermal/thermal_zone0/temp").read_text()) / 1000, 1)
    except (OSError, ValueError):
        return None


def system_snapshot() -> dict:
    try:
        load = round(os.getloadavg()[0], 2)
    except (AttributeError, OSError):
        load = None
    try:
        uptime = float(Path("/proc/uptime").read_text().split()[0])
    except (OSError, ValueError, IndexError):
        uptime = None
    try:
        disk = shutil.disk_usage("/")
        disk_status = {
            "total": disk.total,
            "free": disk.free,
            "used_percent": round(disk.used / disk.total * 100, 1),
        }
    except OSError:
        disk_status = {"total": 0, "free": 0, "used_percent": None}
    return {
        "hostname": socket.gethostname(),
        "version": __version__,
        "uptime_seconds": uptime,
        "load_1m": load,
        "temperature_c": _temperature(),
        "memory": _memory_status(),
        "disk": disk_status,
    }


def load_drive(module, project_path: Path | None = None):
    """Load the student drive hook while supporting older Mecanum projects."""

    if project_path is None:
        drive = IdleDrive(module)
    else:
        if not project_path.is_file():
            raise FileNotFoundError(f"Robot project was not found: {project_path}")
        project = load_project(project_path)
        factory = getattr(project, "create_drive", None)
        legacy_drive = getattr(project, "MecanumDrive", None)
        if callable(factory):
            drive = factory(module)
        elif callable(legacy_drive):
            drive = legacy_drive(module)
        else:
            raise RuntimeError(
                f"{project_path} must define create_drive(module) returning a drive object"
            )

    if not callable(getattr(drive, "drive", None)) or not callable(getattr(drive, "stop", None)):
        raise RuntimeError("The active robot drive object must define drive(...) and stop()")
    return drive


def create_app(
    module,
    drive=None,
    network_client=None,
    project_name: str = "No project",
    terminal_manager=None,
) -> Flask:
    app = Flask(__name__, template_folder=str(Path(__file__).with_name("templates")))
    active_drive = drive or IdleDrive(module)
    network = network_client or NetworkClient()
    terminal = terminal_manager or TerminalManager()
    command_lock = threading.Lock()
    network_lock = threading.Lock()
    servo_lock = threading.Lock()
    terminal_attempt_lock = threading.Lock()
    servo_timers: dict[tuple[int, int], threading.Timer] = {}
    servo_commands: dict[tuple[int, int], dict] = {}
    terminal_attempts: dict[str, list[float]] = {}
    network_state = {"busy": False, "last_error": ""}
    dashboard_token = secrets.token_urlsafe(32)
    app.config["DASHBOARD_TOKEN"] = dashboard_token
    last_sequence = -1

    def authorized() -> bool:
        provided = request.headers.get("X-MotionModule-Token", "")
        return bool(provided) and secrets.compare_digest(provided, dashboard_token)

    @app.get("/")
    @app.get("/<page>")
    def dashboard(page: str = "overview"):
        page = PAGE_ALIASES.get(page, page)
        if page not in DASHBOARD_PAGES:
            return "Not found", 404
        return render_template(
            "dashboard.html",
            dashboard_token=dashboard_token,
            active_page=page,
            project_name=project_name,
        )

    @app.get("/healthz")
    def health():
        return jsonify({"ok": True})

    @app.get("/api/status")
    def status():
        system = system_snapshot()
        system["active_project"] = project_name
        robot = module.snapshot()
        with servo_lock:
            robot["servo_commands"] = {
                f"{board}:{channel}": dict(command)
                for (board, channel), command in servo_commands.items()
            }
        return jsonify({"ok": True, "robot": robot, "system": system})

    @app.get("/api/config")
    def configuration():
        servo = module.config.servos
        return jsonify(
            {
                "ok": True,
                "project": project_name,
                "module": {
                    "pwm_hz": module.config.pwm_hz,
                    "deadtime_ms": module.config.deadtime_ms,
                    "watchdog_ms": module.config.watchdog_ms,
                },
                "motors": motor_rows(module.config),
                "header": header_rows(module.config),
                "servos": {
                    "enabled": servo.enabled,
                    "i2c_bus": servo.i2c_bus,
                    "frequency_hz": servo.frequency_hz,
                    "addresses": [f"0x{address:02x}" for address in servo.addresses],
                    "minimum_pulse_us": servo.minimum_pulse_us,
                    "maximum_pulse_us": servo.maximum_pulse_us,
                    "channels": list(range(16)),
                    "profiles": servo_profiles(servo),
                },
                "pinout_url": "https://github.com/AloeVeraZ/MotionModule/blob/main/docs/PINOUT.md",
                "bom_url": "https://github.com/AloeVeraZ/MotionModule/blob/main/BOM.md",
            }
        )

    @app.get("/api/diagnostics")
    def diagnostics():
        return jsonify({"ok": True, "checks": dashboard_checks(module)})

    @app.get("/api/logs")
    def logs():
        try:
            result = subprocess.run(
                [
                    "journalctl", "-u", "motionmodule.service", "-n", "120",
                    "--no-pager", "--output", "short-iso",
                ],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
            output = (result.stdout or result.stderr or "No service logs are available yet.").strip()
            return jsonify({"ok": result.returncode == 0, "logs": output[-30000:]})
        except (OSError, subprocess.TimeoutExpired) as error:
            return jsonify({"ok": False, "logs": f"Service logs are unavailable here: {error}"})

    @app.post("/api/drive")
    def drive_command():
        nonlocal last_sequence
        if not authorized():
            return jsonify({"ok": False, "error": "Invalid dashboard session"}), 403
        body = request.get_json(silent=True) or {}
        try:
            sequence = int(body.get("sequence", -1))
            with command_lock:
                if sequence <= last_sequence:
                    return jsonify({"ok": True, "ignored": "stale sequence"})
                last_sequence = sequence
            result = active_drive.drive(
                body.get("forward", 0),
                body.get("strafe", 0),
                body.get("rotate", 0),
                body.get("speed", 0.4),
            )
        except (TypeError, ValueError) as error:
            active_drive.stop()
            return jsonify({"ok": False, "error": str(error)}), 400
        return jsonify({"ok": True, **result})

    @app.post("/api/stop")
    def stop_command():
        active_drive.stop()
        return jsonify({"ok": True})

    @app.post("/api/motors/test")
    def test_motor():
        if not authorized():
            return jsonify({"ok": False, "error": "Invalid dashboard session"}), 403
        body = request.get_json(silent=True) or {}
        if body.get("confirmed") is not True:
            return jsonify({"ok": False, "error": "Raise the robot and confirm the safety check first"}), 400
        try:
            channel = int(body.get("channel"))
            power = float(body.get("power"))
            if channel not in {item.channel for item in module.config.motors}:
                raise ValueError("That motor channel is not configured")
            if not -0.2 <= power <= 0.2:
                raise ValueError("Dashboard motor tests are limited to 20% power")
            module.set_motors({channel: power})
        except (TypeError, ValueError) as error:
            module.stop_all()
            return jsonify({"ok": False, "error": str(error)}), 400
        return jsonify({"ok": True, "channel": channel, "power": power})

    def release_servo(board: int, channel: int) -> None:
        try:
            module.servo(channel=channel, board=board).release()
        except (MotionModuleError, ValueError):
            pass
        with servo_lock:
            servo_timers.pop((board, channel), None)
            servo_commands.pop((board, channel), None)

    @app.post("/api/servos/set")
    def set_servo():
        if not authorized():
            return jsonify({"ok": False, "error": "Invalid dashboard session"}), 403
        body = request.get_json(silent=True) or {}
        if body.get("confirmed") is not True:
            return jsonify({"ok": False, "error": "Confirm the servo power and clear-motion check first"}), 400
        try:
            board = int(body.get("board", 0))
            channel = int(body.get("channel", 0))
            legacy_angle = "profile" not in body and "value" not in body
            profile_id = str(body.get("profile", "generic_180_position"))
            value = float(body.get("angle", 90) if legacy_angle else body.get("value"))
            profile, pulse_us = servo_profile_command(module.config.servos, profile_id, value)
            servo = module.servo(channel=channel, board=board)
            if legacy_angle:
                servo.set_angle(value)
            else:
                servo.set_pulse_us(pulse_us)
        except (MotionModuleError, TypeError, ValueError) as error:
            return jsonify({"ok": False, "error": str(error)}), 400
        key = (board, channel)
        with servo_lock:
            if key in servo_timers:
                servo_timers[key].cancel()
            servo_commands[key] = {
                "profile": profile_id,
                "profile_label": profile["label"],
                "kind": profile["kind"],
                "value": value,
                "unit": profile["unit"],
                "pulse_us": round(pulse_us, 1),
            }
            timer = threading.Timer(1.5, release_servo, args=key)
            timer.daemon = True
            servo_timers[key] = timer
            timer.start()
        response = {
            "ok": True,
            "board": board,
            "channel": channel,
            "profile": profile_id,
            "value": value,
            "unit": profile["unit"],
            "pulse_us": round(pulse_us, 1),
            "auto_release_seconds": 1.5,
        }
        if legacy_angle:
            response["angle"] = value
        return jsonify(response)

    @app.post("/api/servos/release")
    def release_servo_route():
        if not authorized():
            return jsonify({"ok": False, "error": "Invalid dashboard session"}), 403
        body = request.get_json(silent=True) or {}
        try:
            board = int(body.get("board", 0))
            channel = int(body.get("channel", 0))
            release_servo(board, channel)
        except (TypeError, ValueError) as error:
            return jsonify({"ok": False, "error": str(error)}), 400
        return jsonify({"ok": True})

    def terminal_error(error: Exception, status_code: int = 400):
        return jsonify({"ok": False, "error": str(error)}), status_code

    def terminal_token() -> str:
        return request.headers.get("X-MotionModule-Terminal", "")

    @app.get("/api/terminal/status")
    def terminal_status():
        return jsonify({"ok": True, **terminal.status()})

    @app.post("/api/terminal/start")
    def terminal_start():
        if not authorized():
            return terminal_error(MotionModuleError("Invalid dashboard session"), 403)
        client_address = request.headers.get("X-Real-IP", request.remote_addr or "unknown")
        now = time.monotonic()
        with terminal_attempt_lock:
            recent = [attempt for attempt in terminal_attempts.get(client_address, []) if now - attempt < 60]
            if len(recent) >= 10:
                return terminal_error(
                    MotionModuleError("Too many terminal unlock attempts; wait one minute"), 429
                )
            recent.append(now)
            terminal_attempts[client_address] = recent
        body = request.get_json(silent=True) or {}
        try:
            result = terminal.start(body.get("access_code", ""), Path.cwd())
        except MotionModuleError as error:
            return terminal_error(error, 403)
        with terminal_attempt_lock:
            terminal_attempts.pop(client_address, None)
        return jsonify({"ok": True, **result})

    @app.post("/api/terminal/output")
    def terminal_output():
        if not authorized():
            return terminal_error(MotionModuleError("Invalid dashboard session"), 403)
        body = request.get_json(silent=True) or {}
        try:
            result = terminal.read(terminal_token(), body.get("cursor", 0))
        except MotionModuleError as error:
            return terminal_error(error, 403)
        return jsonify({"ok": True, **result})

    @app.post("/api/terminal/input")
    def terminal_input():
        if not authorized():
            return terminal_error(MotionModuleError("Invalid dashboard session"), 403)
        body = request.get_json(silent=True) or {}
        try:
            terminal.write(terminal_token(), body.get("input", ""))
        except MotionModuleError as error:
            return terminal_error(error, 403)
        return jsonify({"ok": True})

    @app.post("/api/terminal/interrupt")
    def terminal_interrupt():
        if not authorized():
            return terminal_error(MotionModuleError("Invalid dashboard session"), 403)
        try:
            terminal.interrupt(terminal_token())
        except MotionModuleError as error:
            return terminal_error(error, 403)
        return jsonify({"ok": True})

    @app.post("/api/terminal/stop")
    def terminal_stop():
        if not authorized():
            return terminal_error(MotionModuleError("Invalid dashboard session"), 403)
        try:
            terminal.stop(terminal_token())
        except MotionModuleError as error:
            return terminal_error(error, 403)
        return jsonify({"ok": True})

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
                    return "Authentication server domain is required"
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
        if not authorized():
            return network_error(MotionModuleError("Invalid settings-session token"), 403)
        body = request.get_json(silent=True) or {}
        if error := validate_switch("hotspot", body):
            return network_error(MotionModuleError(error), 400)
        if not queue_network_switch(network.start_hotspot, body):
            return network_error(MotionModuleError("Another network change is already running"), 409)
        return jsonify({"ok": True, "switching": True, "message": f"Switching to hotspot {body['ssid']}. Join it, then open http://10.42.0.1."}), 202

    @app.post("/api/network/connect")
    def network_connect():
        if not authorized():
            return network_error(MotionModuleError("Invalid settings-session token"), 403)
        body = request.get_json(silent=True) or {}
        if error := validate_switch("connect", body):
            return network_error(MotionModuleError(error), 400)
        if not queue_network_switch(network.connect, body):
            return network_error(MotionModuleError("Another network change is already running"), 409)
        return jsonify({"ok": True, "switching": True, "message": "Connecting now. Rejoin that Wi-Fi on this device, then open the displayed .local address or IP."}), 202

    @app.post("/api/network/preferred")
    def network_preferred():
        if not authorized():
            return network_error(MotionModuleError("Invalid settings-session token"), 403)
        if not queue_network_switch(network.activate_preferred, {}):
            return network_error(MotionModuleError("Another network change is already running"), 409)
        return jsonify({"ok": True, "switching": True, "message": "Reconnecting to the saved preferred Wi-Fi. Rejoin it on this device and open the displayed address."}), 202

    return app


def serve(module, stop_event: threading.Event, project_path: Path | None = None) -> None:
    project_name = project_path.parent.name if project_path else "No project"
    app = create_app(module, load_drive(module, project_path), project_name=project_name)
    # Nginx is the only network-facing listener. Keeping Flask on loopback
    # prevents bypassing the stable port-80 front door and proxy policy.
    server = make_server("127.0.0.1", 8080, app, threaded=True)
    server.timeout = 0.25
    print("MotionModule dashboard: http://motionmodule.local")
    try:
        while not stop_event.is_set():
            server.handle_request()
    finally:
        module.stop_all()
        server.server_close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the MotionModule dashboard")
    parser.add_argument("--project", type=Path, help="Optional student robot.py drive hook")
    args = parser.parse_args(argv)
    stop_event = threading.Event()

    def stop(_signum=None, _frame=None):
        stop_event.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    with MotionModule() as module:
        serve(module, stop_event, args.project.resolve() if args.project else None)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
