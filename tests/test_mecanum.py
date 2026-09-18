import sys
import threading
import time
import unittest
from pathlib import Path

from motion_module.config import load_project_config
from motion_module.controller import MotionModule
from motion_module.gpio import MockGPIO

PROJECT_DIR = Path(__file__).resolve().parents[1] / "examples" / "Mecanum"
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from autonomous import MecanumAutonomous  # noqa: E402
from robot import MecanumDrive, create_drive, mix  # noqa: E402


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

    def test_positive_rotation_turns_left(self):
        """Counter-clockwise, like Q and an IMU heading: left side back, right side forward."""

        self.assertEqual(
            mix(0, 0, 1),
            {"front_left": -1, "rear_left": -1, "front_right": 1, "rear_right": 1},
        )

    def test_combined_commands_normalize(self):
        result = mix(1, 1, 1)
        self.assertLessEqual(max(abs(value) for value in result.values()), 1)

    def test_drive_commands_each_wheel_by_its_hardware_name(self):
        module = FakeModule()
        drive = MecanumDrive(module)
        drive.drive(0, 0, 1, speed=0.5)
        self.assertEqual(
            module.outputs,
            {
                "front_left": -0.5,
                "rear_left": -0.5,
                "front_right": 0.5,
                "rear_right": 0.5,
            },
        )

    def test_stop_zeroes_every_wheel(self):
        module = FakeModule()
        MecanumDrive(module).stop()
        self.assertEqual(set(module.outputs.values()), {0})

    def test_drive_rejects_values_that_are_not_finite_numbers(self):
        drive = MecanumDrive(FakeModule())
        for bad in (float("inf"), float("nan"), "0.5", True):
            with self.assertRaises(ValueError):
                drive.drive(bad, 0, 0)

    def test_custom_wheel_names_keep_the_same_mixing_order(self):
        module = FakeModule()
        drive = MecanumDrive(module, wheels=("left_front", "left_back", "right_front", "right_back"))
        drive.drive(0, 1, 0, speed=0.25)
        self.assertEqual(module.outputs, {
            "left_front": 0.25, "left_back": -0.25,
            "right_front": -0.25, "right_back": 0.25,
        })

    def test_sample_names_reach_the_wheel_pins_in_the_shipped_map(self):
        config = load_project_config(PROJECT_DIR)
        gpio = MockGPIO()
        with MotionModule(config, gpio=gpio) as module:
            drive = MecanumDrive(module)
            drive.drive(1, 0, 0, speed=0.25)
            # The front wheels are inverted, so forward runs them on their
            # reverse wires and the rear wheels on their forward wires.
            for gpio_number in (19, 13, 20, 16):
                self.assertEqual(gpio.values[gpio_number], 0.25)
            for gpio_number in (26, 6, 21, 12):
                self.assertEqual(gpio.values[gpio_number], 0)
            drive.stop()
            self.assertEqual(set(gpio.values.values()), {0})


class FakeHeadingSensors:
    """An IMU on a robot that turns as fast as it is told to."""

    def __init__(self):
        self.value = 0.0
        self.zeroed = False
        self.imus = []

    def heading(self):
        return self.value

    def zero_heading(self):
        self.value = 0.0
        self.zeroed = True


class TurningModule(FakeModule):
    def __init__(self, sensors):
        super().__init__()
        self.sensors = sensors

    def set_motors(self, outputs):
        super().set_motors(outputs)
        # Right wheels forward and left wheels back turn the robot left,
        # which a heading counts up.
        left = (outputs["front_left"] + outputs["rear_left"]) / 2
        right = (outputs["front_right"] + outputs["rear_right"]) / 2
        self.sensors.value += (right - left) * 20


class MecanumSensorTests(unittest.TestCase):
    def test_create_drive_brings_the_sensors_from_sensors_py(self):
        import sensors

        config = load_project_config(PROJECT_DIR)
        with MotionModule(config, gpio=MockGPIO()) as module:
            drive = create_drive(module)
            # One GIGA for the whole robot: sensors.py's declarations, simulated here.
            self.assertIs(drive.sensors.giga, module.giga(pins=sensors.PINS, imus=sensors.IMUS))
            self.assertTrue(drive.sensors.giga.simulated)
            self.assertIsNone(drive.sensors.heading())
            self.assertIsNone(drive.sensors.arm_position())
            self.assertIsNone(drive.sensors.intake_blocked())
            names = [control["name"] for control in drive.controls()]
            self.assertIn("zero_heading", names)
            self.assertIn("calibrate_gyro", names)
            self.assertEqual(drive.control("zero_heading", 1), {"heading": None})

    def test_sensors_file_declares_both_recommended_imus(self):
        import sensors

        self.assertEqual([imu.chip for imu in sensors.IMUS], ["bno055", "ism330dhcx"])
        self.assertEqual([imu.address for imu in sensors.IMUS], [0x28, 0x6A])
        self.assertEqual([imu.driver for imu in sensors.IMUS], ["BNO055", "LSM6"])

    def test_autonomous_turns_left_to_ninety_degrees_by_the_imu(self):
        sensors = FakeHeadingSensors()
        module = TurningModule(sensors)
        drive = MecanumDrive(module, sensors=sensors)
        routine = MecanumAutonomous(module, drive)
        self.assertTrue(routine.turn_to(90, threading.Event(), timeout=5))
        self.assertAlmostEqual(sensors.value, 90, delta=routine.TURN_TOLERANCE_DEGREES + 1)
        self.assertEqual(set(module.outputs.values()), {0})

    def test_autonomous_turn_takes_the_short_way_round(self):
        sensors = FakeHeadingSensors()
        sensors.value = 170.0
        module = TurningModule(sensors)
        drive = MecanumDrive(module, sensors=sensors)
        routine = MecanumAutonomous(module, drive)
        routine.turn_to(-170, threading.Event(), timeout=5)
        # Turning left 20 degrees from 170 lands on -170 after passing 180.
        self.assertGreater(sensors.value, 180)

    def test_autonomous_turn_stops_when_disabled(self):
        sensors = FakeHeadingSensors()
        routine = MecanumAutonomous(TurningModule(sensors), MecanumDrive(TurningModule(sensors), sensors=sensors))
        stop = threading.Event()
        stop.set()
        started = time.monotonic()
        self.assertFalse(routine.turn_to(90, stop))
        self.assertLess(time.monotonic() - started, 0.5)


if __name__ == "__main__":
    unittest.main()
