import time
import unittest
from dataclasses import replace
from unittest.mock import Mock, patch

from motion_module.config import default_config
from motion_module.controller import MotionModule
from motion_module.gpio import MockGPIO
from motion_module.errors import ConfigurationError
from motion_module.servo import MockServoController


class ControllerTests(unittest.TestCase):
    def test_default_pi_imu_uses_mpu6500_and_shares_reader(self):
        from motion_module.imu import IMUConfig

        self.gpio.is_hardware = True
        expected = IMUConfig()
        with patch("motion_module.pi_imu.find_i2c_gpio_bus", return_value=15), \
                patch("motion_module.pi_imu.LocalIMU") as reader:
            reader.return_value.declaration = expected
            imu = self.module.local_imu()
            reader.assert_called_once_with(expected, bus=15, auto_address=True)
            self.assertIs(self.module.local_imu(), imu)
            self.assertIs(self.module.local_imu(expected), imu)
            with self.assertRaises(ValueError):
                self.module.local_imu(IMUConfig(address=0x69))

    def test_reference_pi_reader_requires_imu_config(self):
        with self.assertRaisesRegex(TypeError, "IMUConfig"):
            self.module.local_imu("bno055")

    def setUp(self):
        self.config = default_config()
        self.gpio = MockGPIO()
        self.servos = MockServoController(self.config.servos)
        self.module = MotionModule(self.config, self.gpio, self.servos)

    def tearDown(self):
        self.module.close()

    def test_positive_drives_each_default_channel_with_its_shipped_polarity(self):
        self.module.set_motors({1: 0.5, 2: 0.5, 3: 0.5, 4: 0.5})
        # Output A ships inverted; output B does not. A robot-specific
        # hardware.py can change polarity without changing any pin.
        for pin in (19, 13, 20, 16):
            self.assertEqual(self.gpio.values[pin], 0.5)
        for pin in (26, 6, 21, 12):
            self.assertEqual(self.gpio.values[pin], 0)

    def test_inversion_swaps_which_gpio_a_positive_command_drives(self):
        for inverted, driven, idle in ((False, 26, 19), (True, 19, 26)):
            with self.subTest(inverted=inverted):
                self.module.close()
                config = replace(self.config, motors=(
                    replace(self.config.motors[0], inverted=inverted), *self.config.motors[1:]))
                self.gpio = MockGPIO()
                self.module = MotionModule(config, self.gpio, MockServoController(config.servos))
                self.module.set_motors({1: 0.5})
                self.assertEqual(self.gpio.values[driven], 0.5)
                self.assertEqual(self.gpio.values[idle], 0)

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
        motor = self.module.motor("driver_3a")
        motor.set(0.3)
        self.assertEqual(motor.name, "driver_3a")
        self.assertEqual(motor.channel, 5)
        # Spare output 3A retains its shipped inversion.
        self.assertEqual(self.gpio.values[9], 0.3)
        self.assertEqual(self.gpio.values[11], 0)
        servo = self.module.servo("servo_15")
        servo.set_angle(45)
        self.assertEqual((servo.board, servo.channel), (0, 15))
        self.assertEqual(self.servos.angles[(0, 15)], 45)

    def test_unused_pi_gpio_can_be_claimed_as_a_digital_sensor_input(self):
        sensor = self.module.digital_input(17, pull="up")
        self.assertIs(sensor.value, True)
        self.gpio.values[17] = 0
        self.assertIs(sensor.value, False)
        with self.assertRaisesRegex(ValueError, "used or reserved"):
            self.module.digital_input(26)
        # GPIO4 drives the servo board's OE pin, so it is not free either.
        with self.assertRaisesRegex(ValueError, "used or reserved"):
            self.module.digital_input(4)

    def test_output_enable_pin_is_held_low_so_the_servo_outputs_start_enabled(self):
        """OE is active low, and the board pulls it low anyway."""

        oe = self.module.config.servos.output_enable_gpio
        self.assertEqual(oe, 4)
        self.assertIn(oe, self.gpio.outputs)
        self.assertEqual(self.gpio.values[oe], 0.0)
        self.assertTrue(self.module.servo_outputs_enabled)

    def test_disabling_the_outputs_drives_oe_high_and_blocks_nothing_else(self):
        self.module.set_servo_outputs_enabled(False)
        self.assertEqual(self.gpio.values[4], 1.0)
        self.assertFalse(self.module.servo_outputs_enabled)
        # Motors are on their own pins and are unaffected by the servo OE line.
        self.module.motor(1).set(0.5)
        self.assertEqual(self.module.motor_values[1], 0.5)
        self.module.set_servo_outputs_enabled(True)
        self.assertEqual(self.gpio.values[4], 0.0)
        self.assertTrue(self.module.servo_outputs_enabled)

    def test_releasing_every_servo_leaves_the_output_enable_pin_alone(self):
        """The dashboard stops outputs on every page hide.

        Cutting OE there would leave the servos disabled after an ordinary
        navigation, so releasing and disabling stay separate actions.
        """

        self.module.servo("servo_0").set_angle(90)
        self.assertIn((0, 0), self.servos.angles)
        self.module.release_all_servos()
        self.assertNotIn((0, 0), self.servos.angles)
        self.assertEqual(self.gpio.values[4], 0.0)
        self.assertTrue(self.module.servo_outputs_enabled)

    def test_closing_the_module_cuts_the_outputs_before_it_talks_to_the_board(self):
        """Shutting down asserts OE first, so the outputs stop before the
        per-channel I2C writes rather than after them. The pin is freed a
        moment later and the board's own pull-down takes over."""

        module = MotionModule(config=self.module.config, gpio=MockGPIO())
        gpio = module.gpio
        module.close()
        writes = [index for index, (action, gpio_number, value)
                  in enumerate(gpio.events) if action == "write" and gpio_number == 4 and value == 1.0]
        closes = [index for index, (action, _, _) in enumerate(gpio.events) if action == "close"]
        self.assertTrue(writes, "OE was never driven high on close")
        self.assertLess(writes[-1], closes[0])

    def test_a_map_that_leaves_oe_unwired_cannot_pretend_to_disable_outputs(self):
        config = replace(
            self.module.config,
            servos=replace(self.module.config.servos, output_enable_gpio=None),
        )
        module = MotionModule(config=config, gpio=MockGPIO())
        try:
            self.assertTrue(module.servo_outputs_enabled)
            module.set_servo_outputs_enabled(True)   # already enabled, no-op
            with self.assertRaisesRegex(ConfigurationError, "output_enable_gpio"):
                module.set_servo_outputs_enabled(False)
        finally:
            module.close()

    def test_invalid_named_command_cannot_partially_move_motors(self):
        with self.assertRaisesRegex(ValueError, "No motor is named"):
            self.module.set_motors({"driver_3a": 0.3, "missing": 0.3})
        self.assertEqual(set(self.module.motor_values.values()), {0})

    def test_name_and_number_cannot_command_the_same_motor_twice(self):
        with self.assertRaisesRegex(ValueError, "specified more than once"):
            self.module.set_motors({"driver_3a": 0.3, 5: -0.3})
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

    def test_one_broken_motor_does_not_prevent_stopping_the_rest(self):
        self.module.set_motors({1: 0.4, 2: 0.4})
        with patch.object(self.module._motors[1], "set", side_effect=OSError("GPIO unavailable")):
            with self.assertRaises(ExceptionGroup):
                self.module.stop_all()
        self.assertEqual(self.module.motor_values[2], 0)
        self.assertEqual(self.module.motor_values[1], 0.4)
        self.assertTrue(self.module._watchdog_armed)
        self.module.stop_all()
        self.assertEqual(self.module.motor_values[1], 0)

    def test_watchdog_survives_a_transient_gpio_failure_and_retries(self):
        # Drive the loop synchronously after stopping its real worker.
        self.module._stop_event.set()
        self.module._watchdog_thread.join(timeout=1)
        self.module.set_motors({1: 0.4})
        self.module._last_feed = time.monotonic() - 10
        stop = self.module._stop_event = Mock()
        stop.wait.side_effect = [False, False, True]
        motor = self.module._motors[1]
        real_set = motor.set
        attempts = []

        def set_power(value):
            attempts.append(value)
            if len(attempts) == 1:
                raise OSError("temporary GPIO failure")
            real_set(value)

        with patch.object(motor, "set", side_effect=set_power), \
                self.assertLogs("motion_module.controller", level="ERROR"):
            self.module._watchdog_loop()
        self.assertEqual(attempts, [0, 0])
        self.assertEqual(self.module.motor_values[1], 0)
        self.assertFalse(self.module._watchdog_armed)
        self.assertTrue(self.module._watchdog_tripped)

    def test_shutdown_attempts_all_resources_even_after_hardware_errors(self):
        first = next(iter(self.module._motors.values()))
        giga = self.module._giga = Mock()
        imu = self.module._local_imu = Mock()
        giga.close.side_effect = OSError("USB disconnected")
        with patch.object(first, "set", side_effect=OSError("motor GPIO failed")), \
                patch.object(self.servos, "close", side_effect=OSError("I2C failed")):
            with self.assertRaises(ExceptionGroup) as raised:
                self.module.close()
        self.assertEqual(len(raised.exception.exceptions), 3)
        self.assertTrue(self.gpio.closed)
        self.assertFalse(self.module._watchdog_thread.is_alive())
        giga.close.assert_called_once_with()
        imu.close.assert_called_once_with()
        self.module.close()  # Idempotent even after a failed hardware close.

    def test_closed_module_cannot_start_a_usb_reader(self):
        self.module.close()
        with patch("motion_module.sensor_bridge.GigaR1Bridge") as bridge:
            with self.assertRaisesRegex(RuntimeError, "closed"):
                self.module.giga()
            bridge.assert_not_called()


if __name__ == "__main__":
    unittest.main()
