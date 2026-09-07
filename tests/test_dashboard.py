import io
import threading
import tempfile
import unittest
import sys
import zipfile
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from motion_module.config import hardware_source, load_hardware_file, load_project_config
from motion_module.dashboard import create_app, load_dashboard_telemetry, load_drive
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

    def set_motors(self, outputs):
        for reference, value in outputs.items():
            self.outputs[self.config.motor_channel(reference)] = value

    def stop_all(self):
        self.stopped = True
        self.outputs = {channel: 0.0 for channel in range(1, 9)}

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

    def test_drive_is_its_own_page_with_bindings_and_a_controller(self):
        drive = self.client.get("/drive").data
        self.assertIn(b'data-view="drive"', drive)
        self.assertIn(b'id="driveEnable"', drive)
        self.assertIn(b'id="bindingList"', drive)      # remappable keys
        self.assertIn(b'id="padIdentity"', drive)      # game controller
        self.assertIn(b'id="customControls"', drive)   # project-declared controls
        self.assertIn(b'id="cameraStage"', drive)      # one/two-camera square workspace
        self.assertIn(b'id="headingDial"', drive)      # dedicated IMU orientation
        self.assertIn(b'id="sensorList"', drive)       # analog/digital sensor tray
        self.assertIn(b"dashboard.py", drive)
        self.assertIn(b"gamepadconnected", drive)
        # Drive left the Code page entirely.
        code = self.client.get("/code").data
        self.assertNotIn(b'data-tab="drive"', code)

    def test_legacy_dashboard_urls_open_the_consolidated_pages(self):
        for path, active in (("/hardware", b'data-page="diagnostics"'), ("/network", b'data-page="diagnostics"')):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)
            self.assertIn(active, response.data)

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
        motor = replace(self.module.config.motors[0], name="custom_intake", forward_gpio=4)
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
        self.assertIn("Mecanum/dashboard.py", names)
        self.assertIn("Mecanum/README.md", names)

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
        self.assertEqual(self.module.outputs[1], 0.4)

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
            json={"channel": 5, "power": 0.15},
        )
        self.assertEqual(denied.status_code, 400)
        too_high = self.client.post(
            "/api/motors/test", headers=self.headers,
            json={"channel": 5, "power": 0.21, "confirmed": True},
        )
        self.assertEqual(too_high.status_code, 400)
        accepted = self.client.post(
            "/api/motors/test", headers=self.headers,
            json={"channel": 5, "power": -0.15, "confirmed": True},
        )
        self.assertEqual(accepted.status_code, 200)
        self.assertEqual(self.module.outputs[5], -0.15)

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


if __name__ == "__main__":
    unittest.main()
