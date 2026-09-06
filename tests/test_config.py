import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from motion_module.config import (
    DEFAULT_HARDWARE_PATH,
    default_config,
    hardware_source,
    load_config,
    load_hardware_file,
    load_project_config,
    resolve_config_path,
)
from motion_module.errors import ConfigurationError
from motion_module.pinout import header_rows, motor_rows


class DefaultConfigTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        environment = patch.dict(os.environ, {
            "MOTIONMODULE_ACTIVE_PROJECT": "",
            "MOTIONMODULE_CONFIG": "",
            "MOTIONMODULE_CONFIG_DIR": directory.name,
        })
        environment.start()
        self.addCleanup(environment.stop)

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

    def test_the_shipped_hardware_file_is_the_default_pin_map(self):
        self.assertTrue(DEFAULT_HARDWARE_PATH.is_file())
        self.assertEqual(DEFAULT_HARDWARE_PATH.name, "hardware.py")
        self.assertEqual(load_config(), default_config())

    def test_every_motor_uses_two_close_header_pins_on_one_side(self):
        rows = motor_rows(load_config())
        self.assertEqual(
            [(row["in1_physical"], row["in2_physical"]) for row in rows],
            [(37, 35), (33, 31), (40, 38), (36, 32),
             (23, 21), (26, 24), (15, 13), (18, 16)],
        )
        for row in rows:
            first, second = row["in1_physical"], row["in2_physical"]
            self.assertEqual(first % 2, second % 2, row["name"])
            gap = abs(first - second)
            if gap == 2:
                continue
            # The one exception is allowed to straddle its own driver ground.
            self.assertEqual(gap, 4, row["name"])
            self.assertEqual((first + second) // 2, row["ground_physical"], row["name"])

    def test_each_driver_is_one_run_of_header_positions_around_its_ground(self):
        blocks = {}
        for row in motor_rows(load_config()):
            blocks.setdefault(row["driver"], set()).update(
                [row["in1_physical"], row["in2_physical"], row["ground_physical"]]
            )
        self.assertEqual(sorted(blocks[1]), [31, 33, 35, 37, 39])
        self.assertEqual(sorted(blocks[2]), [32, 34, 36, 38, 40])
        self.assertEqual(sorted(blocks[3]), [21, 23, 24, 25, 26])
        self.assertEqual(sorted(blocks[4]), [13, 14, 15, 16, 18])
        # Every driver's pins stay inside a five-position window.
        for driver, pins in blocks.items():
            self.assertLessEqual(max(pins) - min(pins), 8, f"driver {driver}")

    def test_the_default_uart_pair_is_left_free(self):
        used = {pin for row in motor_rows(load_config())
                for pin in (row["in1_physical"], row["in2_physical"])}
        self.assertNotIn(8, used)   # GPIO14 / TXD
        self.assertNotIn(10, used)  # GPIO15 / RXD

    def test_servo_board_uses_default_i2c_address(self):
        config = load_config()
        self.assertEqual(config.servos.addresses, (0x40,))
        self.assertEqual(config.servos.i2c_bus, 1)

    def test_driver_labels_and_full_header_match_documented_harness(self):
        config = load_config()
        rows = motor_rows(config)
        self.assertEqual([(row["driver"], row["output"]) for row in rows[:4]], [(1, "A"), (1, "B"), (2, "A"), (2, "B")])
        header = header_rows(config)
        self.assertEqual(len(header), 40)
        self.assertEqual(header[26]["category"], "reserved")
        self.assertEqual(header[39]["role"], "motor_3 · Driver 2A IN1")

    def test_default_names_follow_the_motor_and_servo_channel_numbers(self):
        config = load_config()
        self.assertEqual(
            {motor.channel: motor.name for motor in config.motors},
            {channel: f"motor_{channel}" for channel in range(1, 9)},
        )
        self.assertEqual(
            config.servo_names, tuple(f"servo_{number}" for number in range(1, 17))
        )

    def test_names_resolve_to_channels_in_both_directions(self):
        config = load_config()
        self.assertEqual(config.motor_channel("motor_5"), 5)
        self.assertEqual(config.motor_channel("MOTOR_5"), 5)
        self.assertEqual(config.motor_channel(5), 5)
        self.assertEqual(config.servo_slot("servo_3").channel, 2)
        self.assertEqual(config.servo_slot(2).name, "servo_3")
        with self.assertRaisesRegex(ConfigurationError, "No motor is named"):
            config.motor_channel("left_front")

    def test_duplicate_names_are_rejected(self):
        hardware = '''
HARDWARE = {
    "module": {"pwm_hz": 1000, "deadtime_ms": 5, "watchdog_ms": 500},
    "motors": {
        1: {"name": "arm", "forward_gpio": 4, "reverse_gpio": 17},
        2: {"name": "arm", "forward_gpio": 22, "reverse_gpio": 27},
    },
    "servos": {
        "enabled": True,
        "i2c_bus": 1,
        "frequency_hz": 50,
        "addresses": [0x40],
        "minimum_pulse_us": 500,
        "maximum_pulse_us": 2500,
    },
}
'''
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "hardware.py").write_text(hardware, encoding="utf-8")
            with self.assertRaisesRegex(ConfigurationError, "unique name"):
                load_project_config(project)

    def test_project_hardware_is_loaded_from_literal_python_data(self):
        project = Path(__file__).resolve().parents[1] / "examples" / "Mecanum"
        config = load_project_config(project)
        self.assertEqual(len(config.motors), 8)
        self.assertEqual(config.motors[0].forward_gpio, 26)
        self.assertEqual(config.motors[0].name, "front_left")
        with patch.dict(os.environ, {"MOTIONMODULE_ACTIVE_PROJECT": str(project)}):
            self.assertEqual(load_config(), config)

    def test_a_project_without_hardware_py_uses_the_shipped_names(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"MOTIONMODULE_ACTIVE_PROJECT": directory}):
                self.assertEqual(load_config(), default_config())

    def test_project_hardware_never_executes_student_code(self):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory)
            (project / "hardware.py").write_text(
                "import os\nHARDWARE = {}\nos.system('never')\n", encoding="utf-8"
            )
            with self.assertRaisesRegex(ConfigurationError, "plain value assignments"):
                load_project_config(project)

    def test_python_api_finds_the_installed_hardware_without_shell_environment(self):
        installed = Path(os.environ["MOTIONMODULE_CONFIG_DIR"]) / "hardware.py"
        config = replace(default_config(), watchdog_ms=750)
        installed.write_text(hardware_source(config), encoding="utf-8")
        self.assertEqual(resolve_config_path(), installed)
        self.assertEqual(load_config(), config)

    def test_explicit_project_overrides_the_active_project_environment(self):
        example = Path(__file__).resolve().parents[1] / "examples" / "Mecanum"
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict(os.environ, {"MOTIONMODULE_ACTIVE_PROJECT": str(example)}):
                self.assertEqual(load_config(project=example).motor_channel("front_left"), 1)
                self.assertEqual(load_config(project=directory), default_config())

    def test_missing_selected_hardware_does_not_silently_use_other_pins(self):
        missing = Path(os.environ["MOTIONMODULE_CONFIG_DIR"]) / "missing.py"
        with patch.dict(os.environ, {"MOTIONMODULE_CONFIG": str(missing)}):
            with self.assertRaisesRegex(ConfigurationError, "not found"):
                load_config()

    def test_export_preserves_custom_pins_names_and_multiple_servo_boards(self):
        config = default_config()
        motors = (replace(config.motors[0], name="left_wheel", inverted=False), *config.motors[1:])
        slots = (*config.servos.channels, replace(config.servos.channels[2], name="claw", board=1))
        config = replace(config, motors=motors, servos=replace(config.servos, addresses=(0x40, 0x41), channels=slots))
        output = Path(os.environ["MOTIONMODULE_CONFIG_DIR"]) / "hardware.py"
        output.write_text(hardware_source(config), encoding="utf-8-sig")
        self.assertEqual(load_hardware_file(output), config)

    def test_duplicate_channel_keys_cannot_silently_replace_a_motor(self):
        source = DEFAULT_HARDWARE_PATH.read_text(encoding="utf-8").replace(
            '2: {"name": "motor_2"', '1: {"name": "motor_2"'
        )
        output = Path(os.environ["MOTIONMODULE_CONFIG_DIR"]) / "hardware.py"
        output.write_text(source, encoding="utf-8")
        with self.assertRaisesRegex(ConfigurationError, "Duplicate dictionary key"):
            load_hardware_file(output)

    def test_non_integer_channel_keys_are_rejected(self):
        for bad in ("True", "1.5"):
            source = DEFAULT_HARDWARE_PATH.read_text(encoding="utf-8").replace(
                '1: {"name": "motor_1"', f'{bad}: {{"name": "motor_1"'
            )
            output = Path(os.environ["MOTIONMODULE_CONFIG_DIR"]) / "hardware.py"
            output.write_text(source, encoding="utf-8")
            with self.subTest(key=bad), self.assertRaisesRegex(ConfigurationError, "integer"):
                load_hardware_file(output)

    def test_legacy_toml_upgrade_preserves_custom_pins_and_runtime_settings(self):
        folder = Path(os.environ["MOTIONMODULE_CONFIG_DIR"])
        legacy = folder / "config.toml"
        legacy.write_text('''
[module]
pwm_hz = 500
deadtime_ms = 20
watchdog_ms = 750
[motors.5]
name = "intake"
forward_gpio = 4
reverse_gpio = 17
inverted = true
[servos]
enabled = true
i2c_bus = 1
frequency_hz = 60
addresses = [0x41]
minimum_pulse_us = 600
maximum_pulse_us = 2400
''', encoding="utf-8")
        original = load_config(legacy)
        self.assertEqual(resolve_config_path(), legacy)
        installed = folder / "hardware.py"
        installed.write_text(hardware_source(original), encoding="utf-8")
        self.assertEqual(resolve_config_path(), installed)
        self.assertEqual(load_config(), original)
        self.assertEqual((original.motor(5).forward_gpio, original.motor(5).reverse_gpio), (4, 17))
        self.assertTrue(legacy.exists())


if __name__ == "__main__":
    unittest.main()
