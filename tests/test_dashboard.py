import io
import re
import threading
import tempfile
import time
import unittest
import sys
import zipfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from motion_module.config import hardware_source, load_hardware_file, load_project_config
from motion_module.controller import MotionModule
from motion_module.dashboard import (
    STATIC_MAX_AGE_SECONDS,
    create_app,
    install_ref,
    load_dashboard_telemetry,
    load_drive,
    static_asset_version,
)
from motion_module.gpio import MockGPIO
from motion_module.servo import MockServoController, Servo

EXAMPLE_DIR = Path(__file__).resolve().parents[1] / "examples" / "Mecanum"
if str(EXAMPLE_DIR) not in sys.path:
    sys.path.insert(0, str(EXAMPLE_DIR))

from robot import MecanumDrive  # noqa: E402


class FakeModule:
    def __init__(self):
        self.config = load_project_config(EXAMPLE_DIR)
        self.outputs = {channel: 0.0 for channel in range(1, 9)}
        self.stopped = False
        self._servos = MockServoController(self.config.servos)
        self.servo_outputs_enabled = True

    def set_motors(self, outputs):
        for reference, value in outputs.items():
            self.outputs[self.config.motor_channel(reference)] = value

    def stop_all(self):
        self.stopped = True
        self.outputs = {channel: 0.0 for channel in range(1, 9)}

    def set_servo_outputs_enabled(self, enabled):
        self.servo_outputs_enabled = bool(enabled)

    def refresh_servo_boards(self, *, interval=2.0):
        self._servos.probe()

    def release_all_servos(self):
        for board, channel in sorted({*self._servos.angles, *self._servos.pulses}):
            self._servos.release(board, channel)

    def servo(self, channel, board=0):
        return Servo(self._servos, board, channel)

    def snapshot(self):
        return {
            "hardware": False,
            "motors": dict(self.outputs),
            "watchdog_ms": self.config.watchdog_ms,
            "watchdog_armed": any(self.outputs.values()),
            "watchdog_tripped": False,
            "servos": {f"{board}:{channel}": angle for (board, channel), angle in self._servos.angles.items()},
            "servo_outputs": {
                f"{board}:{channel}": {"pulse_us": pulse_us}
                for (board, channel), pulse_us in self._servos.pulses.items()
            },
            "servo_boards": [{"index": 0, "address": "0x40", "available": True, "error": None}],
        }


class FakeNetwork:
    def __init__(self):
        self.hotspot_payload = None
        self.hostname_payload = None
        self.called = threading.Event()

    def status(self):
        return {
            "ok": True,
            "wifi": {"mode": "client", "ssid": "Workshop"},
            "addresses": [{"interface": "wlan0", "address": "192.0.2.10"}],
            "services": {"ssh": True, "mdns": True},
            "hostname": "motionmodule",
            "local_url": "http://motionmodule.local",
            "hotspot_url": "http://10.42.0.1",
            "hotspot_ssid": "MotionModule",
        }

    def scan(self):
        return [{"ssid": "Workshop", "signal": 80, "security_kind": "personal", "supported": True}]

    def start_hotspot(self, payload):
        self.hotspot_payload = payload
        self.called.set()

    def connect(self, payload):
        self.called.set()

    def activate_preferred(self):
        self.called.set()

    def change_hostname(self, payload):
        self.hostname_payload = payload
        self.called.set()


class FakeTerminal:
    def __init__(self):
        self.token = "terminal-session"
        self.commands = []
        self.interrupted = False
        self.stopped = False

    def status(self):
        return {
            "available": True,
            "enabled": True,
            "expires_in_seconds": 900,
            "active": bool(self.commands) and not self.stopped,
            "idle_timeout_seconds": 300,
        }

    def start(self, access_code, working_directory):
        if access_code != "test-code":
            from motion_module.errors import MotionModuleError

            raise MotionModuleError("Invalid terminal access code")
        self.working_directory = working_directory
        return {"token": self.token, "cursor": 0}

    def read(self, token, cursor):
        self._check(token)
        return {"output": "motionmodule:$ ", "cursor": cursor + 15, "reset": False, "active": True}

    def write(self, token, value):
        self._check(token)
        self.commands.append(value)

    def interrupt(self, token):
        self._check(token)
        self.interrupted = True

    def stop(self, token):
        self._check(token)
        self.stopped = True

    def _check(self, token):
        if token != self.token:
            from motion_module.errors import MotionModuleError

            raise MotionModuleError("Invalid terminal session")


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.module = FakeModule()
        self.network = FakeNetwork()
        self.terminal = FakeTerminal()
        self.app = create_app(
            self.module,
            MecanumDrive(self.module),
            self.network,
            project_name="Mecanum",
            terminal_manager=self.terminal,
        )
        self.client = self.app.test_client()
        self.headers = {"X-MotionModule-Token": self.app.config["DASHBOARD_TOKEN"]}

    def test_all_dashboard_pages_are_served_by_versioned_runtime(self):
        for path in ("/", "/diagnostics", "/code"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertIn(b"MotionModule", response.data)

    def test_dashboard_consolidates_debug_and_code_navigation(self):
        debug = self.client.get("/diagnostics").data
        self.assertIn(b"Four dual H-bridge drivers", debug)
        self.assertIn(b"MotionModule Doctor", debug)
        self.assertIn(b"Connect to Wi", debug)
        self.assertIn(b"Useful commands", debug)
        self.assertIn(b"Stops outputs, reloads the active robot project", debug)
        self.assertIn(b"Pi reboots automatically", debug)
        self.assertIn(b"Enable Test Mecanum", self.client.get("/drive").data)
        self.assertNotIn(b">Arm control<", self.client.get("/drive").data)
        self.assertNotIn(b'data-page="hardware"', debug)
        self.assertNotIn(b'data-page="network"', debug)
        self.assertNotIn(b'id="bomLink"', debug)
        self.assertNotIn(b'id="pinoutLink"', debug)
        self.assertIn(b'.part-status.pending { background: var(--red-soft); color: var(--red); }', debug)
        self.assertIn(b"activePage === 'diagnostics' ? 'Debug'", debug)
        code = self.client.get("/code").data
        self.assertIn(b"Driver Station", code)
        self.assertIn(b'id="projectFolder"', code)
        self.assertIn(b"Download Mecanum sample", code)
        self.assertIn(b"hardware.py", code)
        self.assertIn(b"Names you can use in code", debug)
        self.assertIn(b'id="motorNameRows"', debug)
        self.assertIn(b'id="servoNameRows"', debug)
        self.assertNotIn(b"Remote-SSH", code)
        self.assertNotIn(b"tools/push_robot.py", code)
        self.assertIn(b"Time-limited robot shell", code)
        self.assertIn(b'id="terminalCommand"', code)
        overview = self.client.get("/").data
        self.assertIn(b"Servo activity", overview)
        self.assertIn(b'id="servoChannel"', debug)
        self.assertIn(b'id="servoProfile"', debug)
        self.assertIn(b"Zero servo", debug)
        self.assertIn(b'id="hostnameForm"', debug)
        self.assertIn(b"Connected USB devices", debug)
        self.assertIn(b'id="usbDevices"', debug)
        self.assertIn(b"hostname is this robot", debug)

    def test_drive_page_is_the_built_in_mecanum_test_not_the_full_station(self):
        drive = self.client.get("/drive").data
        self.assertIn(b'data-view="drive"', drive)
        self.assertIn(b'id="driveEnable"', drive)
        self.assertIn(b'id="padIdentity"', drive)      # game controller
        self.assertIn(b'id="wheelCheck"', drive)       # which corner each channel turns
        self.assertIn(b'id="openDriverStation"', drive)
        self.assertIn(b"/api/mecanum/test", drive)     # built-in mixer, not robot code
        # Key remapping and project-declared controls belong to the full
        # station, which is the page that runs the deployed project.
        self.assertNotIn(b'id="bindingList"', drive)
        self.assertNotIn(b'id="customControls"', drive)
        self.assertNotIn(b'id="cameraStage"', drive)   # telemetry belongs to the full station
        self.assertNotIn(b'id="headingDial"', drive)
        self.assertIn(b"gamepadconnected", drive)
        station = self.client.get("/driver-station").data
        self.assertIn(b"Competition console", station)
        self.assertIn(b'id="cameraStage"', station)
        self.assertIn(b'id="headingDial"', station)
        self.assertIn(b'id="piSensorList"', station)
        self.assertIn(b'id="usbControllerList"', station)
        self.assertNotIn(b'class="sidebar"', station)
        # Drive left the Code page entirely.
        code = self.client.get("/code").data
        self.assertNotIn(b'data-tab="drive"', code)

    def test_legacy_dashboard_urls_open_the_consolidated_pages(self):
        for path, active in (("/hardware", b'data-page="diagnostics"'), ("/network", b'data-page="diagnostics"')):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn(active, response.data)

    def test_wiring_guide_draws_the_pi_beside_its_header_then_the_drivers(self):
        page = self.client.get("/diagnostics").data.decode("utf-8")
        # The Pi 5 drawing sits in the same card as the header list, captioned.
        pi_view = page[page.index('class="pi-header-view"'):page.index('id="headerGrid"')]
        self.assertIn(f'src="/static/raspberry-pi-5.svg?v={static_asset_version()}"', pi_view)
        self.assertIn("<figcaption>Pi-5</figcaption>", pi_view)
        self.assertIn("ports at the bottom, header down the right edge", page)
        # Then the drivers, then the servo board, then power.
        order = [page.index(text) for text in (
            'id="headerGrid"', "02 / Motor drivers", 'id="driverGrid"', "03 / Servo controller", "04 / Power")]
        self.assertEqual(order, sorted(order))
        # The driver drawing names every pin the way the board prints it.
        drawing = page[page.index('class="driver-figure"'):page.index("</figure>", page.index('class="driver-figure"'))]
        for label in ("IN1", "IN2", "IN3", "IN4", "GND", "MOTOR_A", "MOTOR_B", "VIN−", "VIN+"):
            self.assertIn(f">{label}</text>", drawing)
        self.assertIn("Mecanum sample", page)

        drawing_file = self.client.get("/static/raspberry-pi-5.svg")
        svg = drawing_file.data
        drawing_file.close()
        self.assertEqual(drawing_file.status_code, 200)
        self.assertTrue(svg.startswith(b"<svg"))
        # Forty header pins, and nothing fetched from anywhere else.
        self.assertEqual(svg.count(b'<use href="#pin" x="51.23"') + svg.count(b'<use href="#pin" x="53.77"'), 40)
        self.assertNotIn(b"http://", svg.replace(b"http://www.w3.org/2000/svg", b""))
        self.assertNotIn(b"https://", svg)

    def test_pages_load_only_self_hosted_design_assets(self):
        version = static_asset_version()
        for path in ("/", "/drive", "/driver-station"):
            with self.subTest(path=path):
                page = self.client.get(path).data.decode("utf-8")
                self.assertIn(f'href="/static/motionmodule.css?v={version}"', page)
                self.assertIn(f'src="/static/motionmodule.js?v={version}"', page)
                # A robot on its own hotspot has no internet, so no stylesheet,
                # script, or font may come from another origin.
                self.assertIsNone(re.search(r'<(?:link|script)[^>]+(?:href|src)="(?:https?:)?//', page))

        stylesheet = self.client.get("/static/motionmodule.css")
        css = stylesheet.data
        stylesheet.close()
        self.assertEqual(stylesheet.status_code, 200)
        fonts = re.findall(rb'url\("(fonts/[^"]+\.woff2)"\)', css)
        self.assertEqual(len(fonts), 2)
        for font in fonts:
            with self.subTest(font=font):
                response = self.client.get("/static/" + font.decode("ascii"))
                body = response.data
                response.close()
                self.assertEqual(response.status_code, 200)
                self.assertTrue(body.startswith(b"wOF2"))

    def test_static_assets_are_cacheable_but_downloads_are_not(self):
        response = self.client.get("/static/motionmodule.js")
        response.close()
        self.assertTrue(response.cache_control.public)
        self.assertEqual(response.cache_control.max_age, STATIC_MAX_AGE_SECONDS)
        download = self.client.get("/api/hardware-file")
        download.close()
        self.assertNotEqual(download.cache_control.max_age, STATIC_MAX_AGE_SECONDS)

    def test_a_branch_install_is_labelled_in_the_bar(self):
        with patch("motion_module.dashboard.install_ref", return_value="testing"):
            app = create_app(self.module, MecanumDrive(self.module), self.network)
        page = app.test_client().get("/").data
        self.assertIn(b'class="build-pill"', page)
        self.assertIn(b">testing</span>", page)
        with patch("motion_module.dashboard.install_ref", return_value="main"):
            app = create_app(self.module, MecanumDrive(self.module), self.network)
        self.assertNotIn(b'class="build-pill"', app.test_client().get("/").data)

    def test_config_api_matches_driver_harness_and_complete_header(self):
        data = self.client.get("/api/config").get_json()
        self.assertEqual(data["project"], "Mecanum")
        self.assertTrue(data["bom_url"].endswith("/BOM.md"))
        self.assertEqual(data["servos"]["channels"], list(range(16)))
        profile_ids = {profile["id"] for profile in data["servos"]["profiles"]}
        self.assertEqual(
            profile_ids,
            {
                "gobilda_300_position",
                "gobilda_5_turn_position",
                "gobilda_continuous",
                "generic_180_position",
                "generic_360_position",
            },
        )
        self.assertEqual(len(data["header"]), 40)
        by_motor = {item["motor"]: item for item in data["motors"]}
        bench_by_motor = {item["motor"]: item for item in data["bench_motors"]}
        self.assertEqual((by_motor[1]["driver"], by_motor[1]["output"]), (1, "A"))
        self.assertEqual((by_motor[3]["driver"], by_motor[3]["output"]), (2, "A"))
        self.assertEqual(bench_by_motor[1]["name"], "front_left")
        self.assertEqual(data["header"][39]["role"], "front_right · Driver 2A IN1")

    def test_embedded_guide_is_available_locally_and_uses_active_names(self):
        data = self.client.get("/api/config").get_json()
        guide = data["hardware_guide"]
        standalone = self.client.get("/api/hardware-guide").get_json()
        self.assertEqual(guide, {key: value for key, value in standalone.items() if key != "ok"})
        self.assertEqual(len(guide["wiring"]["servo_boards"][0]["outputs"]), 16)
        self.assertEqual(guide["wiring"]["motor_connections"][0]["name"], "front_left")
        self.assertTrue(guide["parts_groups"])
        self.assertTrue(all(pin["detail"] for pin in data["header"]))

    def test_hardware_download_preserves_live_configuration_when_source_differs(self):
        motor = replace(self.module.config.motors[0], name="custom_intake", forward_gpio=17)
        self.module.config = replace(self.module.config, motors=(motor,))
        response = self.client.get("/api/hardware-file")
        self.assertEqual(response.status_code, 200)
        self.assertIn("hardware.py", response.headers["Content-Disposition"])
        with tempfile.TemporaryDirectory() as directory:
            downloaded = Path(directory) / "hardware.py"
            downloaded.write_bytes(response.data)
            self.assertEqual(load_hardware_file(downloaded), self.module.config)
        self.assertEqual(self.client.get("/api/config").get_json()["hardware_file"]["source"], "runtime")

    def test_hardware_download_tracks_runtime_after_source_file_is_edited(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "hardware.py"
            source.write_text(hardware_source(self.module.config), encoding="utf-8")
            app = create_app(self.module, config_path=source)
            client = app.test_client()
            self.assertEqual(client.get("/api/config").get_json()["hardware_file"]["path"], str(source))
            source.write_text("HARDWARE = {}\n", encoding="utf-8")
            downloaded = Path(directory) / "downloaded.py"
            downloaded.write_bytes(client.get("/api/hardware-file").data)
            self.assertEqual(load_hardware_file(downloaded), self.module.config)
            self.assertEqual(client.get("/api/config").get_json()["hardware_file"]["source"], "runtime")

    def test_dashboard_reports_custom_active_project(self):
        app = create_app(
            self.module, MecanumDrive(self.module), self.network, project_name="WalkingRobot"
        )
        client = app.test_client()
        self.assertEqual(client.get("/api/status").get_json()["system"]["active_project"], "WalkingRobot")
        code_page = client.get("/code").data
        self.assertIn(b"ACTIVE \xc2\xb7 WalkingRobot", code_page)
        self.assertIn(b"Driver Station", code_page)
        self.assertNotIn(b"class RobotDrive", code_page)

    def test_sample_project_download_contains_complete_python_folder(self):
        response = self.client.get("/api/projects/sample")
        self.assertEqual(response.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(response.data)) as archive:
            names = set(archive.namelist())
        self.assertIn("Mecanum/robot.py", names)
        self.assertIn("Mecanum/hardware.py", names)
        self.assertIn("Mecanum/sensors.py", names)
        self.assertIn("Mecanum/dashboard.py", names)
        self.assertIn("Mecanum/autonomous.py", names)
        self.assertIn("Mecanum/README.md", names)
        # The GIGA firmware installs from the Pi, so projects no longer carry it.
        self.assertFalse(any(name.endswith(".ino") for name in names))

    def test_update_panel_reports_branches_and_guards_installs(self):
        class Checker:
            """Stands in for the GitHub check."""

            def __init__(self):
                self.started = []
                self.refreshed = []

            def snapshot(self, refresh=False):
                self.refreshed.append(refresh)
                return {
                    "repository": "AloeVeraZ/MotionModule",
                    "installed": {"ref": "testing", "commit": "abc1234"},
                    "lines": [
                        {"ref": "testing", "label": "Testing line", "current": True,
                         "status": "update-available", "latest": "def5678", "installed": "abc1234",
                         "action": "Update now", "note": ""},
                        {"ref": "main", "label": "Main line", "current": False,
                         "status": "other-line", "latest": "999aaaa", "installed": "",
                         "action": "Switch to the main line", "note": ""},
                    ],
                    "checking": False, "checked_at": 1.0, "error": "", "installable": True,
                    "job": {"state": "idle", "log": [], "finished_at": None, "result": ""},
                }

            def start_update(self, ref, password=None):
                if ref not in ("main", "testing"):
                    from motion_module.errors import MotionModuleError

                    raise MotionModuleError("MotionModule installs the main or the testing branch")
                self.started.append(ref)
                return f"Installing the {ref} branch."

            def close(self):
                pass

        checker = Checker()
        app = create_app(self.module, MecanumDrive(self.module), self.network, update_checker=checker)
        client = app.test_client()
        headers = {"X-MotionModule-Token": app.config["DASHBOARD_TOKEN"]}

        data = client.get("/api/updates").get_json()
        self.assertTrue(data["ok"])
        self.assertEqual([line["ref"] for line in data["lines"]], ["testing", "main"])
        self.assertEqual(data["installed"]["ref"], "testing")
        client.get("/api/updates?refresh=1")
        self.assertEqual(checker.refreshed, [False, True])

        self.assertEqual(client.post("/api/updates", json={"ref": "testing"}).status_code, 403)
        refused = client.post("/api/updates", headers=headers, json={"ref": "somewhere-else"})
        self.assertEqual(refused.status_code, 400)
        self.assertIn("main or the testing", refused.get_json()["error"])
        self.assertEqual(checker.started, [])

        started = client.post("/api/updates", headers=headers, json={"ref": "testing"})
        self.assertEqual(started.status_code, 202)
        self.assertEqual(checker.started, ["testing"])
        # Outputs stop before the software is replaced.
        self.assertTrue(self.module.stopped)

    def test_an_update_asks_for_the_sudo_password_when_sudo_wants_one(self):
        from motion_module.updates import PasswordRequired, TooManyPasswordAttempts

        class Checker:
            """sudo on this Pi wants a password, and it is hunter2."""

            def __init__(self):
                self.passwords = []
                self.limited = False

            def start_update(self, ref, password=None):
                self.passwords.append(password)
                if self.limited:
                    raise TooManyPasswordAttempts("Too many wrong passwords. Wait 10 minutes, then try again.")
                if not password:
                    raise PasswordRequired("This update needs the password sudo asks for on this Pi.", user="aloe")
                if password != "hunter2":
                    raise PasswordRequired("That password was not accepted. Try again.", user="aloe", rejected=True)
                return f"Installing the {ref} branch."

            def close(self):
                pass

        checker = Checker()
        app = create_app(self.module, MecanumDrive(self.module), self.network, update_checker=checker)
        client = app.test_client()
        headers = {"X-MotionModule-Token": app.config["DASHBOARD_TOKEN"]}

        asked = client.post("/api/updates", headers=headers, json={"ref": "testing"})
        self.assertEqual(asked.status_code, 401)
        self.assertEqual(asked.get_json()["password_required"], True)
        self.assertEqual(asked.get_json()["rejected"], False)
        self.assertEqual(asked.get_json()["user"], "aloe")

        wrong = client.post("/api/updates", headers=headers, json={"ref": "testing", "password": "letmein"})
        self.assertEqual(wrong.status_code, 401)
        self.assertEqual(wrong.get_json()["rejected"], True)
        self.assertNotIn("letmein", wrong.get_data(as_text=True))

        started = client.post("/api/updates", headers=headers, json={"ref": "testing", "password": "hunter2"})
        self.assertEqual(started.status_code, 202)
        self.assertNotIn("hunter2", started.get_data(as_text=True))
        self.assertEqual(checker.passwords, [None, "letmein", "hunter2"])

        self.assertEqual(client.post("/api/updates", headers=headers,
                                     json={"ref": "testing", "password": ["hunter2"]}).status_code, 400)
        self.assertEqual(client.post("/api/updates", json={"ref": "testing", "password": "hunter2"}).status_code, 403)
        self.assertEqual(len(checker.passwords), 3, "a refused request never reaches the update")

        checker.limited = True
        limited = client.post("/api/updates", headers=headers, json={"ref": "testing", "password": "guess"})
        self.assertEqual(limited.status_code, 429)
        self.assertIn("Wait", limited.get_json()["error"])

    def test_giga_firmware_status_and_install_are_guarded(self):
        status = self.client.get("/api/giga/firmware").get_json()
        self.assertTrue(status["ok"])
        self.assertEqual(status["job"]["state"], "idle")
        self.assertFalse(status["installable"])  # no installed Pi runtime here
        self.assertEqual(self.client.post("/api/giga/firmware").status_code, 403)
        refused = self.client.post("/api/giga/firmware", headers=self.headers)
        self.assertEqual(refused.status_code, 503)

    def test_giga_firmware_install_pauses_the_bridge_and_reports_progress(self):
        class Bridge:
            firmware = "1"
            released = started = 0

            def release(self):
                Bridge.released += 1
                return True

            def start(self):
                Bridge.started += 1

        def flash(log):
            log("Writing firmware 2.0.0 (137 KB)...")
            return {"version": "2.0.0", "verified": True}

        with tempfile.TemporaryDirectory() as directory, \
                patch("motion_module.dashboard.active_bridges", return_value=[Bridge()]), \
                patch("motion_module.dashboard.flash_giga", side_effect=flash):
            app = create_app(self.module, MecanumDrive(self.module), self.network,
                             workspace_directory=directory, restart_callback=lambda: None)
            client = app.test_client()
            headers = {"X-MotionModule-Token": app.config["DASHBOARD_TOKEN"]}
            self.assertEqual(client.post("/api/giga/firmware", headers=headers).status_code, 202)
            deadline = time.monotonic() + 5
            while client.get("/api/giga/firmware").get_json()["job"]["state"] == "running":
                self.assertLess(time.monotonic(), deadline)
                time.sleep(0.02)
            job = client.get("/api/giga/firmware").get_json()["job"]
        self.assertEqual(job["state"], "done")
        self.assertEqual(job["version"], "2.0.0")
        self.assertIn("Writing firmware 2.0.0 (137 KB)...", job["log"])
        self.assertEqual((Bridge.released, Bridge.started), (1, 1))
        self.assertTrue(self.module.stopped)

    def test_optional_dashboard_telemetry_api_exposes_typed_inputs(self):
        class Dashboard:
            def snapshot(self):
                return {
                    "cameras": [{"name": "Front", "url": "/camera/front"}],
                    "imu": {"name": "Pigeon", "yaw": 18, "pitch": 2, "roll": -1},
                    "sensors": [
                        {"name": "Range", "value": 42, "kind": "analog", "unit": "cm"},
                        {"name": "Beam", "value": True, "kind": "digital"},
                    ],
                }

        app = create_app(self.module, dashboard_telemetry=Dashboard(), project_name="SensorBot")
        data = app.test_client().get("/api/drive/telemetry").get_json()
        self.assertTrue(data["configured"])
        self.assertEqual(data["cameras"][0]["name"], "Front")
        self.assertEqual(data["imu"]["yaw"], 18.0)
        self.assertEqual([item["kind"] for item in data["sensors"]], ["analog", "digital"])
        self.assertEqual(data["pi_inputs"], data["sensors"])
        self.assertTrue(data["pi_gpio"]["digital_only"])

    def test_giga_is_auto_discovered_and_merged_with_project_pin_data(self):
        class Dashboard:
            def snapshot(self):
                return {
                    "usb_controllers": [{
                        "name": "GIGA",
                        "board_id": "arduino_giga_r1_wifi",
                        "connected": False,
                        "bridge": "waiting-for-bridge",
                        "pins": [{"name": "Beam", "value": None, "kind": "digital", "channel": "D22", "connected": False}],
                    }],
                }

        discovered = [{
            "name": "Arduino GIGA R1 WiFi",
            "board_id": "arduino_giga_r1_wifi",
            "connected": True,
            "serial": "GIGA123",
            "port": "/dev/ttyACM0",
            "bridge": "detected",
            "digital_pins": ["D0", "D75"],
            "analog_pins": ["A0", "A7"],
            "adc_bits": 12,
            "pins": [],
        }]
        with patch("motion_module.dashboard.sensor_controllers", return_value=discovered):
            app = create_app(self.module, dashboard_telemetry=Dashboard())
            data = app.test_client().get("/api/drive/telemetry").get_json()
        giga = data["usb_controllers"][0]
        self.assertTrue(giga["connected"])
        self.assertEqual(giga["port"], "/dev/ttyACM0")
        self.assertEqual(giga["pins"][0]["channel"], "D22")
        self.assertEqual(giga["digital_pins"], ["D0", "D75"])

    def test_project_dashboard_file_is_optional_and_auto_discovered(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "robot.py"
            project.write_text("# robot placeholder\n", encoding="utf-8")
            self.assertIsNone(load_dashboard_telemetry(self.module, MecanumDrive(self.module), project))
            project.with_name("dashboard.py").write_text(
                "class Dashboard:\n"
                "    def snapshot(self):\n"
                "        return {'sensors': [{'name': 'Limit', 'value': False, 'kind': 'digital'}]}\n"
                "def create_dashboard(module, drive):\n"
                "    return Dashboard()\n",
                encoding="utf-8",
            )
            telemetry = load_dashboard_telemetry(self.module, MecanumDrive(self.module), project)
            self.assertEqual(telemetry.snapshot()["sensors"][0]["name"], "Limit")

    def test_browser_folder_deploy_requires_token_and_restarts(self):
        hardware = b'''HARDWARE = {"module": {"pwm_hz": 1000, "deadtime_ms": 2, "watchdog_ms": 500}, "motors": {1: {"forward_gpio": 4, "reverse_gpio": 17, "inverted": False}}, "servos": {"enabled": True, "i2c_bus": 1, "frequency_hz": 50, "addresses": [0x40], "minimum_pulse_us": 500, "maximum_pulse_us": 2500}}\n'''
        with tempfile.TemporaryDirectory() as directory:
            restarted = threading.Event()
            app = create_app(
                self.module,
                MecanumDrive(self.module),
                self.network,
                project_name="Mecanum",
                terminal_manager=self.terminal,
                workspace_directory=directory,
                restart_callback=restarted.set,
            )
            client = app.test_client()
            payload = {
                "project_name": "TestBot",
                "paths": ["TestBot/robot.py", "TestBot/hardware.py"],
                "files": [
                    (io.BytesIO(b"def create_drive(module):\n    return module\n"), "TestBot/robot.py"),
                    (io.BytesIO(hardware), "TestBot/hardware.py"),
                ],
            }
            denied = client.post("/api/projects/deploy", data=payload)
            self.assertEqual(denied.status_code, 403)
            payload["files"] = [
                (io.BytesIO(b"def create_drive(module):\n    return module\n"), "TestBot/robot.py"),
                (io.BytesIO(hardware), "TestBot/hardware.py"),
            ]
            with patch("motion_module.dashboard.activate_project") as activate, patch(
                "motion_module.dashboard.time.sleep", return_value=None
            ):
                accepted = client.post(
                    "/api/projects/deploy",
                    headers={"X-MotionModule-Token": app.config["DASHBOARD_TOKEN"]},
                    data=payload,
                )
                self.assertEqual(accepted.status_code, 202)
                self.assertTrue(restarted.wait(1))
            self.assertTrue(self.module.stopped)
            self.assertTrue((Path(directory) / "robots" / "TestBot" / "hardware.py").is_file())
            activate.assert_called_once()

    def test_usb_api_exposes_read_only_inventory(self):
        with patch("motion_module.dashboard.usb_devices", return_value={
            "available": True,
            "devices": [{"vendor_id": "1234", "product_id": "abcd"}],
            "error": "",
        }):
            data = self.client.get("/api/usb").get_json()
        self.assertTrue(data["ok"])
        self.assertEqual(data["devices"][0]["vendor_id"], "1234")

    def test_custom_project_requires_the_documented_drive_factory(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "robot.py"
            project.write_text("name = 'missing factory'\n", encoding="utf-8")
            with self.assertRaisesRegex(RuntimeError, "must define create_drive"):
                load_drive(self.module, project)

    def test_drive_requires_session_token_and_ignores_stale_packets(self):
        denied = self.client.post("/api/drive", json={"sequence": 1})
        self.assertEqual(denied.status_code, 403)
        response = self.client.post(
            "/api/drive", headers=self.headers,
            json={"sequence": 3, "forward": 0, "strafe": 0, "rotate": 1, "speed": 0.4},
        )
        self.assertEqual(response.status_code, 200)
        # A left turn runs the front-left wheel (channel 1) backward.
        self.assertEqual(self.module.outputs[1], -0.4)

    def test_mecanum_test_route_uses_the_built_in_mixer_not_the_project(self):
        """Test Mecanum must work on a robot whose own drive() is broken."""

        class BrokenDrive:
            def drive(self, *_args, **_kwargs):
                raise AssertionError("Test Mecanum must not call the project's drive()")

            def stop(self):
                pass

        app = create_app(self.module, BrokenDrive(), project_name="Mecanum")
        client = app.test_client()
        headers = {"X-MotionModule-Token": app.config["DASHBOARD_TOKEN"]}
        self.assertEqual(client.post("/api/mecanum/test", json={"sequence": 1}).status_code, 403)
        response = client.post(
            "/api/mecanum/test", headers=headers,
            json={"sequence": 1, "forward": 0, "strafe": 0, "rotate": 1, "speed": 0.4},
        )
        self.assertEqual(response.status_code, 200)
        # A left turn runs both left wheels back and both right wheels forward.
        self.assertEqual(
            [self.module.outputs[channel] for channel in (1, 2, 3, 4)],
            [-0.4, -0.4, 0.4, 0.4],
        )

    def test_page_reload_can_resume_above_server_sequence_floor(self):
        first = self.client.post(
            "/api/drive", headers=self.headers,
            json={"sequence": 250, "forward": 0.5, "speed": 0.2},
        )
        self.assertEqual(first.status_code, 200)
        self.client.post("/api/stop")
        floor = self.client.get("/api/config").get_json()["drive_sequence_floor"]
        self.assertEqual(floor, 250)
        stale = self.client.post("/api/drive", headers=self.headers, json={"sequence": floor})
        self.assertEqual(stale.get_json()["ignored"], "stale sequence")
        resumed = self.client.post(
            "/api/drive", headers=self.headers,
            json={"sequence": floor + 1, "forward": 0.5, "speed": 0.2},
        )
        self.assertNotIn("ignored", resumed.get_json())
        self.assertEqual(resumed.status_code, 200)

    def test_stop_reaches_all_motor_outputs_even_when_robot_stop_hook_fails(self):
        class BrokenDrive:
            def stop(self):
                raise RuntimeError("broken student stop hook")

        app = create_app(self.module, drive=BrokenDrive())
        self.module.outputs[8] = 0.2
        with self.assertLogs(app.logger, level="ERROR"):
            response = app.test_client().post("/api/stop")
        self.assertEqual(response.status_code, 500)
        self.assertTrue(self.module.stopped)
        self.assertTrue(all(value == 0 for value in self.module.outputs.values()))

    def test_stop_releases_servo_commands_and_cancels_pending_timers(self):
        with patch("motion_module.dashboard.threading.Timer") as timer_type:
            command = self.client.post(
                "/api/servos/set", headers=self.headers,
                json={"board": 0, "channel": 4, "angle": 90, "confirmed": True},
            )
            self.assertEqual(command.status_code, 200)
            # Also stop a servo commanded by robot code outside the debug UI.
            self.module.servo(8).set_angle(45)
            self.module.outputs[8] = 0.2
            response = self.client.post("/api/stop")
            self.assertEqual(response.status_code, 200)
            timer_type.return_value.cancel.assert_called()
        self.assertTrue(all(value == 0 for value in self.module.outputs.values()))
        self.assertEqual(self.module._servos.pulses, {})
        self.assertEqual(self.module._servos.angles, {})
        status = self.client.get("/api/status").get_json()["robot"]
        self.assertEqual(status["servo_commands"], {})
        self.assertEqual(status["servos"], {})
        self.assertEqual(status["servo_outputs"], {})

    def test_motor_test_requires_confirmation_and_caps_power(self):
        denied = self.client.post(
            "/api/motors/test", headers=self.headers,
            json={"channel": 5, "power": 0.5},
        )
        self.assertEqual(denied.status_code, 400)
        too_high = self.client.post(
            "/api/motors/test", headers=self.headers,
            json={"channel": 5, "power": 0.51, "confirmed": True},
        )
        self.assertEqual(too_high.status_code, 400)
        accepted = self.client.post(
            "/api/motors/test", headers=self.headers,
            json={"channel": 5, "power": -0.5, "confirmed": True},
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(self.module.outputs[5], -0.5)

    def test_bench_and_drive_use_the_same_rear_wheel_polarity_in_both_directions(self):
        config = load_project_config(EXAMPLE_DIR)
        gpio = MockGPIO()
        with MotionModule(config, gpio=gpio) as module:
            app = create_app(module, MecanumDrive(module), self.network, project_name="Mecanum")
            client = app.test_client()
            headers = {"X-MotionModule-Token": app.config["DASHBOARD_TOKEN"]}

            pairs = ((1, 26, 19), (2, 6, 13), (3, 21, 20), (4, 12, 16))
            for direction in (1, -1):
                for channel, positive, negative in pairs:
                    with self.subTest(direction=direction, channel=channel):
                        response = client.post(
                            "/api/motors/test", headers=headers,
                            json={"channel": channel, "power": direction * 0.5, "confirmed": True},
                        )
                        self.assertEqual(response.status_code, 200)
                        driven, idle = (positive, negative) if direction > 0 else (negative, positive)
                        self.assertEqual(gpio.values[driven], 0.5)
                        self.assertEqual(gpio.values[idle], 0)
                        client.post("/api/stop", headers=headers)

                response = client.post(
                    "/api/drive", headers=headers,
                    json={"sequence": 2 - direction, "forward": direction, "speed": 0.5},
                )
                self.assertEqual(response.status_code, 200)
                for _, positive, negative in pairs:
                    driven, idle = (positive, negative) if direction > 0 else (negative, positive)
                    self.assertEqual(gpio.values[driven], 0.5)
                    self.assertEqual(gpio.values[idle], 0)
                client.post("/api/stop", headers=headers)
                self.assertTrue(all(gpio.values[pin] == 0 for _, a, b in pairs for pin in (a, b)))

    def test_both_rotation_routes_hold_full_selected_power_on_opposite_sides(self):
        config = load_project_config(EXAMPLE_DIR)
        gpio = MockGPIO()
        with MotionModule(config, gpio=gpio) as module:
            app = create_app(module, MecanumDrive(module), self.network, project_name="Mecanum")
            client = app.test_client()
            headers = {"X-MotionModule-Token": app.config["DASHBOARD_TOKEN"]}
            sequence = 0
            # Fixed GPIOs after the existing B-output inversion. For Q,
            # physical left wheels go backward and right wheels forward.
            pairs = ((1, 19, 26), (2, 13, 6), (3, 21, 20), (4, 12, 16))
            for route in ("/api/mecanum/test", "/api/drive"):
                for rotate in (1, -1):
                    for tick in range(15):
                        sequence += 1
                        with self.subTest(route=route, rotate=rotate, tick=tick):
                            response = client.post(route, headers=headers, json={
                                "sequence": sequence, "forward": 0, "strafe": 0,
                                "rotate": rotate, "speed": 0.4,
                            })
                            self.assertEqual(response.status_code, 200)
                            self.assertNotIn("ignored", response.get_json())
                            self.assertEqual(
                                [module.motor_values[c] for c in (1, 2, 3, 4)],
                                [-0.4 * rotate, -0.4 * rotate, 0.4 * rotate, 0.4 * rotate],
                            )
                            for _, positive, negative in pairs:
                                driven, idle = (positive, negative) if rotate > 0 else (negative, positive)
                                self.assertEqual(gpio.values[driven], 0.4)
                                self.assertEqual(gpio.values[idle], 0)
                    client.post("/api/stop")
                    self.assertTrue(all(value == 0 for value in module.motor_values.values()))

    def test_a_project_without_autonomous_py_reports_it_and_cannot_start_one(self):
        status = self.client.get("/api/autonomous").get_json()
        self.assertFalse(status["configured"])
        self.assertEqual(status["state"], "idle")
        refused = self.client.post("/api/autonomous/start", json={"confirmed": True},
                                   headers=self.headers)
        self.assertEqual(refused.status_code, 409)
        self.assertIn("no autonomous.py", refused.get_json()["error"])

    def test_autonomous_runs_blocks_manual_driving_and_is_ended_by_stop(self):
        import threading
        import time

        released = threading.Event()

        class Routine:
            duration_seconds = 5

            def run(self, stop):
                released.set()
                while not stop.is_set():
                    time.sleep(0.01)

        module = FakeModule()
        app = create_app(module, MecanumDrive(module), FakeNetwork(),
                         project_name="Mecanum", terminal_manager=FakeTerminal(),
                         autonomous_routine=Routine())
        client = app.test_client()
        headers = {"X-MotionModule-Token": app.config["DASHBOARD_TOKEN"]}

        self.assertTrue(client.get("/api/autonomous").get_json()["configured"])
        # Enabling is deliberate, the same as every other moving control.
        unconfirmed = client.post("/api/autonomous/start", json={}, headers=headers)
        self.assertEqual(unconfirmed.status_code, 400)
        self.assertEqual(client.post("/api/autonomous/start",
                                     json={"confirmed": True}).status_code, 403)

        started = client.post("/api/autonomous/start", json={"confirmed": True}, headers=headers)
        self.assertEqual(started.status_code, 200)
        self.assertTrue(released.wait(2))
        self.assertEqual(client.get("/api/autonomous").get_json()["state"], "running")

        # The driver cannot fight the routine for the motors.
        manual = client.post("/api/drive", json={"sequence": 5, "forward": 1},
                             headers=headers)
        self.assertEqual(manual.status_code, 409)
        self.assertIn("autonomous", manual.get_json()["error"])

        # STOP ends the routine, not just the outputs it was writing.
        self.assertEqual(client.post("/api/stop").status_code, 200)
        self.assertEqual(client.get("/api/autonomous").get_json()["state"], "stopped")
        self.assertTrue(module.stopped)
        self.assertEqual(client.post("/api/drive", json={"sequence": 6, "forward": 0},
                                     headers=headers).status_code, 200)

    def test_output_enable_endpoint_disables_and_re_enables_the_servo_outputs(self):
        self.client.post("/api/servos/set", json={
            "board": 0, "channel": 3, "profile": "generic_180_position",
            "value": 40, "confirmed": True,
        }, headers=self.headers)

        off = self.client.post("/api/servos/output-enable", json={"enabled": False},
                               headers=self.headers)
        self.assertEqual(off.status_code, 200)
        self.assertFalse(off.get_json()["enabled"])
        # Cutting OE also clears what the page believed was being held.
        self.assertEqual(self.client.get("/api/status").get_json()["robot"]["servo_commands"], {})

        refused = self.client.post("/api/servos/set", json={
            "board": 0, "channel": 3, "profile": "generic_180_position",
            "value": 40, "confirmed": True,
        }, headers=self.headers)
        self.assertEqual(refused.status_code, 409)
        self.assertIn("OE", refused.get_json()["error"])

        on = self.client.post("/api/servos/output-enable", json={"enabled": True},
                              headers=self.headers)
        self.assertTrue(on.get_json()["enabled"])
        allowed = self.client.post("/api/servos/set", json={
            "board": 0, "channel": 3, "profile": "generic_180_position",
            "value": 40, "confirmed": True,
        }, headers=self.headers)
        self.assertEqual(allowed.status_code, 200)

    def test_output_enable_endpoint_needs_a_session_and_a_boolean(self):
        self.assertEqual(
            self.client.post("/api/servos/output-enable", json={"enabled": False}).status_code, 403)
        self.assertEqual(
            self.client.post("/api/servos/output-enable", json={"enabled": "off"},
                             headers=self.headers).status_code, 400)

    def test_servo_test_and_release_are_guarded(self):
        response = self.client.post(
            "/api/servos/set", headers=self.headers,
            json={"board": 0, "channel": 3, "angle": 90, "confirmed": True},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.module._servos.angles[(0, 3)], 90)
        self.assertEqual(
            self.client.get("/api/status").get_json()["robot"]["servo_commands"]["0:3"]["value"],
            90,
        )
        release = self.client.post(
            "/api/servos/release", headers=self.headers,
            json={"board": 0, "channel": 3},
        )
        self.assertEqual(release.status_code, 200)
        self.assertNotIn((0, 3), self.module._servos.angles)
        self.assertNotIn((0, 3), self.module._servos.pulses)
        self.assertNotIn(
            "0:3", self.client.get("/api/status").get_json()["robot"]["servo_commands"]
        )

    def test_servo_profiles_map_go_bilda_position_and_continuous_modes(self):
        position = self.client.post(
            "/api/servos/set",
            headers=self.headers,
            json={
                "board": 0,
                "channel": 15,
                "profile": "gobilda_5_turn_position",
                "value": 900,
                "confirmed": True,
            },
        )
        self.assertEqual(position.status_code, 200)
        self.assertEqual(position.get_json()["pulse_us"], 1500)
        self.assertEqual(self.module._servos.pulses[(0, 15)], 1500)

        stopped = self.client.post(
            "/api/servos/set",
            headers=self.headers,
            json={
                "board": 0,
                "channel": 2,
                "profile": "gobilda_continuous",
                "value": 0,
                "confirmed": True,
            },
        )
        self.assertEqual(stopped.status_code, 200)
        self.assertEqual(stopped.get_json()["pulse_us"], 1500)
        self.assertEqual(stopped.get_json()["unit"], "%")

        out_of_range = self.client.post(
            "/api/servos/set",
            headers=self.headers,
            json={
                "board": 0,
                "channel": 2,
                "profile": "gobilda_300_position",
                "value": 301,
                "confirmed": True,
            },
        )
        self.assertEqual(out_of_range.status_code, 400)
        invalid_channel = self.client.post(
            "/api/servos/set",
            headers=self.headers,
            json={
                "board": 0,
                "channel": 16,
                "profile": "gobilda_300_position",
                "value": 150,
                "confirmed": True,
            },
        )
        self.assertEqual(invalid_channel.status_code, 400)

    def test_web_terminal_requires_both_dashboard_and_temporary_session_tokens(self):
        no_dashboard_token = self.client.post(
            "/api/terminal/start", json={"access_code": "test-code"}
        )
        self.assertEqual(no_dashboard_token.status_code, 403)
        wrong_code = self.client.post(
            "/api/terminal/start",
            headers=self.headers,
            json={"access_code": "wrong"},
        )
        self.assertEqual(wrong_code.status_code, 403)
        started = self.client.post(
            "/api/terminal/start",
            headers=self.headers,
            json={"access_code": "test-code"},
        )
        self.assertEqual(started.status_code, 200)
        token = started.get_json()["token"]
        missing_terminal_token = self.client.post(
            "/api/terminal/input",
            headers=self.headers,
            json={"input": "pwd\n"},
        )
        self.assertEqual(missing_terminal_token.status_code, 403)
        terminal_headers = {**self.headers, "X-MotionModule-Terminal": token}
        written = self.client.post(
            "/api/terminal/input",
            headers=terminal_headers,
            json={"input": "pwd\n"},
        )
        self.assertEqual(written.status_code, 200)
        self.assertEqual(self.terminal.commands, ["pwd\n"])
        output = self.client.post(
            "/api/terminal/output",
            headers=terminal_headers,
            json={"cursor": 0},
        ).get_json()
        self.assertIn("motionmodule", output["output"])
        self.client.post("/api/terminal/interrupt", headers=terminal_headers, json={})
        self.assertTrue(self.terminal.interrupted)
        self.client.post("/api/terminal/stop", headers=terminal_headers, json={})
        self.assertTrue(self.terminal.stopped)

    def test_web_terminal_rate_limits_access_code_guesses(self):
        for _ in range(10):
            response = self.client.post(
                "/api/terminal/start",
                headers=self.headers,
                json={"access_code": "wrong"},
            )
            self.assertEqual(response.status_code, 403)
        limited = self.client.post(
            "/api/terminal/start",
            headers=self.headers,
            json={"access_code": "test-code"},
        )
        self.assertEqual(limited.status_code, 429)

    def test_network_api_stops_outputs_before_switch(self):
        self.module.outputs[1] = 0.4
        with patch("motion_module.dashboard.time.sleep", return_value=None):
            accepted = self.client.post(
                "/api/network/hotspot", headers=self.headers,
                json={"ssid": "Robot", "password": ""},
            )
            self.assertEqual(accepted.status_code, 202)
            self.assertTrue(self.network.called.wait(1))
        self.assertTrue(self.module.stopped)
        self.assertEqual(self.network.hotspot_payload, {"ssid": "Robot"})

    def test_hostname_api_normalizes_local_suffix_and_stops_outputs(self):
        self.module.outputs[1] = 0.4
        with patch("motion_module.dashboard.time.sleep", return_value=None):
            accepted = self.client.post(
                "/api/network/hostname", headers=self.headers,
                json={"hostname": "Robot-07.local"},
            )
            self.assertEqual(accepted.status_code, 202)
            self.assertTrue(self.network.called.wait(1))
        self.assertTrue(self.module.stopped)
        self.assertEqual(self.network.hostname_payload, {"hostname": "robot-07"})

    def test_hostname_api_rejects_username_and_spaces(self):
        for hostname in ("angelo@robot", "robot name", "-robot"):
            with self.subTest(hostname=hostname):
                response = self.client.post(
                    "/api/network/hostname", headers=self.headers, json={"hostname": hostname}
                )
                self.assertEqual(response.status_code, 400)


class DashboardAssetHelperTests(unittest.TestCase):
    def test_asset_version_changes_when_any_static_file_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            static = Path(directory)
            (static / "fonts").mkdir()
            (static / "site.css").write_text("body {}", encoding="utf-8")
            (static / "fonts" / "face.woff2").write_bytes(b"font")
            first = static_asset_version(static)
            self.assertEqual(first, static_asset_version(static))
            (static / "fonts" / "face.woff2").write_bytes(b"another font")
            self.assertNotEqual(first, static_asset_version(static))

    def test_install_ref_reads_the_release_marker_and_rejects_anything_else(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self.assertEqual(install_ref(root), "")
            (root / "INSTALL_REF").write_text("testing\n", encoding="utf-8")
            self.assertEqual(install_ref(root), "testing")
            (root / "INSTALL_REF").write_text("<script>alert(1)</script>\n", encoding="utf-8")
            self.assertEqual(install_ref(root), "")


if __name__ == "__main__":
    unittest.main()
