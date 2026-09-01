import io
import tarfile
import tempfile
import unittest
from pathlib import Path

from motion_module.deploy import deploy_archive
from motion_module.errors import MotionModuleError


def write_archive(path: Path, files: dict[str, str]) -> None:
    with tarfile.open(path, mode="w:gz") as archive:
        for name, content in files.items():
            encoded = content.encode("utf-8")
            member = tarfile.TarInfo(name)
            member.size = len(encoded)
            member.mode = 0o644
            archive.addfile(member, io.BytesIO(encoded))


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


if __name__ == "__main__":
    unittest.main()
