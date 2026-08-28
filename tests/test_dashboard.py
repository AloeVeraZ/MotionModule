import threading
import unittest
from unittest.mock import patch

from motion_module.config import load_config
from motion_module.dashboard import create_app
from motion_module.mecanum import MecanumDrive
from motion_module.servo import MockServoController, Servo


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
            "servo_boards": [{"index": 0, "address": "0x40", "available": True, "error": None}],
        }


class FakeNetwork:
    def __init__(self):
        self.hotspot_payload = None
        self.called = threading.Event()

    def status(self):
        return {
            "ok": True,
            "wifi": {"mode": "client", "ssid": "Workshop"},
            "addresses": [{"interface": "wlan0", "address": "192.0.2.10"}],
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


class DashboardTests(unittest.TestCase):
    def setUp(self):
        self.module = FakeModule()
        self.network = FakeNetwork()
        self.app = create_app(self.module, MecanumDrive(self.module), self.network)
        self.client = self.app.test_client()
        self.headers = {"X-MotionModule-Token": self.app.config["DASHBOARD_TOKEN"]}

    def test_all_dashboard_pages_are_served_by_versioned_runtime(self):
        for path in ("/", "/drive", "/hardware", "/diagnostics", "/network", "/code"):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            self.assertIn(b"MotionModule", response.data)

    def test_config_api_matches_driver_harness_and_complete_header(self):
        data = self.client.get("/api/config").get_json()
        self.assertEqual(len(data["header"]), 40)
        by_motor = {item["motor"]: item for item in data["motors"]}
        self.assertEqual((by_motor[1]["driver"], by_motor[1]["output"]), (2, "A"))
        self.assertEqual((by_motor[3]["driver"], by_motor[3]["output"]), (1, "A"))
        self.assertEqual(data["header"][39]["role"], "Driver 1 A IN2 · Motor 3")

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
        release = self.client.post(
            "/api/servos/release", headers=self.headers,
            json={"board": 0, "channel": 3},
        )
        self.assertEqual(release.status_code, 200)
        self.assertNotIn((0, 3), self.module._servos.angles)

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


if __name__ == "__main__":
    unittest.main()
