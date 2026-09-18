"""An install moves pin maps left on the retired wiring onto the locked wiring.

Every pin map MotionModule shipped until 6 September 2026 used other pins. A
Pi set up then kept its copies in robots/Mecanum and ~/.config/motionmodule
through every later install, so it drove, and drew, the old pins on a robot
wired the new way. core/motion_module/retired_wiring.py explains.
"""

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from motion_module.config import DEFAULT_HARDWARE_PATH, load_hardware_file
from motion_module.retired_wiring import BACKUP_SUFFIX, main, on_retired_wiring, replace_retired_pin_maps

ROOT = Path(__file__).resolve().parents[1]
MECANUM_HARDWARE = ROOT / "examples" / "Mecanum" / "hardware.py"
INSTALLER = ROOT / "installer" / "install.sh"

# examples/Mecanum/hardware.py as MotionModule shipped it on 2 September 2026.
# A Pi set up then still has exactly this in robots/Mecanum.
SEPTEMBER_MECANUM = '''"""Pins and electrical behavior that travel with this robot project.

MotionModule reads this file as literal Python data before starting robot.py.
Do not add imports, function calls, or calculated values here.
"""

HARDWARE = {
    "module": {
        "pwm_hz": 1000,
        "deadtime_ms": 15,
        "watchdog_ms": 500,
    },
    "motors": {
        1: {"name": "front_left", "forward_gpio": 12, "reverse_gpio": 6, "inverted": True},
        2: {"name": "rear_left", "forward_gpio": 19, "reverse_gpio": 16, "inverted": True},
        3: {"name": "front_right", "forward_gpio": 20, "reverse_gpio": 21, "inverted": True},
        4: {"name": "rear_right", "forward_gpio": 26, "reverse_gpio": 13, "inverted": True},
        5: {"name": "driver3_a", "forward_gpio": 5, "reverse_gpio": 25, "inverted": False},
        6: {"name": "driver3_b", "forward_gpio": 9, "reverse_gpio": 11, "inverted": False},
        7: {"name": "driver4_a", "forward_gpio": 8, "reverse_gpio": 7, "inverted": False},
        8: {"name": "driver4_b", "forward_gpio": 23, "reverse_gpio": 24, "inverted": False},
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
# The installed pin map a Pi set up in August was given: the same pins under
# the driver names that release used.
AUGUST_INSTALLED = (
    SEPTEMBER_MECANUM.replace('"front_left"', '"driver2_a"')
    .replace('"rear_left"', '"driver2_b"')
    .replace('"front_right"', '"driver1_a"')
    .replace('"rear_right"', '"driver1_b"')
)


class RetiredWiringTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.robots = self.root / "robots"
        self.installed = self.root / "config" / "hardware.py"

    def write(self, path: Path, text: str) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return path

    def test_old_pin_maps_are_recognised_by_their_pins_alone(self):
        self.assertTrue(on_retired_wiring(self.write(self.root / "september.py", SEPTEMBER_MECANUM)))
        self.assertTrue(on_retired_wiring(self.write(self.root / "august.py", AUGUST_INSTALLED)))
        for shipped in (DEFAULT_HARDWARE_PATH, MECANUM_HARDWARE):
            with self.subTest(path=shipped.name):
                self.assertFalse(on_retired_wiring(shipped))

    def test_install_moves_old_pin_maps_onto_the_locked_wiring(self):
        robot = self.write(self.robots / "Mecanum" / "hardware.py", SEPTEMBER_MECANUM)
        self.write(self.installed, AUGUST_INSTALLED)

        messages = replace_retired_pin_maps(self.robots, self.installed)

        self.assertEqual(robot.read_bytes(), MECANUM_HARDWARE.read_bytes())
        self.assertEqual(self.installed.read_bytes(), DEFAULT_HARDWARE_PATH.read_bytes())
        self.assertEqual(robot.with_name("hardware.py" + BACKUP_SUFFIX).read_text(encoding="utf-8"),
                         SEPTEMBER_MECANUM)
        self.assertEqual(self.installed.with_name("hardware.py" + BACKUP_SUFFIX).read_text(encoding="utf-8"),
                         AUGUST_INSTALLED)
        self.assertEqual(len(messages), 2)
        self.assertIn(str(robot), messages[0])
        self.assertIn(str(self.installed), messages[1])
        for message in messages:
            self.assertNotIn("\n", message)
            self.assertIn("test each wheel with the robot raised", message)

    def test_the_mecanum_wheels_keep_their_names_and_channels(self):
        robot = self.write(self.robots / "Mecanum" / "hardware.py", SEPTEMBER_MECANUM)
        before = {motor.channel: motor.name for motor in load_hardware_file(robot).motors if motor.channel <= 4}

        replace_retired_pin_maps(self.robots, self.installed)

        after = {motor.channel: motor.name for motor in load_hardware_file(robot).motors if motor.channel <= 4}
        self.assertEqual(after, before)

    def test_a_second_install_changes_nothing(self):
        robot = self.write(self.robots / "Mecanum" / "hardware.py", SEPTEMBER_MECANUM)
        self.write(self.installed, AUGUST_INSTALLED)
        replace_retired_pin_maps(self.robots, self.installed)

        self.assertEqual(replace_retired_pin_maps(self.robots, self.installed), [])
        self.assertEqual(sorted(path.name for path in robot.parent.iterdir()),
                         ["hardware.py", "hardware.py" + BACKUP_SUFFIX])

    def test_a_robot_tuned_or_wired_its_own_way_is_never_changed(self):
        # Wheels flipped after the move, and one motor moved to other pins.
        tuned = MECANUM_HARDWARE.read_text(encoding="utf-8").replace('"inverted": False', '"inverted": True', 2)
        own_pins = SEPTEMBER_MECANUM.replace('"reverse_gpio": 24', '"reverse_gpio": 17')
        for label, text in (("tuned", tuned), ("own-pins", own_pins)):
            with self.subTest(label):
                robots = self.root / label / "robots"
                robot = self.write(robots / "Mecanum" / "hardware.py", text)

                self.assertEqual(replace_retired_pin_maps(robots, self.installed), [])
                self.assertEqual(robot.read_text(encoding="utf-8"), text)
                self.assertEqual([path.name for path in robot.parent.iterdir()], ["hardware.py"])

    def test_a_robot_with_no_matching_sample_is_reported_not_replaced(self):
        robot = self.write(self.robots / "MyRobot" / "hardware.py", SEPTEMBER_MECANUM)

        messages = replace_retired_pin_maps(self.robots, self.installed)

        self.assertEqual(robot.read_text(encoding="utf-8"), SEPTEMBER_MECANUM)
        self.assertEqual(len(messages), 1)
        self.assertIn(str(robot), messages[0])
        self.assertIn("docs/PINOUT.md", messages[0])

    def test_unreadable_pin_maps_and_upload_staging_folders_are_left_alone(self):
        broken = self.write(self.robots / "Mecanum" / "hardware.py", "HARDWARE = {\n")
        staging = self.write(self.robots / ".Mecanum.deploy-1234" / "hardware.py", SEPTEMBER_MECANUM)

        self.assertEqual(replace_retired_pin_maps(self.robots, self.installed), [])
        self.assertEqual(broken.read_text(encoding="utf-8"), "HARDWARE = {\n")
        self.assertEqual(staging.read_text(encoding="utf-8"), SEPTEMBER_MECANUM)

    def test_an_earlier_copy_is_never_overwritten(self):
        robot = self.write(self.robots / "Mecanum" / "hardware.py", SEPTEMBER_MECANUM)
        earlier = self.write(robot.with_name("hardware.py" + BACKUP_SUFFIX), "# kept from before\n")

        messages = replace_retired_pin_maps(self.robots, self.installed)

        self.assertEqual(earlier.read_text(encoding="utf-8"), "# kept from before\n")
        self.assertEqual(robot.with_name(f"hardware.py{BACKUP_SUFFIX}.1").read_text(encoding="utf-8"),
                         SEPTEMBER_MECANUM)
        self.assertIn(f"hardware.py{BACKUP_SUFFIX}.1", messages[0])

    def test_a_pi_with_nothing_to_move_prints_nothing(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main([str(self.robots), str(self.installed)]), 0)
        self.assertEqual(output.getvalue(), "")

    def test_the_command_prints_one_line_per_moved_pin_map(self):
        self.write(self.robots / "Mecanum" / "hardware.py", SEPTEMBER_MECANUM)
        self.write(self.installed, AUGUST_INSTALLED)
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main([str(self.robots), str(self.installed)]), 0)
        self.assertEqual(len(output.getvalue().splitlines()), 2)

    def test_installer_moves_old_pin_maps_before_the_new_release_starts(self):
        script = INSTALLER.read_text(encoding="utf-8")
        command = '-m motion_module.retired_wiring "$ROBOT_DIR" "$CONFIG_FILE"'
        self.assertIn(command, script)
        # After the installed pin map exists, before the service restarts on
        # the new release, so the dashboard comes back on the locked wiring.
        self.assertLess(script.index('say "Installed the default pin and name definitions'), script.index(command))
        self.assertLess(script.index(command), script.index("if ! sudo systemctl restart motionmodule.service; then"))


if __name__ == "__main__":
    unittest.main()
