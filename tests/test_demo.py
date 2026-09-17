"""The laptop demo serves the real dashboard with a simulated robot."""

import shutil
import socket
import subprocess
import unittest
from pathlib import Path

from motion_module.demo import DemoNetwork, create_demo_app, port_is_free
from motion_module.gpio import MockGPIO


ROOT = Path(__file__).resolve().parents[1]


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.app, self.module = create_demo_app("http://127.0.0.1:8080")
        self.client = self.app.test_client()
        self.headers = {"X-MotionModule-Token": self.app.config["DASHBOARD_TOKEN"]}

    def tearDown(self):
        self.module.close()

    def test_demo_never_claims_real_hardware(self):
        self.assertIsInstance(self.module.gpio, MockGPIO)
        self.assertFalse(self.client.get("/api/status").get_json()["robot"]["hardware"])

    def test_every_page_is_served(self):
        for path in ("/", "/diagnostics", "/drive", "/code", "/driver-station"):
            with self.subTest(path=path):
                self.assertEqual(self.client.get(path).status_code, 200)

    def test_driving_moves_the_simulated_motors_and_stop_halts_them(self):
        response = self.client.post(
            "/api/drive", headers=self.headers,
            json={"sequence": 1, "forward": 1, "strafe": 0, "rotate": 0, "speed": 0.5},
        )
        self.assertEqual(response.status_code, 200)
        motors = self.client.get("/api/status").get_json()["robot"]["motors"]
        self.assertTrue(any(motors.values()))
        self.client.post("/api/stop")
        motors = self.client.get("/api/status").get_json()["robot"]["motors"]
        self.assertFalse(any(motors.values()))

    def test_example_robot_brings_its_controls_and_autonomous_routine(self):
        controls = self.client.get("/api/drive/controls").get_json()["controls"]
        self.assertTrue(controls)
        self.assertTrue(self.client.get("/api/autonomous").get_json()["configured"])

    def test_driver_station_gets_simulated_cameras_imu_and_sensors(self):
        data = self.client.get("/api/drive/telemetry").get_json()
        self.assertEqual(
            [camera["url"] for camera in data["cameras"]],
            ["/demo/camera/front.svg", "/demo/camera/rear.svg"],
        )
        self.assertTrue(all(camera["connected"] for camera in data["cameras"]))
        self.assertTrue(data["imu"]["connected"])
        self.assertTrue(data["pi_inputs"])
        self.assertEqual(data["usb_controllers"][0]["bridge"], "streaming")
        camera = self.client.get("/demo/camera/front.svg")
        self.assertEqual(camera.mimetype, "image/svg+xml")
        self.assertIn(b"FRONT CAMERA", camera.data)
        self.assertEqual(self.client.get("/demo/camera/other.svg").status_code, 404)

    def test_terminal_and_deployment_stay_off(self):
        self.assertFalse(self.client.get("/api/terminal/status").get_json()["available"])
        refused = self.client.post("/api/terminal/start", headers=self.headers, json={"access_code": "x"})
        self.assertEqual(refused.status_code, 403)
        self.assertEqual(self.client.post("/api/projects/deploy", headers=self.headers).status_code, 503)

    def test_network_changes_are_only_pretend(self):
        network = DemoNetwork("http://127.0.0.1:8080")
        network.change_hostname({"hostname": "robot-02"})
        network.activate_preferred()
        status = network.status()
        self.assertEqual(status["hostname"], "motionmodule")
        self.assertIn("Demo only", status["last_message"])
        self.assertTrue(network.scan())


class DemoServerTests(unittest.TestCase):
    def test_a_port_already_in_use_is_skipped(self):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as busy:
            busy.bind(("127.0.0.1", 0))
            busy.listen()
            self.assertFalse(port_is_free("127.0.0.1", busy.getsockname()[1]))


class DemoLauncherTests(unittest.TestCase):
    def test_launchers_run_the_demo_on_this_computer_only_by_default(self):
        for name in ("demo.ps1", "demo.sh"):
            with self.subTest(launcher=name):
                script = (ROOT / name).read_text(encoding="utf-8")
                self.assertIn("-m motion_module.demo", script)
                self.assertIn("127.0.0.1", script)
                self.assertIn("requirements.txt", script)

    def test_powershell_launcher_is_ascii_for_windows_powershell(self):
        # Windows PowerShell 5.1 reads a script without a byte-order mark in
        # the system code page, which garbles anything outside ASCII.
        self.assertTrue(all(byte < 128 for byte in (ROOT / "demo.ps1").read_bytes()))

    @unittest.skipUnless(shutil.which("bash"), "bash is required to check demo.sh")
    def test_shell_launcher_is_valid_bash(self):
        script = (ROOT / "demo.sh").read_text(encoding="utf-8").replace("\r\n", "\n")
        result = subprocess.run(
            [shutil.which("bash"), "-n"], input=script, capture_output=True, text=True, timeout=30, check=False
        )
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
