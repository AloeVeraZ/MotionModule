import math
import unittest

from motion_module.telemetry import (
    CameraFeed,
    IMUReading,
    MAX_CAMERAS,
    MAX_SENSORS,
    SensorReading,
    TelemetryDashboard,
    normalize_snapshot,
)


class TelemetryTests(unittest.TestCase):
    def test_normalizer_caps_camera_and_sensor_counts(self):
        payload = normalize_snapshot({
            "cameras": [CameraFeed(f"Camera {index}", f"/camera/{index}") for index in range(5)],
            "sensors": [SensorReading(f"Sensor {index}", index) for index in range(30)],
        })
        self.assertEqual(len(payload["cameras"]), MAX_CAMERAS)
        self.assertEqual(len(payload["sensors"]), MAX_SENSORS)

    def test_analog_and_digital_inputs_are_json_safe(self):
        payload = normalize_snapshot({
            "imu": IMUReading(yaw=361.5, pitch=-3, roll=2.25, rate=9),
            "sensors": [
                SensorReading("Range", 275.5, unit="mm", channel="ADC 0", minimum=0, maximum=1000),
                SensorReading("Beam", "high", kind="digital", channel="DIO 2"),
                SensorReading("Mode", "intaking", kind="text"),
            ],
        })
        self.assertEqual(payload["imu"]["yaw"], 361.5)
        self.assertEqual(payload["sensors"][0]["value"], 275.5)
        self.assertIs(payload["sensors"][1]["value"], True)
        self.assertEqual(payload["sensors"][2]["value"], "intaking")

    def test_bad_values_and_camera_urls_fail_closed(self):
        payload = normalize_snapshot({
            "cameras": [CameraFeed("Unsafe", "javascript:alert(1)")],
            "imu": IMUReading(yaw=math.inf),
            "sensors": [
                SensorReading("Bad analog", math.nan),
                SensorReading("Missing switch", None, kind="digital", connected=False),
            ],
        })
        self.assertEqual(payload["cameras"][0]["url"], "")
        self.assertFalse(payload["cameras"][0]["connected"])
        self.assertIsNone(payload["imu"]["yaw"])
        self.assertIsNone(payload["sensors"][0]["value"])
        self.assertEqual(payload["sensors"][1]["status"], "offline")

    def test_base_dashboard_reads_overridden_groups_on_every_snapshot(self):
        class RobotDashboard(TelemetryDashboard):
            def sensors(self):
                return [SensorReading("Limit", False, kind="digital")]

        payload = normalize_snapshot(RobotDashboard().snapshot())
        self.assertEqual(payload["sensors"][0]["kind"], "digital")
        self.assertIs(payload["sensors"][0]["value"], False)

    def test_driver_bindings_default_to_wasd_and_space(self):
        payload = normalize_snapshot(TelemetryDashboard().snapshot())
        self.assertEqual(payload["driver_bindings"], {
            "forward": "w", "back": "s", "left": "a", "right": "d",
            "turn_left": "q", "turn_right": "e", "stop": " ",
        })

    def test_a_project_moves_only_the_keys_it_names(self):
        class RobotDashboard(TelemetryDashboard):
            def driver_bindings(self):
                return {"turn_left": "Z", "turn_right": "c", "stop": "Escape"}

        bindings = normalize_snapshot(RobotDashboard().snapshot())["driver_bindings"]
        self.assertEqual(bindings["turn_left"], "z")     # single keys are case-free
        self.assertEqual(bindings["turn_right"], "c")
        self.assertEqual(bindings["stop"], "Escape")     # named keys pass through
        self.assertEqual(bindings["forward"], "w")       # untouched actions keep defaults

    def test_one_key_never_ends_up_meaning_two_things(self):
        """A project that takes another action's default leaves it unassigned
        rather than making one keypress do two jobs."""

        class RobotDashboard(TelemetryDashboard):
            def driver_bindings(self):
                return {"forward": "s"}

        bindings = normalize_snapshot(RobotDashboard().snapshot())["driver_bindings"]
        self.assertEqual(bindings["forward"], "s")
        self.assertNotIn("back", bindings)
        self.assertEqual(len(set(bindings.values())), len(bindings))

    def test_values_the_browser_could_never_send_fall_back_to_the_default(self):
        class RobotDashboard(TelemetryDashboard):
            def driver_bindings(self):
                return {"forward": 12, "back": "", "left": ["a"], "right": "ArrowRight"}

        bindings = normalize_snapshot(RobotDashboard().snapshot())["driver_bindings"]
        self.assertEqual(bindings["forward"], "w")
        self.assertEqual(bindings["back"], "s")
        self.assertEqual(bindings["left"], "a")
        self.assertEqual(bindings["right"], "ArrowRight")


if __name__ == "__main__":
    unittest.main()
