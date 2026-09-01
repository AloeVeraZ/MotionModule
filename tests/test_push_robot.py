import tarfile
import tempfile
import unittest
from pathlib import Path
from unittest.mock import ANY, patch

from tools.push_robot import create_archive, push_project


class PushRobotTests(unittest.TestCase):
    def test_archive_contains_code_and_skips_development_caches(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            project = root / "MyRobot"
            project.mkdir()
            (project / "robot.py").write_text("READY = True\n", encoding="utf-8")
            (project / "drive.py").write_text("SPEED = 1\n", encoding="utf-8")
            cache = project / "__pycache__"
            cache.mkdir()
            (cache / "robot.pyc").write_bytes(b"cache")
            archive = root / "project.tar.gz"

            create_archive(project, archive)

            with tarfile.open(archive, mode="r:gz") as uploaded:
                self.assertEqual(sorted(uploaded.getnames()), ["drive.py", "robot.py"])

    @patch("tools.push_robot.shutil.which", return_value="available")
    @patch("tools.push_robot._run")
    def test_push_uses_ssh_then_remote_deploy(self, run, _which):
        with tempfile.TemporaryDirectory() as directory:
            project = Path(directory) / "MyRobot"
            project.mkdir()
            (project / "robot.py").write_text("READY = True\n", encoding="utf-8")

            push_project(project, "MyRobot", "angelo@motionmodule.local")

        self.assertEqual(run.call_count, 3)
        self.assertEqual(run.call_args_list[0].args[0], [
            "ssh", "angelo@motionmodule.local", "mkdir -p MotionModule/.uploads"
        ])
        self.assertEqual(run.call_args_list[1].args[0][0], "scp")
        self.assertEqual(
            run.call_args_list[2].args[0],
            [
                "ssh",
                "angelo@motionmodule.local",
                ANY,
            ],
        )
        self.assertIn("motionmodule deploy MyRobot", run.call_args_list[2].args[0][2])


if __name__ == "__main__":
    unittest.main()
