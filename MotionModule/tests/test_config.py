import unittest
from pathlib import Path

from motion_module.config import DEFAULT_CONFIG_PATH, load_config
from motion_module.pinout import header_rows, motor_rows


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

    def test_default_config_resolves_outside_the_core_package(self):
        expected = Path(__file__).resolve().parents[1] / "config" / "default.toml"
        self.assertEqual(DEFAULT_CONFIG_PATH, expected)

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

    def test_driver_labels_and_full_header_match_documented_harness(self):
        config = load_config()
        rows = motor_rows(config)
        self.assertEqual([(row["driver"], row["output"]) for row in rows[:4]], [(2, "A"), (2, "B"), (1, "A"), (1, "B")])
        header = header_rows(config)
        self.assertEqual(len(header), 40)
        self.assertEqual(header[26]["category"], "reserved")
        self.assertEqual(header[39]["role"], "Driver 1 A IN2 · Motor 3")


if __name__ == "__main__":
    unittest.main()
