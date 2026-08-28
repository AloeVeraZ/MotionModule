import importlib.util
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import patch


PROJECT_DIR = Path(__file__).resolve().parents[1] / "Mecanum"
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from mecanum import MecanumDrive, mix  # noqa: E402


class FakeModule:
    def __init__(self):
        self.outputs = None
        self.stopped = False

    def set_motors(self, outputs):
        self.outputs = outputs

    def stop_all(self):
        self.stopped = True

    def snapshot(self):
        return {"motors": self.outputs or {}, "watchdog_tripped": False}


class FakeNetwork:
    def __init__(self):
        self.hotspot_payload = None
        self.called = threading.Event()

    def status(self):
        return {
            "ok": True,
            "wifi": {"mode": "client", "ssid": "Workshop"},
            "addresses": [{"interface": "wlan0", "address": "192.0.2.10"}],
            "local_url": "http://motionmodule.local:8080",
        }

    def scan(self):
        return [{"ssid": "Workshop", "signal": 80, "security_kind": "personal"}]

    def start_hotspot(self, payload):
        self.hotspot_payload = payload
        self.called.set()

    def connect(self, payload):
        self.called.set()

    def activate_preferred(self):
        self.called.set()


class MecanumTests(unittest.TestCase):
    def test_forward_commands_all_wheels_together(self):
        self.assertEqual(
            mix(1, 0, 0),
            {"front_left": 1, "rear_left": 1, "front_right": 1, "rear_right": 1},
        )

    def test_strafe_uses_opposite_diagonals(self):
        self.assertEqual(
            mix(0, 1, 0),
            {"front_left": 1, "rear_left": -1, "front_right": -1, "rear_right": 1},
        )

    def test_rotation_commands_left_opposite_right(self):
        self.assertEqual(
            mix(0, 0, 1),
            {"front_left": 1, "rear_left": 1, "front_right": -1, "rear_right": -1},
        )

    def test_combined_commands_normalize(self):
        result = mix(1, 1, 1)
        self.assertLessEqual(max(abs(value) for value in result.values()), 1)

    def test_drive_maps_wheels_to_first_four_channels(self):
        module = FakeModule()
        drive = MecanumDrive(module)
        drive.drive(0, 0, 1, speed=0.5)
        self.assertEqual(module.outputs, {1: 0.5, 2: 0.5, 3: -0.5, 4: -0.5})

    @unittest.skipUnless(importlib.util.find_spec("flask"), "Flask is installed by the Pi installer")
    def test_browser_api_uses_correct_rotation_and_rejects_stale_packets(self):
        from robot import create_app

        module = FakeModule()
        client = create_app(module).test_client()
        response = client.post(
            "/api/drive",
            json={"sequence": 3, "forward": 0, "strafe": 0, "rotate": 1, "speed": 0.4},
        )
        self.assertEqual(response.status_code, 200)
        self.assertEqual(module.outputs, {1: 0.4, 2: 0.4, 3: -0.4, 4: -0.4})

        stale = client.post(
            "/api/drive",
            json={"sequence": 2, "forward": 1, "strafe": 0, "rotate": 0, "speed": 1},
        )
        self.assertEqual(stale.get_json()["ignored"], "stale sequence")
        self.assertEqual(module.outputs, {1: 0.4, 2: 0.4, 3: -0.4, 4: -0.4})

    @unittest.skipUnless(importlib.util.find_spec("flask"), "Flask is installed by the Pi installer")
    def test_network_api_requires_page_token_and_stops_before_hotspot_switch(self):
        from robot import create_app

        module = FakeModule()
        network = FakeNetwork()
        app = create_app(module, network_client=network)
        client = app.test_client()

        page = client.get("/")
        self.assertEqual(page.status_code, 200)
        self.assertIn(b"Network settings", page.data)
        self.assertEqual(client.get("/api/network/status").get_json()["wifi"]["ssid"], "Workshop")
        denied = client.post(
            "/api/network/hotspot",
            json={"ssid": "Robot", "password": "safe-pass"},
        )
        self.assertEqual(denied.status_code, 403)

        with patch("robot.time.sleep", return_value=None):
            accepted = client.post(
                "/api/network/hotspot",
                headers={"X-MotionModule-Token": app.config["NETWORK_CSRF_TOKEN"]},
                json={"ssid": "Robot", "password": ""},
            )
            self.assertEqual(accepted.status_code, 202)
            self.assertTrue(network.called.wait(1))

        self.assertTrue(module.stopped)
        self.assertEqual(network.hotspot_payload, {"ssid": "Robot"})


if __name__ == "__main__":
    unittest.main()
