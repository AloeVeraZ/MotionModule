import unittest

from motion_module.config import load_config
from motion_module.pinout import motor_rows


class DefaultConfigTests(unittest.TestCase):
    def test_default_has_eight_unique_motor_channels(self):
        config = load_config()
        self.assertEqual([motor.channel for motor in config.motors], list(range(1, 9)))
        pins = [
            gpio
            for motor in config.motors
            for gpio in (motor.forward_gpio, motor.reverse_gpio)
        ]
        self.assertEqual(len(pins), 16)
        self.assertEqual(len(set(pins)), 16)

    def test_existing_and_expansion_physical_pin_assignments(self):
        rows = motor_rows(load_config())
        self.assertEqual(
            [(row["in1_physical"], row["in2_physical"]) for row in rows[:4]],
            [(32, 31), (35, 36), (38, 40), (37, 33)],
        )
        self.assertEqual(
            [(row["in1_physical"], row["in2_physical"]) for row in rows[4:]],
            [(29, 22), (21, 23), (24, 26), (16, 18)],
        )

    def test_servo_board_uses_default_i2c_address(self):
        config = load_config()
        self.assertEqual(config.servos.addresses, (0x40,))
        self.assertEqual(config.servos.i2c_bus, 1)


if __name__ == "__main__":
    unittest.main()

