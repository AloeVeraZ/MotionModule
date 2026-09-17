"""Run the MotionModule dashboard on any computer, with a simulated robot.

This is for showing the robot website off, or working on it, without a
Raspberry Pi. It is the real dashboard and Driver Station, driving the example
Mecanum robot through MotionModule's own motor and servo simulation, so arming
Drive and holding W moves the motor bars exactly as it would on a robot.

Nothing touches hardware or the computer's network. GPIO and servo boards are
always simulated, even on a Pi. Wi-Fi status, the camera feeds, the IMU, and
the sensors are stand-ins that move on their own, and network changes and the
web terminal are switched off.

    python -m motion_module.demo                  # http://127.0.0.1:8080
    python -m motion_module.demo --port 9000
    python -m motion_module.demo --host 0.0.0.0   # also reachable from a phone

demo.ps1 and demo.sh at the repository root download MotionModule, prepare
Python, and run this for you.
"""

from __future__ import annotations

import argparse
import math
import os
import socket
import threading
import time
import webbrowser
from pathlib import Path

from flask import Response
from werkzeug.serving import WSGIRequestHandler, make_server

from . import __version__
from .config import default_config, load_config
from .controller import MotionModule
from .dashboard import IdleDrive, create_app, load_autonomous_routine, load_drive
from .errors import MotionModuleError
from .gpio import MockGPIO


EXAMPLE_PROJECT = Path(__file__).resolve().parents[2] / "examples" / "Mecanum"
DEMO_NOTE = "Demo only: nothing on this computer was changed."


class DemoNetwork:
    """Wi-Fi status for the Debug and Code pages. Switching is simulated."""

    def __init__(self, dashboard_url: str) -> None:
        self.dashboard_url = dashboard_url
        self.message = ""

    def status(self) -> dict:
        return {
            "ok": True,
            "wifi": {"mode": "client", "ssid": "Workshop Wi-Fi"},
            "addresses": [{"interface": "demo", "address": "127.0.0.1"}],
            "services": {"ssh": True, "mdns": True},
            "hostname": "motionmodule",
            "local_url": self.dashboard_url,
            "hotspot_url": "http://10.42.0.1",
            "hotspot_ssid": "MotionModule",
            "last_message": self.message,
        }

    def scan(self) -> list[dict]:
        return [
            {"ssid": "Workshop Wi-Fi", "signal": 86, "security": "WPA2", "security_kind": "personal",
             "connected": True, "supported": True},
            {"ssid": "Field Network", "signal": 64, "security": "WPA2", "security_kind": "personal",
             "connected": False, "supported": True},
            {"ssid": "Campus Secure", "signal": 52, "security": "WPA2 Enterprise",
             "security_kind": "enterprise", "connected": False, "supported": True},
            {"ssid": "Guest", "signal": 38, "security": "", "security_kind": "open",
             "connected": False, "supported": True},
        ]

    def _simulate(self, _payload=None) -> None:
        self.message = DEMO_NOTE

    start_hotspot = connect = change_hostname = _simulate

    def activate_preferred(self) -> None:
        self._simulate()


class DemoTerminal:
    """The web terminal is a real shell on a robot, so the demo has none."""

    def status(self) -> dict:
        return {
            "available": False,
            "enabled": False,
            "expires_in_seconds": 0,
            "active": False,
            "idle_timeout_seconds": 300,
        }

    def start(self, _access_code, _working_directory):
        raise MotionModuleError("The web terminal runs only on a real robot")

    def _closed(self, *_arguments):
        raise MotionModuleError("There is no terminal session in the demo")

    read = write = interrupt = stop = _closed


class DemoTelemetry:
    """Camera, IMU, and sensor readings that move, for the Driver Station."""

    def __init__(self) -> None:
        self.started = time.monotonic()

    def snapshot(self) -> dict:
        t = time.monotonic() - self.started
        heading = (t * 9.0 + 180.0) % 360.0 - 180.0
        return {
            "cameras": [
                {"name": "Front", "url": "/demo/camera/front.svg", "detail": "Simulated feed"},
                {"name": "Rear", "url": "/demo/camera/rear.svg", "detail": "Simulated feed"},
            ],
            "imu": {
                "name": "Main IMU",
                "connected": True,
                "calibrated": True,
                # Counter-clockwise positive, as a real IMU reports it.
                "yaw": heading,
                "pitch": 1.6 * math.sin(t / 3.1),
                "roll": -2.2 * math.cos(t / 4.3),
                "rate": 9.0,
                "detail": "Simulated BNO055 at 0x28: the demo robot turns slowly left.",
            },
            "pi_inputs": [
                {"name": "Forward limit", "value": math.sin(t / 2.5) > 0.6, "kind": "digital",
                 "channel": "GPIO17", "status": "ok"},
                {"name": "Arm home switch", "value": True, "kind": "digital", "channel": "GPIO5",
                 "status": "ok"},
            ],
            "usb_controllers": [{
                "id": "giga:demo",
                "name": "Arduino GIGA R1 WiFi",
                "board_id": "arduino_giga_r1_wifi",
                "connected": True,
                "serial": "DEMO",
                "port": "simulated",
                "bridge": "streaming",
                "digital_pins": ["D0", "D75"],
                "analog_pins": ["A0", "A7"],
                "adc_bits": 12,
                "detail": "Simulated MotionModule sensor firmware 3.0.0",
                "pins": [
                    {"name": "Arm potentiometer", "value": round(2048 + 1700 * math.sin(t / 2)),
                     "kind": "analog", "unit": "raw", "channel": "A0", "minimum": 0, "maximum": 4095,
                     "status": "ok"},
                    {"name": "Battery", "value": round(12.4 - 0.25 * math.sin(t / 9), 2),
                     "kind": "analog", "unit": "V", "channel": "A1", "minimum": 10.5, "maximum": 13,
                     "status": "ok"},
                    {"name": "Intake beam", "value": int(t / 3) % 2 == 0, "kind": "digital",
                     "channel": "D22", "status": "ok"},
                    {"name": "Main IMU heading", "value": round(heading, 1), "kind": "analog",
                     "unit": "°", "channel": "I2C 0x28", "minimum": -180, "maximum": 180, "status": "ok"},
                    {"name": "Backup IMU heading", "value": round(heading - 0.4, 1), "kind": "analog",
                     "unit": "°", "channel": "I2C 0x6A", "minimum": -180, "maximum": 180, "status": "ok"},
                ],
            }],
        }


def camera_svg(name: str) -> str:
    """A still, camera-shaped frame: a floor grid running to the horizon."""

    lines = []
    horizon, center, size = 300, 320, 640
    for index in range(-8, 9):
        lines.append(f'<line x1="{center}" y1="{horizon}" x2="{center + index * 90}" y2="{size}"/>')
    for step in range(1, 9):
        y = horizon + (size - horizon) * (step / 8) ** 2
        lines.append(f'<line x1="0" y1="{y:.1f}" x2="{size}" y2="{y:.1f}"/>')
    title = f"{name.upper()} CAMERA"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {size} {size}" width="{size}" height="{size}">
<defs><linearGradient id="g" x1="0" y1="0" x2="0" y2="1">
<stop offset="0" stop-color="#13161b"/><stop offset=".47" stop-color="#0c0e11"/><stop offset="1" stop-color="#07080a"/>
</linearGradient></defs>
<rect width="{size}" height="{size}" fill="url(#g)"/>
<g stroke="#7ba8d8" stroke-opacity=".28" stroke-width="1.4">{"".join(lines)}</g>
<line x1="0" y1="{horizon}" x2="{size}" y2="{horizon}" stroke="#9dccff" stroke-opacity=".45" stroke-width="1.5"/>
<circle cx="{center}" cy="{center}" r="44" fill="none" stroke="#f7f4ed" stroke-opacity=".28" stroke-width="2"/>
<g stroke="#f7f4ed" stroke-opacity=".7" stroke-width="2.5" stroke-linecap="round">
<line x1="{center - 22}" y1="{center}" x2="{center + 22}" y2="{center}"/>
<line x1="{center}" y1="{center - 22}" x2="{center}" y2="{center + 22}"/>
</g>
<text x="36" y="66" fill="#9dccff" font-family="'Barlow Condensed', 'Arial Narrow', Arial, sans-serif" font-size="34" font-weight="700" letter-spacing="4">{title}</text>
<text x="36" y="96" fill="#8f8c85" font-family="Inter, 'Segoe UI', Arial, sans-serif" font-size="17">Simulated feed</text>
</svg>"""


def create_demo_app(dashboard_url: str = "http://127.0.0.1:8080"):
    """Build the demo dashboard. Returns the Flask app and the simulated module."""

    project = EXAMPLE_PROJECT / "robot.py"
    have_example = project.is_file()
    config = load_config(project=EXAMPLE_PROJECT) if have_example else default_config()
    # Always simulated, even when this runs on a Raspberry Pi next to a real
    # robot service: the demo must never claim GPIO or talk to a servo board.
    module = MotionModule(config, gpio=MockGPIO())
    drive = load_drive(module, project) if have_example else IdleDrive(module)
    routine, routine_error = None, ""
    if have_example:
        try:
            routine = load_autonomous_routine(module, drive, project)
        except Exception as error:  # the demo still runs without autonomous mode
            routine_error = f"autonomous.py could not be loaded: {error}"
    app = create_app(
        module,
        drive,
        DemoNetwork(dashboard_url),
        project_name="Mecanum" if have_example else "No project",
        terminal_manager=DemoTerminal(),
        config_path=EXAMPLE_PROJECT / "hardware.py" if have_example else None,
        dashboard_telemetry=DemoTelemetry(),
        autonomous_routine=routine,
        autonomous_error=routine_error,
    )

    @app.get("/demo/camera/<name>.svg")
    def demo_camera(name: str):
        if name not in {"front", "rear"}:
            return "Not found", 404
        return Response(camera_svg(name), mimetype="image/svg+xml")

    return app, module


class QuietRequestHandler(WSGIRequestHandler):
    """The pages poll the robot several times a second; logging every request
    would bury the address the demo prints. Errors are still logged."""

    def log_request(self, *_arguments, **_keywords) -> None:
        pass


def port_is_free(host: str, port: int) -> bool:
    # A plain bind, without the address reuse web servers ask for, is what
    # reliably reports a port another program already holds on Windows.
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        try:
            probe.bind((host, port))
        except OSError:
            return False
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the MotionModule dashboard with a simulated robot, no Raspberry Pi needed."
    )
    parser.add_argument("--host", default="127.0.0.1",
                        help="address to listen on; 0.0.0.0 also serves other devices on this network")
    parser.add_argument("--port", type=int, default=8080, help="first port to try (default 8080)")
    parser.add_argument(
        "--no-browser",
        action="store_true",
        default=os.environ.get("MOTIONMODULE_DEMO_NO_BROWSER", "").casefold() in {"1", "true", "yes"},
        help="do not open a browser window (or set MOTIONMODULE_DEMO_NO_BROWSER=1)",
    )
    args = parser.parse_args(argv)

    port = next((candidate for candidate in range(args.port, args.port + 20)
                 if port_is_free(args.host, candidate)), None)
    if port is None:
        parser.error(f"no free port between {args.port} and {args.port + 19}")
    shown_host = "127.0.0.1" if args.host in {"0.0.0.0", ""} else args.host
    url = f"http://{shown_host}:{port}"

    app, module = create_demo_app(url)
    with module:
        server = make_server(args.host, port, app, threaded=True, request_handler=QuietRequestHandler)
        print(f"\nMotionModule {__version__} demo, with a simulated robot")
        print(f"  Dashboard:       {url}/")
        print(f"  Driver Station:  {url}/driver-station")
        if args.host == "0.0.0.0":
            print("  Other devices on this network can open the same pages with this computer's IP address.")
        print("Press Ctrl+C to stop.\n", flush=True)
        if not args.no_browser:
            threading.Timer(0.8, webbrowser.open, args=(f"{url}/",)).start()
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nStopping the demo.")
        finally:
            server.server_close()
            module.stop_all()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
