"""Pi 5 fan settings in config.txt and the read-only cooling status."""

import tempfile
import unittest
from pathlib import Path

from motion_module.cooling import BEGIN, END, configure, configured_text, cooling_status, managed_block
from motion_module.diagnostics import cooling_check


PI_OS_CONFIG = """# For more options and information see
# http://rptl.io/configtxt
# Some settings may impact device functionality. See link above for details

# Uncomment some or all of these to enable the optional hardware interfaces
dtparam=i2c_arm=on
#dtparam=i2s=on
#dtparam=spi=on

# Enable audio (loads snd_bcm2835)
dtparam=audio=on

camera_auto_detect=1
display_auto_detect=1
dtoverlay=vc4-kms-v3d
max_framebuffers=2

[cm5]
dtoverlay=dwc2,dr_mode=host

[all]

[all]
dtoverlay=i2c-gpio,i2c_gpio_sda=17,i2c_gpio_scl=18
"""


class FanConfiguration(unittest.TestCase):
    def test_the_block_holds_the_documented_parameters(self):
        block = managed_block()
        for line in (
            "[pi5]",
            "dtparam=cooling_fan=on",
            "dtparam=fan_temp0=47000",
            "dtparam=fan_temp0_hyst=2000",
            "dtparam=fan_temp1=50000",
            "dtparam=fan_temp2=67500",
            "dtparam=fan_temp3=75000",
            "[all]",
        ):
            self.assertIn(line + "\n", block)
        speeds = [int(line.split("=")[-1]) for line in block.splitlines() if "_speed=" in line]
        self.assertEqual(speeds, sorted(speeds))
        self.assertEqual(speeds, [191, 255, 255, 255])
        self.assertTrue(all(0 < speed <= 255 for speed in speeds))
        self.assertTrue(block.rstrip().endswith("[all]\n" + END))

    def test_adding_it_keeps_every_other_line_and_goes_before_any_overlay(self):
        text, message = configured_text(PI_OS_CONFIG)
        self.assertIn("Enabled Pi 5 fan cooling", message)
        self.assertEqual(text.replace(managed_block() + "\n", ""), PI_OS_CONFIG)
        # Base parameters placed after a dtoverlay line can be taken as that
        # overlay's parameters, so the block comes before the first setting.
        self.assertLess(text.index("dtparam=cooling_fan=on"), text.index("dtparam=i2c_arm=on"))
        self.assertLess(text.index("dtparam=cooling_fan=on"), text.index("dtoverlay="))
        self.assertTrue(text.startswith("# For more options"))

    def test_running_it_again_changes_nothing(self):
        once, _ = configured_text(PI_OS_CONFIG)
        twice, message = configured_text(once)
        self.assertEqual(twice, once)
        self.assertIn("already configured", message)
        self.assertEqual(twice.count(BEGIN), 1)

    def test_an_older_block_is_replaced_not_duplicated(self):
        stale = PI_OS_CONFIG + "\n" + BEGIN + "\n[pi5]\ndtparam=fan_temp0=40000\n[all]\n" + END + "\n"
        text, message = configured_text(stale)
        self.assertIn("Updated", message)
        self.assertEqual(text.count(BEGIN), 1)
        self.assertNotIn("fan_temp0=40000", text)
        self.assertIn("dtoverlay=i2c-gpio,i2c_gpio_sda=17,i2c_gpio_scl=18", text)

    def test_fan_settings_someone_wrote_themselves_are_left_in_charge(self):
        own = PI_OS_CONFIG + "[pi5]\ndtparam=fan_temp0=55000\n"
        text, message = configured_text(own)
        self.assertEqual(text, own)
        self.assertIn("Kept the Pi 5 fan settings", message)
        commented = PI_OS_CONFIG + "#dtparam=fan_temp0=55000\n"
        self.assertIn(BEGIN, configured_text(commented)[0])

    def test_a_block_missing_its_end_marker_is_not_guessed_at(self):
        broken = BEGIN + "\n[pi5]\ndtparam=audio=on\n"
        text, _ = configured_text(broken)
        self.assertIn("dtparam=audio=on", text)

    def test_configure_writes_a_backup_only_when_it_changes_the_file(self):
        folder = Path(tempfile.mkdtemp())
        config = folder / "config.txt"
        config.write_bytes(PI_OS_CONFIG.encode())
        message = configure(config)
        backups = list(folder.glob("config.txt.motionmodule-*.bak"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), PI_OS_CONFIG.encode())
        self.assertIn(str(backups[0]), message)
        self.assertIn(managed_block(), config.read_text())
        configure(config)
        self.assertEqual(len(list(folder.glob("config.txt.motionmodule-*.bak"))), 1)
        self.assertEqual(sorted(path.name for path in folder.iterdir()),
                         sorted(["config.txt", backups[0].name]))


def fake_sys(temperature=None, fan=None, rpm=None, pwm=None):
    root = Path(tempfile.mkdtemp())
    thermal = root / "sys/class/thermal"
    (thermal / "thermal_zone0").mkdir(parents=True)
    if temperature is not None:
        (thermal / "thermal_zone0/temp").write_text(f"{int(temperature * 1000)}\n")
    (thermal / "cooling_device0").mkdir()
    (thermal / "cooling_device0/type").write_text("thermal-cpufreq-0\n")
    if fan is not None:
        (thermal / "cooling_device1").mkdir()
        (thermal / "cooling_device1/type").write_text("pwm-fan\n")
        (thermal / "cooling_device1/cur_state").write_text(f"{fan}\n")
        (thermal / "cooling_device1/max_state").write_text("4\n")
        hwmon = root / "sys/class/hwmon/hwmon2"
        hwmon.mkdir(parents=True)
        (hwmon / "name").write_text("pwmfan\n")
        if rpm is not None:
            (hwmon / "fan1_input").write_text(f"{rpm}\n")
        if pwm is not None:
            (hwmon / "pwm1").write_text(f"{pwm}\n")
    return root


class CoolingStatus(unittest.TestCase):
    def test_no_fan_control_is_unknown_not_zero(self):
        status = cooling_status(fake_sys(temperature=58.3))
        self.assertEqual(status["temperature_c"], 58.3)
        self.assertFalse(status["fan_found"])
        self.assertIsNone(status["state"])
        self.assertIsNone(status["rpm"])
        self.assertEqual(status["level"], "unknown")
        self.assertEqual(cooling_check(status)["level"], "info")

    def test_nothing_readable_at_all(self):
        status = cooling_status(Path(tempfile.mkdtemp()))
        self.assertIsNone(status["temperature_c"])
        self.assertIn("unavailable", status["summary"])

    def test_a_cool_pi_with_a_stopped_fan_is_fine(self):
        status = cooling_status(fake_sys(temperature=41.0, fan=0, rpm=0, pwm=0))
        self.assertEqual((status["state"], status["rpm"]), (0, 0))
        self.assertEqual(status["level"], "ok")
        self.assertIn("off, as expected", status["summary"])
        self.assertEqual(cooling_check(status)["level"], "pass")

    def test_fan_off_at_new_start_threshold_is_a_warning(self):
        self.assertEqual(cooling_status(fake_sys(temperature=47, fan=0, rpm=0, pwm=0))['level'], 'warn')

    def test_a_running_fan_reports_its_level_and_speed(self):
        status = cooling_status(fake_sys(temperature=62.0, fan=2, rpm=3100, pwm=125))
        self.assertEqual((status["state"], status["rpm"], status["pwm"]), (2, 3100, 125))
        self.assertEqual(status["level"], "ok")
        self.assertIn("3100 RPM", status["summary"])

    def test_a_missing_tachometer_is_not_read_as_stopped(self):
        status = cooling_status(fake_sys(temperature=62.0, fan=2))
        self.assertIsNone(status["rpm"])
        self.assertEqual(status["level"], "ok")
        self.assertIn("no speed reading", status["summary"])

    def test_a_fan_asked_to_run_that_reads_zero_rpm_is_a_warning(self):
        status = cooling_status(fake_sys(temperature=63.0, fan=2, rpm=0, pwm=125))
        self.assertEqual(status["level"], "warn")
        check = cooling_check(status)
        self.assertEqual(check["level"], "warn")
        self.assertIn("FAN connector", check["detail"])
        self.assertIn("switch the Pi off", check["detail"])

    def test_hot_but_never_asked_to_run_is_a_warning(self):
        status = cooling_status(fake_sys(temperature=55.0, fan=0, rpm=0))
        self.assertEqual(status["level"], "warn")


if __name__ == "__main__":
    unittest.main()
