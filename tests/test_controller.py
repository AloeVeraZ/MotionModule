import time
import unittest
from dataclasses import replace
from unittest.mock import patch

from motion_module.config import default_config
from motion_module.controller import MotionModule
from motion_module.gpio import MockGPIO
from motion_module.servo import MockServoController


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.config = default_config()
        self.gpio = MockGPIO()
        self.servos = MockServoController(self.config.servos)
        self.module = MotionModule(self.config, self.gpio, self.servos)

    def tearDown(self):
        self.module.close()

    def test_positive_first_four_channels_respect_installed_inversion(self):
        self.module.set_motors({1: 0.5, 2: 0.5, 3: 0.5, 4: 0.5})
        for pin in (6, 16, 21, 13):
            self.assertEqual(self.gpio.values[pin], 0.5)
        for pin in (12, 19, 20, 26):
            self.assertEqual(self.gpio.values[pin], 0)

    def test_full_direction_change_uses_one_shared_deadtime(self):
        self.module.set_motors({channel: 0.4 for channel in range(1, 5)})
        with patch("motion_module.controller.time.sleep") as sleep:
            self.module.set_motors({channel: -0.4 for channel in range(1, 5)})
        sleep.assert_called_once_with(0.015)

    def test_watchdog_stops_stale_outputs(self):
        self.module.close()
        quick_config = replace(self.config, watchdog_ms=50)
        self.gpio = MockGPIO()
        self.servos = MockServoController(quick_config.servos)
        self.module = MotionModule(quick_config, self.gpio, self.servos)
        self.module.motor(5).set(0.25)
        time.sleep(0.12)
        self.assertEqual(self.module.motor(5).value, 0)
        self.assertTrue(self.module.snapshot()["watchdog_tripped"])

    def test_servo_api_supports_board_and_channel(self):
        servo = self.module.servo(15, board=0)
        servo.set_angle(90)
        self.assertEqual(servo.angle, 90)
        servo.release()
        self.assertIsNone(servo.angle)

    def test_named_outputs_operate_the_expected_motor_and_servo(self):
        motor = self.module.motor("motor_5")
        motor.set(0.3)
        self.assertEqual(motor.name, "motor_5")
        self.assertEqual(motor.channel, 5)
        self.assertEqual(self.gpio.values[5], 0.3)
        self.assertEqual(self.gpio.values[25], 0)
        servo = self.module.servo("servo_16")
        servo.set_angle(45)
        self.assertEqual((servo.board, servo.channel), (0, 15))
        self.assertEqual(self.servos.angles[(0, 15)], 45)

    def test_invalid_named_command_cannot_partially_move_motors(self):
        with self.assertRaisesRegex(ValueError, "No motor is named"):
            self.module.set_motors({"motor_5": 0.3, "missing": 0.3})
        self.assertEqual(set(self.module.motor_values.values()), {0})

    def test_name_and_number_cannot_command_the_same_motor_twice(self):
        with self.assertRaisesRegex(ValueError, "specified more than once"):
            self.module.set_motors({"motor_5": 0.3, 5: -0.3})
        self.assertEqual(set(self.module.motor_values.values()), {0})

    def test_servo_reference_errors_are_clear_before_writing_outputs(self):
        for channel, board in (("missing", 0), (0, True), (0, 0.5), (0, "0"), (16, 0), (0, 1)):
            with self.subTest(channel=channel, board=board), self.assertRaises(ValueError):
                self.module.servo(channel, board)
        self.assertEqual(self.servos.pulses, {})

    def test_stop_all_is_safe_after_the_module_is_closed(self):
        self.module.close()
        self.module.stop_all()
        self.assertTrue(self.gpio.closed)


if __name__ == "__main__":
    unittest.main()
