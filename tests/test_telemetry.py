import math
import unittest

from motion_module.telemetry import (
    DEFAULT_GAMEPAD_STICKS,
    DEFAULT_TOUCH_STICKS,
    CameraFeed,
    IMUReading,
    MAX_CAMERAS,
    MAX_SENSORS,
    SensorReading,
    TOUCH_PANELS,
    TelemetryDashboard,
    empty_snapshot,
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

    def test_a_dashboard_keeping_the_robot_s_sensors_in_self_sensors_still_snapshots(self):
        """The Mecanum sample stores drive.sensors as self.sensors, which hides
        the legacy sensors() method; that must not break the whole console."""

        class RobotSensors:
            pass

        for held in (RobotSensors(), None):
            class RobotDashboard(TelemetryDashboard):
                def __init__(self):
                    self.sensors = held

                def cameras(self):
                    return [CameraFeed("Front", "/camera/front")]

            with self.subTest(held=held):
                payload = normalize_snapshot(RobotDashboard().snapshot())
                self.assertEqual(payload["pi_inputs"], [])
                self.assertEqual(payload["cameras"][0]["name"], "Front")

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

    def test_sticks_default_to_a_drive_stick_and_a_turning_stick(self):
        for payload in (normalize_snapshot(TelemetryDashboard().snapshot()), empty_snapshot(),
                        normalize_snapshot({"cameras": []})):
            with self.subTest(payload=payload):
                self.assertEqual(payload["gamepad_sticks"], DEFAULT_GAMEPAD_STICKS)
                self.assertEqual(payload["touch_sticks"], DEFAULT_TOUCH_STICKS)
                self.assertEqual(payload["touch_panels"], [])
        self.assertEqual(
            {key: DEFAULT_TOUCH_STICKS[key] for key in ("forward", "strafe", "rotate")},
            {"forward": "left_y", "strafe": "left_x", "rotate": "right_x"},
        )

    def test_a_project_moves_only_the_stick_axes_it_names(self):
        class RobotDashboard(TelemetryDashboard):
            def gamepad_sticks(self):
                return {"forward": "-Right_Y", "deadzone": 0.2, "curve": 2}

            def touch_sticks(self):
                return {"strafe": None, "rotate": "buttons"}

        payload = normalize_snapshot(RobotDashboard().snapshot())
        self.assertEqual(payload["gamepad_sticks"], {
            "forward": "-right_y", "strafe": "left_x", "rotate": "right_x",
            "deadzone": 0.2, "curve": 2.0,
        })
        self.assertEqual(payload["touch_sticks"], {
            "forward": "left_y", "strafe": None, "rotate": "buttons",
            "deadzone": 0.1, "curve": 1.0,
        })

    def test_one_stick_axis_never_moves_the_robot_two_ways(self):
        class RobotDashboard(TelemetryDashboard):
            def gamepad_sticks(self):
                # Turning takes the left stick's X, which strafing had.
                return {"rotate": "left_x"}

            def touch_sticks(self):
                return {"forward": "right_x", "strafe": "-right_x"}

        payload = normalize_snapshot(RobotDashboard().snapshot())
        self.assertEqual(payload["gamepad_sticks"]["rotate"], "left_x")
        self.assertIsNone(payload["gamepad_sticks"]["strafe"])
        self.assertEqual(payload["gamepad_sticks"]["forward"], "left_y")
        touch = payload["touch_sticks"]
        self.assertEqual(touch["forward"], "right_x")
        self.assertEqual(touch["strafe"], "left_x")   # its second claim fell back to the default
        self.assertIsNone(touch["rotate"])            # whose own default was already taken

    def test_stick_values_that_make_no_sense_fall_back_or_are_held_in_range(self):
        class RobotDashboard(TelemetryDashboard):
            def gamepad_sticks(self):
                return {"forward": "up", "strafe": 3, "rotate": "buttons", "deadzone": 0.9, "curve": 0}

            def touch_sticks(self):
                return {"forward": "off", "strafe": False, "deadzone": True, "curve": "steep"}

        payload = normalize_snapshot(RobotDashboard().snapshot())
        pad = payload["gamepad_sticks"]
        self.assertEqual((pad["forward"], pad["strafe"]), ("left_y", "left_x"))
        self.assertEqual(pad["rotate"], "right_x", "Only the on-screen sticks have Turn buttons")
        self.assertEqual((pad["deadzone"], pad["curve"]), (0.5, 1.0))
        touch = payload["touch_sticks"]
        self.assertEqual((touch["forward"], touch["strafe"], touch["rotate"]), (None, None, "right_x"))
        self.assertEqual((touch["deadzone"], touch["curve"]), (0.1, 1.0))

    def test_a_touchscreen_adds_only_the_panels_it_knows(self):
        class RobotDashboard(TelemetryDashboard):
            def touch_panels(self):
                return ["usb_controllers", "IMU", "imu", "weather", 7]

        self.assertEqual(normalize_snapshot(RobotDashboard().snapshot())["touch_panels"],
                         ["imu", "usb_controllers"])
        self.assertEqual(normalize_snapshot({"touch_panels": "status"})["touch_panels"], ["status"])
        self.assertEqual(normalize_snapshot({"touch_panels": {"imu": True}})["touch_panels"], [])
        self.assertEqual(TOUCH_PANELS, ("status", "mechanisms", "imu", "pi_inputs", "usb_controllers"))


if __name__ == "__main__":
    unittest.main()
