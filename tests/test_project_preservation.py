"""Runtime upgrades snapshot every project without replacing the live code."""
import json
import tempfile
import unittest
from pathlib import Path

from motion_module.project_preservation import snapshot_projects


class ProjectPreservationTests(unittest.TestCase):
    def test_snapshot_keeps_all_code_and_data_including_unedited_samples(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            robots = workspace / 'robots'
            files = {'robot.py': b'# owner code\r\n', 'hardware.py': b'# owner map\n',
                     'autonomous.py': b'# owner routine', 'data/calibration.bin': b'\x00\xff'}
            for name in ('Mecanum', 'MecanumMini', 'MyRobot'):
                for relative, data in files.items():
                    target = robots / name / relative
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_bytes(data)
            legacy = workspace / 'OldRobot'
            legacy.mkdir()
            (legacy / 'robot.py').write_bytes(b'# legacy')
            destination = snapshot_projects(robots, workspace / 'backups', 'release-1', legacy_workspace=workspace)
            for name in ('Mecanum', 'MecanumMini', 'MyRobot'):
                for relative, data in files.items():
                    self.assertEqual((robots / name / relative).read_bytes(), data)
                    self.assertEqual((destination / 'robots' / name / relative).read_bytes(), data)
            self.assertEqual((destination / 'legacy/OldRobot/robot.py').read_bytes(), b'# legacy')
            self.assertEqual(len(json.loads((destination / 'snapshot.json').read_text())['projects']), 4)
            # An existing backup is never overwritten, even after live code changes.
            (robots / 'MyRobot/robot.py').write_bytes(b'# newer owner code')
            with self.assertRaises(FileExistsError):
                snapshot_projects(robots, workspace / 'backups', 'release-1')
            self.assertEqual((destination / 'robots/MyRobot/robot.py').read_bytes(), files['robot.py'])

    def test_empty_workspace_creates_no_backup_and_rejects_unsafe_destinations(self):
        with tempfile.TemporaryDirectory() as folder:
            robots = Path(folder) / 'robots'
            self.assertIsNone(snapshot_projects(robots, Path(folder) / 'backups', 'fresh'))
            with self.assertRaises(ValueError):
                snapshot_projects(robots, robots / 'backups', 'nested')
            with self.assertRaises(ValueError):
                snapshot_projects(robots, Path(folder) / 'backups', '../outside')

    def test_branch_handoff_snapshots_using_current_runtime_before_target_installer(self):
        script = (Path(__file__).resolve().parents[1] / 'installer/motionmodule').read_text(encoding='utf-8')
        command = '"$(runtime_python)" -m motion_module.project_preservation'
        self.assertIn(command, script)
        self.assertLess(script.index(command), script.index('"$bootstrap" | bash'))
