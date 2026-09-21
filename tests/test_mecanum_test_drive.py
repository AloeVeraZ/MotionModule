"""The Drive page's built-in Mecanum bench drive.

Lock the working translations and the test-only rotation correction separately.
Software assertions are not a substitute for the owner's physical turn check.
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

    def test_translation_panels_of_the_gobilda_mecanum_reference_are_unchanged(self):
        """goBILDA's arrow chart, one row per panel: 1 up, -1 down, 0 stopped.

        Forward is the row a working robot already proves; every other row is
        that same value with some wheels' signs flipped.
        """

        up, down, off = 1, -1, 0
        panels = {
            #                      forward strafe rotate      FL    RL    FR    RR
            "forward":           ((     1,     0,     0), (   up,   up,   up,   up)),
            "backward":          ((    -1,     0,     0), ( down, down, down, down)),
            "strafe right":      ((     0,     1,     0), (   up, down, down,   up)),
            "strafe left":       ((     0,    -1,     0), ( down,   up,   up, down)),
            "diagonal up-left":  ((     1,    -1,     0), (  off,   up,   up,  off)),
            "diagonal up-right": ((     1,     1,     0), (   up,  off,  off,   up)),
            "diagonal down-left":((    -1,    -1,     0), ( down,  off,  off, down)),
            "diagonal down-right":((   -1,     1,     0), (  off, down, down,  off)),
        }
        for panel, (command, expected) in panels.items():
            with self.subTest(panel=panel):
                measured = self.outputs(*command)
                # Only the direction is under test; the magnitude is the
                # speed limit, and a diagonal's two driven wheels are scaled
                # back down into range together.
                signs = tuple(0 if value == 0 else (1 if value > 0 else -1) for value in measured)
                self.assertEqual(signs, expected)

    def test_rotation_only_reverses_channels_1_and_4_from_the_previous_test(self):
        # The physical turn is to be confirmed by the owner. These assertions
        # lock the requested electrical correction, not a measured motion.
        self.assertEqual(self.outputs(rotate=1), [1, -1, 1, -1])
        self.assertEqual(self.outputs(rotate=-1), [-1, 1, -1, 1])

    def test_all_translation_combinations_are_identical_to_the_previous_mixer(self):
        for forward in (-1, -0.3, 0, 0.6, 1):
            for strafe in (-1, -0.3, 0, 0.6, 1):
                before = [forward + strafe, forward - strafe, forward - strafe, forward + strafe]
                scale = max(1, *(abs(power) for power in before))
                self.assertEqual(self.outputs(forward, strafe), [power / scale for power in before])

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
