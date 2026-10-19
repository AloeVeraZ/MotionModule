import importlib.util
import sys
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from motion_module.config import load_project_config
from motion_module.controller import MotionModule
from motion_module.gpio import MockGPIO

PROJECT_DIR = Path(__file__).resolve().parents[1] / "examples" / "Mecanum"
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

AUTONOMOUS_FILE = PROJECT_DIR.parent / "MecanumAutonomous" / "autonomous.py"
spec = importlib.util.spec_from_file_location("sample_autonomous_mecanum", AUTONOMOUS_FILE)
sample_autonomous = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sample_autonomous)
MecanumAutonomous = sample_autonomous.MecanumAutonomous
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
    def test_mecanum_inverts_only_the_two_rear_wheels(self):
        mecanum = load_project_config(PROJECT_DIR)
        self.assertEqual(
            [motor.inverted for motor in mecanum.motors[:4]],
            [False, True, False, True],
        )

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
        """Use the owner's confirmed Q calibration from Debug's Mecanum Test."""

        self.assertEqual(
            mix(0, 0, 1),
            {"front_left": 1, "rear_left": -1, "front_right": 1, "rear_right": -1},
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
                "rear_left": -0.5,
                "front_right": 0.5,
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

    def test_sample_names_reach_the_wheel_pins_in_the_shipped_map(self):
        config = load_project_config(PROJECT_DIR)
        gpio = MockGPIO()
        with MotionModule(config, gpio=gpio) as module:
            drive = MecanumDrive(module)
            drive.drive(1, 0, 0, speed=0.25)
            # Match the measured baseline: only the rear wheels reverse.
            for gpio_number in (26, 6, 21, 12):
                self.assertEqual(gpio.values[gpio_number], 0.25)
            for gpio_number in (19, 13, 20, 16):
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
        # Simulate the robot's confirmed rotation response, not the old
        # theoretical wheel labels. Translation cancels out of this sum.
        turn = (outputs["front_left"] - outputs["rear_left"]
                + outputs["front_right"] - outputs["rear_right"]) / 2
        self.sensors.value += turn * 20


class MecanumSensorTests(unittest.TestCase):
    def test_create_drive_uses_the_builtin_imu_without_a_sensor_file(self):
        config = load_project_config(PROJECT_DIR)
        with MotionModule(config, gpio=MockGPIO()) as module:
            drive = create_drive(module)
            self.assertIs(drive.sensors, module.imu)
            self.assertFalse((PROJECT_DIR / "sensors.py").exists())
            self.assertIsNone(module._giga)
            self.assertIsNone(drive.sensors.heading())
            self.assertFalse(drive.sensors.reading().connected)
            names = [control["name"] for control in drive.controls()]
            self.assertEqual(names, [])
            # Without an IMU there is nothing to zero or snap by: say so.
            with self.assertRaisesRegex(ValueError, "not ready"):
                drive.control("zero_heading", 1)
            with self.assertRaisesRegex(ValueError, "IMU"):
                drive.control("turn_left_90", 1)

    def test_drive_uses_runtime_readings_and_zero_control(self):
        config = load_project_config(PROJECT_DIR)
        with MotionModule(config, gpio=MockGPIO()) as module:
            from unittest.mock import Mock
            imu = module._local_imu = Mock()
            imu.heading.return_value = 42.0
            with patch("motion_module.pi_imu.LocalIMU") as reader:
                drive = create_drive(module)
                reader.assert_not_called()
                self.assertEqual(drive.sensors.heading(), 42.0)
                self.assertIs(module.imu, drive.sensors)
                drive.control("zero_heading", 1)
                imu.zero.assert_called_once_with(level=True)
                module.close()
                imu.close.assert_called_once_with()
                with self.assertRaises(RuntimeError):
                    module.local_imu()

    def test_default_auto_supports_legacy_teleop_and_builtin_motor_names(self):
        from types import SimpleNamespace
        create_autonomous = sample_autonomous.create_autonomous
        from motion_module.config import default_config
        from motion_module.mecanum import mix as channel_mix
        with MotionModule(default_config(), gpio=MockGPIO()) as module:
            sensors = SimpleNamespace(heading=lambda: 0, rate=lambda: 0)
            module._local_imu = sensors
            routine = create_autonomous(module, SimpleNamespace())
            # The fixture is not a worker and owns no resources.
            module._owns_imu = False
            self.assertIs(routine.sensors, sensors)
            self.assertFalse(any(module.snapshot()['motors'].values()))
            result = routine.move(0, 0, 0.3, speed=1)
            self.assertEqual(result['outputs'], channel_mix(0, 0, 0.3))
            routine.drive.stop()
            self.assertFalse(any(module.snapshot()['motors'].values()))

    def test_autonomous_turns_left_to_ninety_degrees_by_the_imu(self):
        sensors = FakeHeadingSensors()
        module = TurningModule(sensors)
        drive = MecanumDrive(module, sensors=sensors)
        routine = MecanumAutonomous(module, drive)
        self.assertTrue(routine.turn_to(90, threading.Event()))
        self.assertAlmostEqual(sensors.value, 90, delta=routine.heading.tolerance + 1)
        self.assertEqual(set(module.outputs.values()), {0})

    def test_autonomous_waits_without_moving_until_builtin_imu_is_ready(self):
        from unittest.mock import Mock
        module = FakeModule()
        drive = Mock(sensors=FakeHeadingSensors())
        routine = MecanumAutonomous(module, drive)
        stop = Mock()
        stop.is_set.return_value = False
        with patch.object(routine, "ready", side_effect=[False, True]), \
                patch.object(sample_autonomous, "PLAN", []):
            routine.run(stop)
        stop.wait.assert_called_once_with(routine.LOOP_SECONDS)
        drive.move.assert_not_called()

    def test_unavailable_imu_and_disable_during_calibration_never_move(self):
        with MotionModule(load_project_config(PROJECT_DIR), gpio=MockGPIO()) as module:
            routine = sample_autonomous.create_autonomous(module, object())
            routine.IMU_READY_TIMEOUT = 0
            with self.assertRaisesRegex(RuntimeError, "autonomous stayed stopped"):
                routine.run(threading.Event())
            stop = threading.Event()
            stop.set()
            routine.run(stop)
            self.assertFalse(any(module.motor_values.values()))

    def test_autonomous_turn_takes_the_short_way_round(self):
        sensors = FakeHeadingSensors()
        sensors.value = 170.0
        module = TurningModule(sensors)
        # This instantaneous, frictionless fixture needs no breakaway power.
        # The dynamic heading tests exercise the real minimum-power setting.
        from motion_module.heading import HeadingController
        drive = MecanumDrive(module, sensors=sensors, heading=HeadingController(min_turn_power=0))
        routine = MecanumAutonomous(module, drive)
        routine.turn_to(-170, threading.Event())
        # Turning left 20 degrees from 170 lands on -170 after passing 180.
        self.assertGreater(sensors.value, 180)
        self.assertAlmostEqual(sensors.value, 190, delta=2)
        self.assertEqual(set(module.outputs.values()), {0})

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
