import time
import unittest
from dataclasses import replace
from unittest.mock import patch

from motion_module.config import load_config
from motion_module.controller import MotionModule
from motion_module.gpio import MockGPIO
from motion_module.servo import MockServoController


class ControllerTests(unittest.TestCase):
    def setUp(self):
        self.config = load_config()
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


if __name__ == "__main__":
    unittest.main()

