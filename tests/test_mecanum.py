import sys
import unittest
from pathlib import Path


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

if __name__ == "__main__":
    unittest.main()
