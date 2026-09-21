"""The Drive page's built-in Mecanum bench drive.

These lock the three mixing patterns the Drive page relies on, because two of
them look identical on a robot whose diagonal channels are crossed and only
the third one gives that away. See core/motion_module/mecanum.py.
"""

import unittest
from dataclasses import replace
from pathlib import Path

from motion_module.config import load_project_config
from motion_module.mecanum import MecanumTestDrive

EXAMPLE_DIR = Path(__file__).resolve().parents[1] / "examples" / "Mecanum"


class FakeModule:
    def __init__(self, config=None):
        self.config = config or load_project_config(EXAMPLE_DIR)
        self.outputs = {}

    def set_motors(self, outputs):
        self.outputs = dict(outputs)


class MecanumTestDriveTests(unittest.TestCase):
    def setUp(self):
        self.module = FakeModule()
        self.drive = MecanumTestDrive(self.module)

    def outputs(self, forward=0, strafe=0, rotate=0, speed=1.0):
        self.drive.drive(forward, strafe, rotate, speed)
        return [self.module.outputs[channel] for channel in (1, 2, 3, 4)]

    def test_forward_drives_all_four_wheels_the_same_way(self):
        self.assertEqual(self.outputs(forward=1), [1.0, 1.0, 1.0, 1.0])
        self.assertEqual(self.outputs(forward=-1), [-1.0, -1.0, -1.0, -1.0])

    def test_strafe_right_follows_the_x_roller_diagonals(self):
        front_left, rear_left, front_right, rear_right = self.outputs(strafe=1)
        # The wheels that share a diagonal share a sign.
        self.assertEqual(front_left, rear_right)
        self.assertEqual(front_right, rear_left)
        self.assertGreater(front_left, 0)
        self.assertLess(front_right, 0)

    def test_turning_in_place_opposes_the_left_side_to_the_right_side(self):
        # The regression this page exists to catch: if the front pair opposes
        # the rear pair instead, every axis cancels and the robot only twitches.
        front_left, rear_left, front_right, rear_right = self.outputs(rotate=1)
        self.assertEqual(front_left, rear_left)
        self.assertEqual(front_right, rear_right)
        self.assertEqual(front_left, -front_right)
        # Positive rotate is a left turn, so the left wheels run backward.
        self.assertLess(front_left, 0)

    def test_speed_limits_the_command_and_combinations_stay_in_range(self):
        self.assertEqual(self.outputs(forward=1, speed=0.4), [0.4] * 4)
        for value in self.outputs(forward=1, strafe=1, rotate=1, speed=1.0):
            self.assertLessEqual(abs(value), 1.0)

    def test_over_range_and_unusable_commands_are_refused_or_clamped(self):
        self.assertEqual(self.outputs(forward=5), [1.0, 1.0, 1.0, 1.0])
        for bad in (float("nan"), float("inf"), "1", True, None):
            with self.assertRaises(ValueError):
                self.drive.drive(bad, 0, 0)

    def test_stop_zeroes_the_four_drive_channels(self):
        self.outputs(forward=1)
        self.drive.stop()
        self.assertEqual(self.module.outputs, {1: 0.0, 2: 0.0, 3: 0.0, 4: 0.0})

    def test_a_different_pin_map_is_refused_rather_than_driven_blind(self):
        config = load_project_config(EXAMPLE_DIR)
        moved = replace(config.motor(1), forward_gpio=5)
        motors = [moved if motor.channel == 1 else motor for motor in config.motors]
        drive = MecanumTestDrive(FakeModule(replace(config, motors=motors)))
        with self.assertRaisesRegex(ValueError, "reference wiring"):
            drive.drive(1, 0, 0)


if __name__ == "__main__":
    unittest.main()
