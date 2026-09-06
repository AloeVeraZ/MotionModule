import sys
import unittest
from pathlib import Path

from motion_module.config import load_project_config
from motion_module.controller import MotionModule
from motion_module.gpio import MockGPIO

PROJECT_DIR = Path(__file__).resolve().parents[1] / "examples" / "Mecanum"
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from robot import MecanumDrive, mix  # noqa: E402


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

    def test_rotation_commands_left_opposite_right(self):
        self.assertEqual(
            mix(0, 0, 1),
            {"front_left": 1, "rear_left": 1, "front_right": -1, "rear_right": -1},
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
                "front_left": 0.5,
                "rear_left": 0.5,
                "front_right": -0.5,
                "rear_right": -0.5,
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

    def test_sample_names_preserve_the_tested_motor_pin_behavior(self):
        config = load_project_config(PROJECT_DIR)
        gpio = MockGPIO()
        with MotionModule(config, gpio=gpio) as module:
            drive = MecanumDrive(module)
            drive.drive(1, 0, 0, speed=0.25)
            for gpio_number in (6, 16, 21, 13):
                self.assertEqual(gpio.values[gpio_number], 0.25)
            for gpio_number in (12, 19, 20, 26):
                self.assertEqual(gpio.values[gpio_number], 0)
            drive.stop()
            self.assertEqual(set(gpio.values.values()), {0})

if __name__ == "__main__":
    unittest.main()
