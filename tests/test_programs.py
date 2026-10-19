import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from motion_module.config import default_config
from motion_module.controller import MotionModule
from motion_module.dashboard import create_app, load_drive, load_autonomous_routine
from motion_module.deploy import _check_python, deploy_project_files
from motion_module.errors import MotionModuleError
from motion_module.gpio import MockGPIO
from motion_module.programs import default_program, initialize_library, list_programs, resolve_program, workspace_for


ROBOT = b'def create_drive(module):\n    return module\n'
AUTO = b'def run(module, stop):\n    pass\n'


class ProgramTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.workspace = Path(temporary.name)
        self.robots = self.workspace / "robots"
        self.tele = self.robots / "teleop" / "Mecanum"
        self.auto = self.robots / "autonomous" / "Mecanum"
        for folder in (self.tele, self.auto):
            folder.mkdir(parents=True)
            (folder / "robot.py").write_bytes(ROBOT)
        (self.auto / "autonomous.py").write_bytes(AUTO)

    def test_modes_filter_programs_and_default_to_teleop(self):
        self.assertEqual([row["id"] for row in list_programs(self.robots, "teleop")], ["teleop/Mecanum"])
        self.assertEqual([row["id"] for row in list_programs(self.robots, "autonomous")], ["autonomous/Mecanum"])
        self.assertEqual(default_program(self.robots), self.tele)
        self.assertEqual(workspace_for(self.tele / "robot.py"), self.workspace)

    def test_selection_rejects_other_modes_traversal_and_unknown_folders(self):
        for identifier in ("../outside", str(self.auto), "autonomous/Mecanum", "MyRobot/Missing_tele"):
            with self.subTest(identifier=identifier), self.assertRaises(MotionModuleError):
                resolve_program(self.robots, identifier, "teleop")
        with self.assertRaises(MotionModuleError):
            list_programs(self.robots, "invalid")

    def test_only_immediate_mode_program_folders_are_listed(self):
        legacy = self.robots / "Legacy"
        legacy.mkdir()
        (legacy / "robot.py").write_bytes(ROBOT)
        (legacy / "autonomous.py").write_bytes(AUTO)
        (self.robots / "autonomous" / "loose.py").write_bytes(AUTO)
        nested = self.robots / "teleop" / "wrapper" / "Nested"
        nested.mkdir(parents=True)
        (nested / "robot.py").write_bytes(ROBOT)
        self.assertEqual([row["id"] for row in list_programs(self.robots, "teleop")], ["teleop/Mecanum"])
        self.assertEqual([row["id"] for row in list_programs(self.robots, "autonomous")], ["autonomous/Mecanum"])
        with self.assertRaises(MotionModuleError):
            resolve_program(self.robots, "Legacy", "teleop")

    def test_selection_reloads_program_without_restarting_dashboard(self):
        (self.auto / "robot.py").write_bytes(AUTO)
        module = MotionModule(default_config(), gpio=MockGPIO())
        self.addCleanup(module.close)
        replacements = []

        def factory(_folder):
            replacement = MotionModule(default_config(), gpio=MockGPIO())
            replacements.append(replacement)
            self.addCleanup(replacement.close)
            return replacement

        app = create_app(module, workspace_directory=self.workspace, project_path=self.tele / "robot.py",
                         module_factory=factory)
        client = app.test_client()
        headers = {"X-MotionModule-Token": app.config["DASHBOARD_TOKEN"]}
        with patch("motion_module.dashboard.activate_project"):
            response = client.post("/api/programs/select", headers=headers,
                                   json={"program": "autonomous/Mecanum", "mode": "autonomous"})
        self.assertEqual(response.status_code, 200, response.get_json())
        self.assertFalse(response.get_json().get("restarting", False))
        self.assertEqual(client.get("/api/programs?mode=autonomous").get_json()["active"], "autonomous/Mecanum")
        self.assertIs(app.config["ACTIVE_MODULE"], replacements[-1])
        self.assertFalse(any(module.motor_values.values()))

    def test_failed_live_switch_restores_previous_program_disabled(self):
        (self.auto / "robot.py").write_bytes(AUTO)
        module = MotionModule(default_config(), gpio=MockGPIO())
        self.addCleanup(module.close)
        replacements = []

        def factory(_folder):
            replacement = MotionModule(default_config(), gpio=MockGPIO())
            replacements.append(replacement)
            self.addCleanup(replacement.close)
            return replacement

        app = create_app(module, workspace_directory=self.workspace, project_path=self.auto / "robot.py",
                         module_factory=factory)
        client = app.test_client()
        headers = {"X-MotionModule-Token": app.config["DASHBOARD_TOKEN"]}
        response = client.post("/api/programs/select", headers=headers,
                               json={"program": "teleop/Mecanum", "mode": "teleop"})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(client.get("/api/programs?mode=autonomous").get_json()["active"], "autonomous/Mecanum")
        self.assertIs(app.config["ACTIVE_MODULE"], replacements[-1])
        self.assertFalse(app.config["RECOVERY"]["active"])

    def test_default_install_has_mecanum_teleop_and_gyro_autonomous_on_both_module_types(self):
        import os
        sample = Path(__file__).resolve().parents[1] / "examples" / "Mecanum"
        for variant in ("standard", "mini"):
            library = self.workspace / variant / "robots"
            target = initialize_library(library, self.workspace / variant / "backups", sample)
            self.assertEqual([row["name"] for row in list_programs(library, "teleop")], ["Mecanum"])
            self.assertEqual([row["id"] for row in list_programs(library, "autonomous")],
                             ["autonomous/Mecanum"])
            auto_target = library / "autonomous" / "Mecanum"
            _check_python(target, strict=True)
            _check_python(auto_target, strict=True, mode="autonomous")
            from motion_module.config import load_config
            with patch.dict(os.environ, {"MOTIONMODULE_VARIANT": variant}):
                with MotionModule(load_config(project=target), gpio=MockGPIO()) as module:
                    drive = load_drive(module, target / "robot.py")
                    drive.drive(1, 0, 0)
                    self.assertTrue(any(module.motor_values.values()))
                    self.assertTrue(all(power == 0 for channel, power in module.motor_values.items() if channel > 4))
                    self.assertIsNone(load_autonomous_routine(module, drive, target / "robot.py"))
                with MotionModule(load_config(project=auto_target), gpio=MockGPIO()) as module:
                    auto_drive = load_drive(module, auto_target / "robot.py")
                    routine = load_autonomous_routine(module, auto_drive, auto_target / "robot.py")
                    self.assertEqual(routine.progress["steps"],
                                     [["turn", 90], ["turn", 180], ["turn", 270], ["turn", 360]])
                    self.assertFalse(routine.ready())
                    self.assertFalse(any(module.motor_values.values()))

    def test_legacy_mecanum_class_is_valid_and_loads_without_a_factory(self):
        (self.tele / "robot.py").write_text("class MecanumDrive:\n    def __init__(self, module): pass\n    def drive(self, *args): return {}\n    def stop(self): pass\n", encoding="utf-8")
        _check_python(self.tele, strict=True)
        drive = load_drive(object(), self.tele / "robot.py")
        self.assertEqual(drive.drive(1, 0, 0), {})

    def test_autonomous_robot_py_runs_without_a_teleop_factory(self):
        (self.auto / "autonomous.py").unlink()
        (self.auto / "robot.py").write_text("def run(module, stop):\n    module.called = True\n", encoding="utf-8")
        _check_python(self.auto, strict=True)
        module = Mock()
        drive = load_drive(module, self.auto / "robot.py")
        routine = load_autonomous_routine(module, drive, self.auto / "robot.py")
        routine.run(Mock())
        self.assertIs(module.called, True)

    def test_retired_unmodified_bundles_are_kept_in_backups_and_removed_from_picker(self):
        import shutil
        sample = Path(__file__).resolve().parents[1] / "examples" / "Mecanum"
        library = self.workspace / "old" / "robots"
        previous = self.workspace / "old" / "examples"
        for name in ("Mecanum", "MecanumMini"):
            for base in (library, previous):
                folder = base / name
                folder.mkdir(parents=True)
                (folder / "robot.py").write_bytes(ROBOT)
                (folder / "autonomous.py").write_bytes(AUTO)
        backups = self.workspace / "old" / "backups"
        initialize_library(library, backups, sample, previous)
        self.assertEqual([row["id"] for row in list_programs(library, "teleop")], ["teleop/Mecanum"])
        self.assertEqual([row["id"] for row in list_programs(library, "autonomous")],
                         ["autonomous/Mecanum"])
        self.assertEqual(len(list(backups.iterdir())), 2)

    def test_install_preserves_an_edited_autonomous_program(self):
        sample = Path(__file__).resolve().parents[1] / "examples" / "Mecanum"
        auto = self.robots / "autonomous" / "Mecanum"
        (auto / "robot.py").write_text("def run(module, stop):\n    pass\n", encoding="utf-8")
        initialize_library(self.robots, self.workspace / "backups", sample)
        self.assertEqual((auto / "robot.py").read_text(encoding="utf-8"),
                         "def run(module, stop):\n    pass\n")

    def test_mode_groups_keep_same_named_programs_separate(self):
        tele = list_programs(self.robots, "teleop")
        auto = list_programs(self.robots, "autonomous")
        self.assertEqual(tele[0]["name"], auto[0]["name"])
        self.assertNotEqual(tele[0]["id"], auto[0]["id"])
        self.assertEqual(resolve_program(self.robots, tele[0]["id"], "teleop"), self.tele)
        self.assertEqual(resolve_program(self.robots, auto[0]["id"], "autonomous"), self.auto)

    def test_upload_accepts_nested_programs_and_validates_autonomous(self):
        result = deploy_project_files([
            ("Uploaded/Drive_tele/robot.py", ROBOT),
            ("Uploaded/Square_auto/robot.py", ROBOT),
            ("Uploaded/Square_auto/autonomous.py", AUTO),
        ], self.robots, self.workspace / "backups")
        self.assertEqual(default_program(Path(result["target"])).name, "Drive_tele")
        (self.auto / "autonomous.py").unlink()
        with self.assertRaisesRegex(MotionModuleError, "Autonomous robot.py"):
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
        self.assertEqual(status["active"], "teleop/Mecanum")
        self.assertEqual(status["programs"][0]["id"], "autonomous/Mecanum")
        self.assertEqual(client.post("/api/programs/select", json={}).status_code, 403)
        with patch("motion_module.dashboard.activate_project") as activate:
            response = client.post("/api/programs/select", headers=headers,
                                   json={"program": "autonomous/Mecanum", "mode": "autonomous"})
        self.assertEqual(response.status_code, 202, response.get_json())
        activate.assert_called_once_with(self.auto, self.workspace / "active")
        self.assertTrue(all(power == 0 for power in module.motor_values.values()))
        self.assertEqual(client.post("/api/drive", headers=headers, json={"sequence": 1, "forward": 1}).status_code, 423)


if __name__ == "__main__":
    unittest.main()
