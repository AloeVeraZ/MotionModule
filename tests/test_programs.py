import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from motion_module.config import default_config
from motion_module.controller import MotionModule
from motion_module.dashboard import create_app
from motion_module.deploy import _check_python, deploy_project_files
from motion_module.errors import MotionModuleError
from motion_module.gpio import MockGPIO
from motion_module.programs import default_program, list_programs, resolve_program, workspace_for


ROBOT = b'def create_drive(module):\n    return module\n'
AUTO = b'def run(module, stop):\n    pass\n'


class ProgramTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.workspace = Path(temporary.name)
        self.robots = self.workspace / "robots"
        self.tele = self.robots / "MyRobot" / "Drive_tele"
        self.auto = self.robots / "MyRobot" / "Square_auto"
        for folder in (self.tele, self.auto):
            folder.mkdir(parents=True)
            (folder / "robot.py").write_bytes(ROBOT)
        (self.auto / "autonomous.py").write_bytes(AUTO)

    def test_modes_filter_programs_and_default_to_teleop(self):
        self.assertEqual([row["id"] for row in list_programs(self.robots, "teleop")], ["MyRobot/Drive_tele"])
        self.assertEqual([row["id"] for row in list_programs(self.robots, "autonomous")], ["MyRobot/Square_auto"])
        self.assertEqual(default_program(self.tele.parent), self.tele)
        self.assertEqual(workspace_for(self.tele / "robot.py"), self.workspace)

    def test_selection_rejects_other_modes_traversal_and_unknown_folders(self):
        for identifier in ("../outside", str(self.auto), "MyRobot/Square_auto", "MyRobot/Missing_tele"):
            with self.subTest(identifier=identifier), self.assertRaises(MotionModuleError):
                resolve_program(self.robots, identifier, "teleop")
        with self.assertRaises(MotionModuleError):
            list_programs(self.robots, "invalid")

    def test_flat_projects_remain_available_for_the_modes_they_support(self):
        legacy = self.robots / "Legacy"
        legacy.mkdir()
        (legacy / "robot.py").write_bytes(ROBOT)
        self.assertIn("Legacy", [row["id"] for row in list_programs(self.robots, "teleop")])
        self.assertNotIn("Legacy", [row["id"] for row in list_programs(self.robots, "autonomous")])
        (legacy / "autonomous.py").write_bytes(AUTO)
        self.assertIn("Legacy", [row["id"] for row in list_programs(self.robots, "autonomous")])

    def test_sample_programs_have_their_own_files_and_the_locked_hardware(self):
        sample = Path(__file__).resolve().parents[1] / "examples" / "Mecanum"
        for name in ("Drive_tele", "Heading_auto"):
            folder = sample / name
            for filename in ("robot.py", "hardware.py", "dashboard.py", "sensors.py", "test.py"):
                self.assertTrue((folder / filename).is_file())
            self.assertEqual((folder / "hardware.py").read_bytes(), (sample / "hardware.py").read_bytes())
            _check_python(folder, strict=True)

    def test_upload_accepts_nested_programs_and_validates_autonomous(self):
        result = deploy_project_files([
            ("Uploaded/Drive_tele/robot.py", ROBOT),
            ("Uploaded/Square_auto/robot.py", ROBOT),
            ("Uploaded/Square_auto/autonomous.py", AUTO),
        ], self.robots, self.workspace / "backups")
        self.assertEqual(default_program(Path(result["target"])).name, "Drive_tele")
        (self.auto / "autonomous.py").unlink()
        with self.assertRaisesRegex(MotionModuleError, "must contain autonomous.py"):
            _check_python(self.auto, strict=True)

    def test_selection_stops_blocks_commands_and_restarts_without_executing_new_code(self):
        module = MotionModule(default_config(), gpio=MockGPIO())
        self.addCleanup(module.close)
        restart = Mock()
        app = create_app(module, workspace_directory=self.workspace, restart_callback=restart,
                         project_path=self.tele / "robot.py")
        client = app.test_client()
        headers = {"X-MotionModule-Token": app.config["DASHBOARD_TOKEN"]}
        status = client.get("/api/programs?mode=autonomous").get_json()
        self.assertEqual(status["active"], "MyRobot/Drive_tele")
        self.assertEqual(status["programs"][0]["id"], "MyRobot/Square_auto")
        self.assertEqual(client.post("/api/programs/select", json={}).status_code, 403)
        with patch("motion_module.dashboard.activate_project") as activate:
            response = client.post("/api/programs/select", headers=headers,
                                   json={"program": "MyRobot/Square_auto", "mode": "autonomous"})
        self.assertEqual(response.status_code, 202, response.get_json())
        activate.assert_called_once_with(self.auto, self.workspace / "active")
        self.assertTrue(all(power == 0 for power in module.motor_values.values()))
        self.assertEqual(client.post("/api/drive", headers=headers, json={"sequence": 1, "forward": 1}).status_code, 423)


if __name__ == "__main__":
    unittest.main()
