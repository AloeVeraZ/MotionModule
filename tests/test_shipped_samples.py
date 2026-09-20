"""An install gives a robot folder nobody edited the sample this release ships.

A Pi keeps its robot folders through every install, so the copy of a sample it
was first given stayed on it: a fix to the sample, such as a motor's
`inverted` value, never reached the robot. A folder whose files are all copies
MotionModule shipped holds nobody's work, so the install now replaces it and
keeps the old folder under backups. core/motion_module/shipped_samples.py
explains.
"""

import io
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from motion_module.shipped_samples import (
    EXAMPLES_DIRECTORY,
    digest,
    folder_digests,
    main,
    refresh_untouched_samples,
    shipped_digests,
)

MECANUM_SAMPLE = EXAMPLES_DIRECTORY / "Mecanum"
INSTALLER = Path(__file__).resolve().parents[1] / "installer" / "install.sh"

# examples/Mecanum/hardware.py as MotionModule shipped it on 2 September 2026.
# tests/test_retired_wiring.py keeps that file in full; this is what an install
# sees of it. A Pi set up then still has exactly this in robots/Mecanum.
SEPTEMBER_HARDWARE_DIGEST = "fa396c31a26bf46a8f2e1b0993f9da1d82d16ef8c3c8387cc32b27c137db35b1"


class ShippedSampleTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.robots = self.root / "robots"
        self.backups = self.root / "backups"
        self.robots.mkdir()

    def copy_sample(self, target: Path, **edits: str) -> Path:
        """A copy of the Mecanum sample, with any named file written over."""

        shutil.copytree(
            MECANUM_SAMPLE, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc")
        )
        for name, text in edits.items():
            (target / name).write_text(text, encoding="utf-8", newline="\n")
        return target

    def older_release(self, **edits: str) -> Path:
        """The examples directory of a release that shipped an older sample."""

        examples = self.root / "older" / "examples"
        self.copy_sample(examples / "Mecanum", **edits)
        return examples

    def backup_folders(self) -> list[Path]:
        return sorted(self.backups.iterdir()) if self.backups.is_dir() else []

    def test_a_folder_that_is_still_a_shipped_sample_gets_this_release_s_copy(self):
        older = self.older_release(**{"hardware.py": "HARDWARE = {}  # an older copy\n"})
        robot = self.copy_sample(
            self.robots / "Mecanum", **{"hardware.py": "HARDWARE = {}  # an older copy\n"}
        )

        messages = refresh_untouched_samples(self.robots, self.backups, older)

        self.assertEqual(folder_digests(robot), folder_digests(MECANUM_SAMPLE))
        self.assertEqual(len(messages), 1)
        self.assertIn(str(robot), messages[0])
        self.assertIn("test each wheel with the robot raised", messages[0])
        self.assertNotIn("\n", messages[0])

    def test_the_folder_that_was_replaced_is_kept_under_backups(self):
        older = self.older_release(**{"robot.py": "# the sample as it was\n"})
        self.copy_sample(self.robots / "Mecanum", **{"robot.py": "# the sample as it was\n"})

        messages = refresh_untouched_samples(self.robots, self.backups, older)

        kept = self.backup_folders()
        self.assertEqual(len(kept), 1)
        self.assertEqual((kept[0] / "robot.py").read_text(encoding="utf-8"), "# the sample as it was\n")
        self.assertIn(str(kept[0]), messages[0])

    def test_a_folder_with_work_of_its_own_is_never_changed(self):
        robot = self.copy_sample(self.robots / "Mecanum")
        mine = "# my drive code\n" + (robot / "robot.py").read_text(encoding="utf-8")
        (robot / "robot.py").write_text(mine, encoding="utf-8", newline="\n")
        before = folder_digests(robot)

        messages = refresh_untouched_samples(self.robots, self.backups, self.older_release())

        self.assertEqual(folder_digests(robot), before)
        self.assertEqual(self.backup_folders(), [])
        self.assertEqual(len(messages), 1)
        self.assertIn("robot.py", messages[0])
        self.assertIn("Code page", messages[0])

    def test_a_file_of_the_robot_s_own_keeps_the_whole_folder(self):
        robot = self.copy_sample(self.robots / "Mecanum", **{"arm.py": "# my mechanism\n"})
        before = folder_digests(robot)

        messages = refresh_untouched_samples(self.robots, self.backups, self.older_release())

        self.assertEqual(folder_digests(robot), before)
        self.assertIn("arm.py", messages[0])

    def test_running_the_sample_or_moving_its_pins_does_not_make_it_edited(self):
        older = self.older_release(**{"robot.py": "# the sample as it was\n"})
        robot = self.copy_sample(self.robots / "Mecanum", **{"robot.py": "# the sample as it was\n"})
        # What a Pi collects on its own: bytecode from running the robot, and
        # the pin map the retired-wiring move replaced.
        (robot / "__pycache__").mkdir()
        (robot / "__pycache__" / "robot.cpython-311.pyc").write_bytes(b"\x00compiled")
        (robot / "hardware.py.retired-wiring").write_text("# the old pins\n", encoding="utf-8")

        messages = refresh_untouched_samples(self.robots, self.backups, older)

        self.assertEqual(folder_digests(robot), folder_digests(MECANUM_SAMPLE))
        self.assertEqual(len(messages), 1)
        self.assertIn("Updated", messages[0])

    def test_a_folder_already_holding_this_release_s_sample_is_left_alone(self):
        robot = self.copy_sample(self.robots / "Mecanum")

        self.assertEqual(refresh_untouched_samples(self.robots, self.backups), [])
        self.assertEqual(folder_digests(robot), folder_digests(MECANUM_SAMPLE))
        self.assertEqual(self.backup_folders(), [])

    def test_a_second_install_changes_nothing(self):
        older = self.older_release(**{"hardware.py": "HARDWARE = {}  # an older copy\n"})
        self.copy_sample(
            self.robots / "Mecanum", **{"hardware.py": "HARDWARE = {}  # an older copy\n"}
        )
        refresh_untouched_samples(self.robots, self.backups, older)

        self.assertEqual(refresh_untouched_samples(self.robots, self.backups, older), [])
        self.assertEqual(len(self.backup_folders()), 1)

    def test_a_robot_with_a_name_of_its_own_is_not_touched(self):
        robot = self.copy_sample(self.robots / "MyRobot")
        before = folder_digests(robot)

        self.assertEqual(refresh_untouched_samples(self.robots, self.backups), [])
        self.assertEqual(folder_digests(robot), before)

    def test_a_pi_without_that_robot_folder_is_left_alone(self):
        self.assertEqual(refresh_untouched_samples(self.robots, self.backups), [])
        self.assertFalse((self.robots / "Mecanum").exists())

    def test_the_active_project_keeps_its_path(self):
        older = self.older_release(**{"robot.py": "# the sample as it was\n"})
        robot = self.copy_sample(self.robots / "Mecanum", **{"robot.py": "# the sample as it was\n"})
        active = self.root / "active"
        try:
            active.symlink_to(robot, target_is_directory=True)
        except (OSError, NotImplementedError):
            self.skipTest("this computer does not allow symbolic links")

        refresh_untouched_samples(self.robots, self.backups, older)

        self.assertTrue((active / "robot.py").is_file())
        self.assertEqual(
            (active / "robot.py").read_bytes(), (MECANUM_SAMPLE / "robot.py").read_bytes()
        )

    def test_the_shipped_list_covers_the_copies_a_pi_can_still_have(self):
        shipped = shipped_digests()

        self.assertIn("Mecanum", shipped)
        mecanum = shipped["Mecanum"]
        # A Pi set up in September has the September sample: robot.py and the
        # mecanum.py beside it, which later samples no longer ship.
        self.assertLessEqual({"README.md", "hardware.py", "mecanum.py", "robot.py"}, set(mecanum))
        self.assertIn(SEPTEMBER_HARDWARE_DIGEST, mecanum["hardware.py"])

    def test_line_endings_do_not_decide_whether_a_folder_was_edited(self):
        text = "HARDWARE = {}  # an older copy\n"
        older = self.older_release(**{"hardware.py": text})
        robot = self.copy_sample(self.robots / "Mecanum")
        (robot / "hardware.py").write_bytes(text.replace("\n", "\r\n").encode("utf-8"))

        self.assertEqual(digest(text.encode()), digest(text.replace("\n", "\r\n").encode()))
        self.assertEqual(len(refresh_untouched_samples(self.robots, self.backups, older)), 1)
        self.assertEqual(folder_digests(robot), folder_digests(MECANUM_SAMPLE))

    def test_a_pi_with_nothing_to_update_prints_nothing(self):
        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(main([str(self.robots), str(self.backups)]), 0)
        self.assertEqual(output.getvalue(), "")

    def test_the_command_prints_one_line_per_robot_folder(self):
        older = self.older_release(**{"robot.py": "# the sample as it was\n"})
        self.copy_sample(self.robots / "Mecanum", **{"robot.py": "# the sample as it was\n"})

        output = io.StringIO()
        with redirect_stdout(output):
            self.assertEqual(
                main([str(self.robots), str(self.backups), "--released-with", str(older)]), 0
            )
        self.assertEqual(len(output.getvalue().splitlines()), 1)

    def test_installer_updates_the_samples_before_the_new_release_starts(self):
        script = INSTALLER.read_text(encoding="utf-8")
        command = '-m motion_module.shipped_samples \\\n    "$ROBOT_DIR" "$PROJECT_DIR/backups"'

        self.assertIn(command, script)
        # The robot folders exist by then, the retired-wiring move can still
        # correct a folder this step left alone, and the service has not yet
        # restarted on the new release.
        self.assertLess(script.index('say "Created robot project'), script.index(command))
        self.assertLess(script.index(command), script.index("-m motion_module.retired_wiring"))
        self.assertLess(
            script.index(command), script.index("if ! sudo systemctl restart motionmodule.service;")
        )

    def test_the_install_passes_the_samples_of_the_release_it_replaces(self):
        script = INSTALLER.read_text(encoding="utf-8")

        self.assertIn('released_with=(--released-with "$(readlink -f "$CURRENT_LINK")/examples")', script)
        self.assertIn('"${released_with[@]}"', script)


if __name__ == "__main__":
    unittest.main()
