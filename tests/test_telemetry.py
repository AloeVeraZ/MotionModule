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


if __name__ == "__main__":
    unittest.main()
