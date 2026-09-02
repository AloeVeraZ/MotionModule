import io
import tarfile
import tempfile
import unittest
from pathlib import Path

from motion_module.deploy import deploy_archive, deploy_project_files
from motion_module.errors import MotionModuleError


def write_archive(path: Path, files: dict[str, str]) -> None:
    with tarfile.open(path, mode="w:gz") as archive:
        for name, content in files.items():
            encoded = content.encode("utf-8")
            member = tarfile.TarInfo(name)
            member.size = len(encoded)
            member.mode = 0o644
            archive.addfile(member, io.BytesIO(encoded))


VALID_HARDWARE = """HARDWARE = {
    "module": {"pwm_hz": 1000, "deadtime_ms": 2, "watchdog_ms": 500},
    "motors": {1: {"name": "driver1_a", "forward_gpio": 4, "reverse_gpio": 17, "inverted": False}},
    "servos": {"enabled": True, "i2c_bus": 1, "frequency_hz": 50, "addresses": [0x40], "minimum_pulse_us": 500, "maximum_pulse_us": 2500},
}
"""


class DeployTests(unittest.TestCase):
    def test_valid_project_replaces_target_and_keeps_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            robots = root / "robots"
            old = robots / "MyRobot"
            old.mkdir(parents=True)
            (old / "robot.py").write_text("OLD = True\n", encoding="utf-8")
            archive = root / "upload.tar.gz"
            write_archive(
                archive,
                {
                    "robot.py": "def create_drive(module):\n    return module\n",
                    "drive.py": "SPEED = 0.25\n",
                },
            )

            result = deploy_archive(archive, robots, root / "backups", "MyRobot")

            self.assertIn("create_drive", (robots / "MyRobot" / "robot.py").read_text())
            backup = Path(result["backup"])
            self.assertTrue(backup.is_dir())
            self.assertIn("OLD", (backup / "robot.py").read_text())

    def test_unsafe_archive_path_is_rejected_without_changing_project(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            robots = root / "robots"
            target = robots / "SafeRobot"
            target.mkdir(parents=True)
            (target / "robot.py").write_text("SAFE = True\n", encoding="utf-8")
            archive = root / "unsafe.tar.gz"
            write_archive(archive, {"robot.py": "SAFE = False\n", "../outside.py": "BAD = True\n"})

            with self.assertRaisesRegex(MotionModuleError, "Unsafe path"):
                deploy_archive(archive, robots, root / "backups", "SafeRobot")

            self.assertIn("SAFE = True", (target / "robot.py").read_text())
            self.assertFalse((root / "outside.py").exists())

    def test_python_syntax_failure_does_not_replace_running_project(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            robots = root / "robots"
            target = robots / "MyRobot"
            target.mkdir(parents=True)
            (target / "robot.py").write_text("WORKS = True\n", encoding="utf-8")
            archive = root / "broken.tar.gz"
            write_archive(archive, {"robot.py": "def broken(:\n"})

            with self.assertRaisesRegex(MotionModuleError, "Python check failed"):
                deploy_archive(archive, robots, root / "backups", "MyRobot")

            self.assertIn("WORKS", (target / "robot.py").read_text())

    def test_browser_folder_deployment_validates_and_backs_up_project(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / "robots" / "TestBot"
            target.mkdir(parents=True)
            (target / "robot.py").write_text("OLD = True\n", encoding="utf-8")
            result = deploy_project_files(
                [
                    ("TestBot/robot.py", b"def create_drive(module):\n    return module\n"),
                    ("TestBot/hardware.py", VALID_HARDWARE.encode()),
                    ("TestBot/drive.py", b"MAX_SPEED = 0.4\n"),
                ],
                root / "robots",
                root / "backups",
            )
            self.assertEqual(result["name"], "TestBot")
            self.assertEqual(result["files"], 3)
            self.assertTrue(Path(result["backup"]).is_dir())
            self.assertIn("create_drive", (target / "robot.py").read_text())

    def test_browser_folder_requires_hardware_and_data_only_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(MotionModuleError, "hardware.py"):
                deploy_project_files(
                    [("BadBot/robot.py", b"def create_drive(module):\n    return module\n")],
                    root / "robots",
                    root / "backups",
                )
            with self.assertRaisesRegex(MotionModuleError, "literal"):
                deploy_project_files(
                    [
                        ("BadBot/robot.py", b"def create_drive(module):\n    return module\n"),
                        ("BadBot/hardware.py", b"HARDWARE = dict()\n"),
                    ],
                    root / "robots",
                    root / "backups",
                )

    def test_browser_folder_rejects_non_source_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(MotionModuleError, "not Python"):
                deploy_project_files(
                    [
                        ("TestBot/robot.py", b"def create_drive(module):\n    return module\n"),
                        ("TestBot/hardware.py", VALID_HARDWARE.encode()),
                        ("TestBot/secret.bin", b"binary"),
                    ],
                    root / "robots",
                    root / "backups",
                )

    def test_browser_deploy_requires_one_named_folder_root(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaisesRegex(MotionModuleError, "folder, not individual"):
                deploy_project_files(
                    [
                        ("robot.py", b"def create_drive(module):\n    return module\n"),
                        ("hardware.py", VALID_HARDWARE.encode()),
                    ],
                    root / "robots",
                    root / "backups",
                    "TestBot",
                )
            with self.assertRaisesRegex(MotionModuleError, "must match"):
                deploy_project_files(
                    [
                        ("TestBot/robot.py", b"def create_drive(module):\n    return module\n"),
                        ("TestBot/hardware.py", VALID_HARDWARE.encode()),
                    ],
                    root / "robots",
                    root / "backups",
                    "AnotherName",
                )


if __name__ == "__main__":
    unittest.main()
