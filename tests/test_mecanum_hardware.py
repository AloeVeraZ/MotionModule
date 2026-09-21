"""The legacy configuration observed on the Pi must actually receive the fix."""

import tempfile
import unittest
from dataclasses import replace
from pathlib import Path

from motion_module.config import default_config, hardware_source, load_config
from motion_module.controller import MotionModule
from motion_module.gpio import MockGPIO
from motion_module.mecanum_hardware import provision_mecanum_hardware


class LegacyMecanumHardwareTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.project = self.root / "robots" / "Mecanum"
        self.project.mkdir(parents=True)
        self.robot = self.project / "robot.py"
        self.robot.write_text("# Preserve this robot's own code\n", encoding="utf-8")
        self.installed = self.root / "hardware.py"
        config = default_config()
        # This is the map returned by the live Pi: driver_* names, locked
        # GPIOs, all eight channels uninverted, and no project hardware.py.
        self.before = replace(config, motors=tuple(replace(m, inverted=False) for m in config.motors))
        self.installed.write_text(hardware_source(self.before), encoding="utf-8")

    def test_upgrade_reverses_only_1b_and_2b_and_preserves_every_other_setting(self):
        installed_bytes = self.installed.read_bytes()
        robot_bytes = self.robot.read_bytes()
        self.assertIn("Driver 1B and 2B", provision_mecanum_hardware(self.project, self.installed))
        after = load_config(project=self.project)
        expected = replace(self.before, motors=tuple(
            replace(m, inverted=True) if m.channel in (2, 4) else m for m in self.before.motors
        ))
        self.assertEqual(after, expected)
        self.assertEqual(self.installed.read_bytes(), installed_bytes)
        self.assertEqual(self.robot.read_bytes(), robot_bytes)
        # Compare actual electrical outputs before/after for each motor and
        # direction, including unaffected spare channels.
        for motor in self.before.motors:
            for power in (-0.25, 0.25):
                outputs = []
                for config in (self.before, after):
                    gpio = MockGPIO()
                    with MotionModule(config, gpio=gpio) as module:
                        module.motor(motor.name).set(power)
                        outputs.append((gpio.values[motor.forward_gpio], gpio.values[motor.reverse_gpio]))
                self.assertEqual(outputs[1], outputs[0][::-1] if motor.channel in (2, 4) else outputs[0])

    def test_existing_project_hardware_and_later_tuning_are_never_overwritten(self):
        target = self.project / "hardware.py"
        target.write_text("# my own hardware file\n", encoding="utf-8")
        self.assertIsNone(provision_mecanum_hardware(self.project, self.installed))
        self.assertEqual(target.read_text(encoding="utf-8"), "# my own hardware file\n")

    def test_a_second_update_does_not_flip_the_motors_again(self):
        provision_mecanum_hardware(self.project, self.installed)
        target = self.project / "hardware.py"
        before = target.read_bytes()
        self.assertIsNone(provision_mecanum_hardware(self.project, self.installed))
        self.assertEqual(target.read_bytes(), before)

    def test_custom_timing_servo_settings_and_other_motor_polarity_are_preserved(self):
        custom = replace(
            self.before, pwm_hz=800, deadtime_ms=20, watchdog_ms=700,
            motors=tuple(replace(m, inverted=True) if m.channel == 7 else m for m in self.before.motors),
            servos=replace(self.before.servos, minimum_pulse_us=600, maximum_pulse_us=2400),
        )
        self.installed.write_text(hardware_source(custom), encoding="utf-8")
        provision_mecanum_hardware(self.project, self.installed)
        after = load_config(project=self.project)
        expected = replace(custom, motors=tuple(
            replace(m, inverted=True) if m.channel in (2, 4) else m for m in custom.motors
        ))
        self.assertEqual(after, expected)

    def test_other_robot_projects_are_left_alone(self):
        other = self.project.with_name("MyRobot")
        self.project.rename(other)
        self.assertIsNone(provision_mecanum_hardware(other, self.installed))
        self.assertFalse((other / "hardware.py").exists())

    def test_other_wiring_is_left_alone(self):
        different = replace(self.before, motors=(
            replace(self.before.motors[0], forward_gpio=17), *self.before.motors[1:],
        ))
        self.installed.write_text(hardware_source(different), encoding="utf-8")
        self.assertIn("wiring differs", provision_mecanum_hardware(self.project, self.installed))
        self.assertFalse((self.project / "hardware.py").exists())

    def test_installer_runs_repair_on_the_active_project_before_restarting(self):
        script = (Path(__file__).resolve().parents[1] / "installer" / "install.sh").read_text(encoding="utf-8")
        call = '-m motion_module.mecanum_hardware "$active_target" "$CONFIG_FILE"'
        self.assertLess(script.index("-m motion_module.retired_wiring"), script.index(call))
        self.assertLess(script.index(call), script.index("if ! sudo systemctl restart motionmodule.service;"))
