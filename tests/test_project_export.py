import io
import os
import stat
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from motion_module.project_export import project_archive
from motion_module.errors import MotionModuleError


class ProjectExportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.project = Path(self.temp.name) / 'MyRobot'
        self.project.mkdir()
        (self.project / 'robot.py').write_bytes(b'# robot\r\n')

    def test_archive_preserves_code_and_calibration_but_excludes_runtime_and_dependencies(self):
        saved = {'hardware.py': b'# custom map', '.imu-level.json': b'{"pitch": 0.2}', 'data/offset.bin': b'\x00\xff'}
        excluded = ['.git/config', '.venv/module.py', '__pycache__/robot.pyc', 'nested/stale.pyc', 'node_modules/pkg/index.js']
        for name, data in [*saved.items(), *((name, b'cache') for name in excluded)]:
            target = self.project / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        pipe = self.project / '.lgd-nfy0'
        pipe.write_bytes(b'pipe placeholder')
        original_lstat = Path.lstat
        with patch.object(Path, 'lstat', lambda p: SimpleNamespace(st_mode=stat.S_IFIFO) if p == pipe else original_lstat(p)):
            with zipfile.ZipFile(project_archive(self.project)) as archive:
                self.assertEqual(set(archive.namelist()), {'MyRobot/robot.py', *(f'MyRobot/{name}' for name in saved)})
                self.assertEqual(archive.read('MyRobot/robot.py'), b'# robot\r\n')
                for name, data in saved.items():
                    self.assertEqual(archive.read(f'MyRobot/{name}'), data)
                    self.assertEqual((self.project / name).read_bytes(), data)
        self.assertTrue(pipe.exists())

    def test_limits_fail_instead_of_returning_a_partial_backup(self):
        with patch('motion_module.project_export.MAX_EXPORT_BYTES', 2):
            with self.assertRaisesRegex(MotionModuleError, '32 MiB'):
                project_archive(self.project)
        with patch('motion_module.project_export.MAX_EXPORT_FILES', 0):
            with self.assertRaisesRegex(MotionModuleError, '2,000'):
                project_archive(self.project)
        self.assertEqual((self.project / 'robot.py').read_bytes(), b'# robot\r\n')

    def test_unreadable_files_are_errors_instead_of_silent_data_loss(self):
        with patch('motion_module.project_export.os.open', side_effect=PermissionError('unreadable')):
            with self.assertRaises(PermissionError):
                project_archive(self.project)

    @unittest.skipUnless(hasattr(os, 'mkfifo'), 'Requires Unix pipes and links')
    def test_real_fifo_and_links_never_export_external_data(self):
        outside = self.project.parent / 'secret.txt'
        outside.write_text('private data')
        (self.project / 'external.txt').symlink_to(outside)
        (self.project / 'linked-folder').symlink_to(self.project.parent, target_is_directory=True)
        os.mkfifo(self.project / '.lgd-nfy0')
        with zipfile.ZipFile(project_archive(self.project)) as archive:
            self.assertEqual(archive.namelist(), ['MyRobot/robot.py'])


class DownloadAPITests(unittest.TestCase):
    def test_project_download_requires_session_and_works_in_recovery(self):
        from motion_module.config import default_config
        from motion_module.controller import MotionModule
        from motion_module.dashboard import create_app
        from motion_module.gpio import MockGPIO
        with tempfile.TemporaryDirectory() as folder:
            project = Path(folder) / 'MyRobot'
            project.mkdir()
            (project / 'robot.py').write_bytes(b'# broken project kept exactly')
            with MotionModule(default_config(), gpio=MockGPIO()) as module:
                app = create_app(module, project_path=project / 'robot.py', recovery_error='Cannot import owner code')
                client = app.test_client()
                self.assertEqual(client.get('/api/projects/download').status_code, 403)
                reply = client.get('/api/projects/download', headers={'X-MotionModule-Token': app.config['DASHBOARD_TOKEN']})
                self.assertEqual(reply.status_code, 200)
                self.assertEqual(reply.headers['Cache-Control'], 'no-store')
                with zipfile.ZipFile(io.BytesIO(reply.data)) as archive:
                    self.assertEqual(archive.read('MyRobot/robot.py'), b'# broken project kept exactly')

    def test_report_identifies_both_variants_without_source_logs_or_credentials(self):
        from motion_module.config import DEFAULT_HARDWARE_PATH, MINI_HARDWARE_PATH, load_hardware_file
        from motion_module.controller import MotionModule
        from motion_module.dashboard import create_app
        from motion_module.gpio import MockGPIO
        for path, count in ((DEFAULT_HARDWARE_PATH, 8), (MINI_HARDWARE_PATH, 4)):
            with MotionModule(load_hardware_file(path), gpio=MockGPIO()) as module:
                app = create_app(module, project_name='OwnerRobot', recovery_error='PRIVATE_SOURCE_LINE in PRIVATE_USER/path')
                client = app.test_client()
                self.assertEqual(client.get('/api/diagnostics/download').status_code, 403)
                module.motor(1).set(0.2)
                with patch('motion_module.dashboard.system_snapshot', return_value={
                    'hostname': 'PRIVATE_HOST', 'username': 'PRIVATE_USER', 'password': 'PRIVATE_PASSWORD',
                    'load_1m': 0.2,
                }):
                    reply = client.get('/api/diagnostics/download', headers={'X-MotionModule-Token': app.config['DASHBOARD_TOKEN']})
                self.assertEqual(reply.status_code, 200)
                self.assertEqual(reply.headers['Cache-Control'], 'no-store')
                report = reply.get_json()
                self.assertEqual(report['module']['motor_ports'], count)
                self.assertEqual(len(report['wiring']['motors']), count)
                self.assertEqual(report['active_project'], 'OwnerRobot')
                self.assertTrue(report['recovery']['active'])
                self.assertEqual(module.motor(1).value, 0.2)
                self.assertNotIn(b'PRIVATE_', reply.data)
                self.assertNotIn('logs', report)
                self.assertNotIn('source', report)
