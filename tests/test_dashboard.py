import io
import threading
import tempfile
import unittest
import sys
import zipfile
from pathlib import Path
from unittest.mock import patch

from motion_module.config import load_config
from motion_module.dashboard import create_app, load_drive
from motion_module.servo import MockServoController, Servo

EXAMPLE_DIR = Path(__file__).resolve().parents[1] / "examples" / "Mecanum"
if str(EXAMPLE_DIR) not in sys.path:
    sys.path.insert(0, str(EXAMPLE_DIR))

from mecanum import MecanumDrive  # noqa: E402


class FakeModule:
    def __init__(self):
        self.config = load_config()
        self.outputs = {channel: 0.0 for channel in range(1, 9)}
        self.stopped = False
        self._servos = MockServoController(self.config.servos)

    def set_motors(self, outputs):
        self.outputs.update(outputs)

    def stop_all(self):
        self.stopped = True
        self.outputs = {channel: 0.0 for channel in range(1, 9)}

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
        self.assertNotIn(b'data-page="drive"', debug)
        self.assertNotIn(b'data-page="hardware"', debug)
        self.assertNotIn(b'data-page="network"', debug)
        self.assertIn(b"activePage==='diagnostics'?'Debug'", debug)
        code = self.client.get("/code").data
        self.assertIn(b"Manual test control", code)
        self.assertIn(b'id="driveEnable"', code)
        self.assertIn(b"Driver Station", code)
        self.assertIn(b'id="projectFolder"', code)
        self.assertIn(b"Download Mecanum sample", code)
        self.assertIn(b"hardware.py", code)
        self.assertNotIn(b"Remote-SSH", code)
        self.assertNotIn(b"tools/push_robot.py", code)
        self.assertIn(b"Time-limited robot shell", code)
        self.assertIn(b'id="terminalCommand"', code)
        self.assertGreater(code.index(b"Time-limited robot shell"), code.index(b"Manual test control"))
        overview = self.client.get("/").data
        self.assertIn(b"Servo activity", overview)
        self.assertIn(b'id="servoChannel"', debug)
        self.assertIn(b'id="servoProfile"', debug)
        self.assertIn(b"Zero servo", debug)
        self.assertIn(b'id="hostnameForm"', debug)
        self.assertIn(b"Connected USB devices", debug)
        self.assertIn(b'id="usbDevices"', debug)
        self.assertIn(b"hostname is this robot", debug)

    def test_legacy_dashboard_urls_open_the_consolidated_pages(self):
        for path, active in (("/drive", b'data-page="code"'), ("/hardware", b'data-page="diagnostics"'), ("/network", b'data-page="diagnostics"')):
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
        self.assertEqual((by_motor[1]["driver"], by_motor[1]["output"]), (2, "A"))
        self.assertEqual((by_motor[3]["driver"], by_motor[3]["output"]), (1, "A"))
        self.assertEqual(data["header"][39]["role"], "Driver 1A IN2")

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
        self.assertIn("Mecanum/mecanum.py", names)

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
        stale = self.client.post(
            "/api/drive", headers=self.headers,
            json={"sequence": 2, "forward": 1, "strafe": 0, "rotate": 0, "speed": 1},
        )
        self.assertEqual(stale.get_json()["ignored"], "stale sequence")
        self.assertEqual(self.module.outputs[1], 0.4)

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
