"""Runtime upgrades snapshot every project without replacing the live code."""
import json
import os
import socket
import stat
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from motion_module.project_preservation import snapshot_projects


class ProjectPreservationTests(unittest.TestCase):
    def test_runtime_objects_are_skipped_recursively_without_name_based_exclusions(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            project = workspace / 'robots/Mecanum'
            project.mkdir(parents=True)
            files = {'robot.py': b'# owner code', 'nested/.lgd-nfy0': b'runtime FIFO',
                     'runtime.sock': b'runtime socket', 'device': b'character device',
                     'disk': b'block device', '.lgd-nfy-real-data': b'keep this file'}
            for relative, data in files.items():
                target = project / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            runtime_modes = {project / 'nested/.lgd-nfy0': stat.S_IFIFO,
                             project / 'runtime.sock': stat.S_IFSOCK,
                             project / 'device': stat.S_IFCHR, project / 'disk': stat.S_IFBLK}
            original_lstat = Path.lstat

            def lstat(path):
                if path in runtime_modes:
                    return SimpleNamespace(st_mode=runtime_modes[path])
                return original_lstat(path)

            with patch.object(Path, 'lstat', lstat):
                destination = snapshot_projects(workspace / 'robots', workspace / 'backups', 'release')
            copied = destination / 'robots/Mecanum'
            self.assertEqual((copied / 'robot.py').read_bytes(), files['robot.py'])
            self.assertEqual((copied / '.lgd-nfy-real-data').read_bytes(), files['.lgd-nfy-real-data'])
            for path in runtime_modes:
                self.assertFalse((copied / path.relative_to(project)).exists())
                self.assertTrue(path.exists(), 'The live runtime object is never deleted')
            manifest = json.loads((destination / 'snapshot.json').read_text())
            self.assertEqual(set(manifest['skipped_runtime_objects']), {str(p) for p in runtime_modes})

    @unittest.skipUnless(hasattr(os, 'mkfifo') and hasattr(socket, 'AF_UNIX'), 'Requires Unix filesystem objects')
    def test_live_gpio_fifo_and_unix_socket_do_not_block_code_backup(self):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            project = workspace / 'robots/Mecanum'
            project.mkdir(parents=True)
            (project / 'robot.py').write_bytes(b'# owner code')
            fifo = project / '.lgd-nfy0'
            os.mkfifo(fifo)
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as listener:
                listener.bind(str(project / 'runtime.sock'))
                destination = snapshot_projects(workspace / 'robots', workspace / 'backups', 'release')
                self.assertEqual((destination / 'robots/Mecanum/robot.py').read_bytes(), b'# owner code')
                self.assertFalse((destination / 'robots/Mecanum/.lgd-nfy0').exists())
                self.assertFalse((destination / 'robots/Mecanum/runtime.sock').exists())
                self.assertTrue(stat.S_ISFIFO(fifo.stat().st_mode))

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

    def test_installer_never_refreshes_existing_robot_code_or_inserts_hardware_files(self):
        script = (Path(__file__).resolve().parents[1] / 'installer/install.sh').read_text(encoding='utf-8')
        self.assertNotIn('-m motion_module.shipped_samples', script)
        self.assertNotIn('-m motion_module.mecanum_hardware', script)
        self.assertLess(script.index('-m motion_module.project_preservation'),
                        script.index('-m motion_module.retired_wiring'))
