"""Mini shares the runtime while limiting motors and keeping servos and IMU."""
import os
import tempfile
import unittest
from dataclasses import replace
from pathlib import Path
from unittest.mock import patch

from motion_module.config import (DEFAULT_HARDWARE_PATH, MINI_HARDWARE_PATH,
                                  hardware_source, load_config, load_hardware_file)
from motion_module.controller import MotionModule
from motion_module.dashboard import IdleDrive, create_app, load_drive
from motion_module.errors import ConfigurationError
from motion_module.gpio import MockGPIO
from motion_module.hardware_guide import hardware_guide
from motion_module.pinout import header_rows

ROOT = Path(__file__).resolve().parents[1]


class MiniTests(unittest.TestCase):
    def setUp(self):
        self.standard = load_hardware_file(DEFAULT_HARDWARE_PATH)
        self.mini = load_hardware_file(MINI_HARDWARE_PATH)

    def test_mini_keeps_the_locked_first_four_motor_and_all_servo_connections(self):
        self.assertEqual(self.mini.motors, self.standard.motors[:4])
        self.assertEqual(self.mini.servos, self.standard.servos)
        self.assertEqual(self.mini.motor_capacity, 4)
        self.assertEqual(self.standard.motor_capacity, 8)
        self.assertEqual(self.mini, load_hardware_file(ROOT / 'MotionModuleMini/hardware.py'))
        self.assertEqual(self.standard, load_hardware_file(ROOT / 'MotionModule/hardware.py'))

    def test_mini_export_preserves_variant_and_rejects_fifth_motor(self):
        with tempfile.TemporaryDirectory() as folder:
            config = Path(folder) / 'hardware.py'
            config.write_text(hardware_source(self.mini), encoding='utf-8')
            self.assertEqual(load_hardware_file(config), self.mini)
            config.write_text(hardware_source(replace(self.standard, variant='mini')), encoding='utf-8')
            with self.assertRaisesRegex(ConfigurationError, 'channels 1-4'):
                load_hardware_file(config)

    def test_installed_limit_cannot_be_bypassed_by_a_full_project(self):
        with patch.dict(os.environ, {'MOTIONMODULE_VARIANT': 'mini'}):
            config = load_config(project=ROOT / 'examples/Mecanum')
            self.assertEqual(config.motors, load_hardware_file(ROOT / 'examples/Mecanum/hardware.py').motors[:4])
            self.assertEqual(config.motor_capacity, 4)
            config = load_config(project=ROOT / 'examples/MecanumMini')
            self.assertEqual(len(config.motors), 4)
            self.assertEqual(len(config.servos.channels), 16)

    def test_installed_variant_marker_selects_mini_fallback(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder, 'variant').write_text('mini\n', encoding='utf-8')
            with patch.dict(os.environ, {'MOTIONMODULE_CONFIG_DIR': folder}):
                with patch.dict(os.environ):
                    for key in ('MOTIONMODULE_VARIANT', 'MOTIONMODULE_CONFIG', 'MOTIONMODULE_ACTIVE_PROJECT'):
                        os.environ.pop(key, None)
                    self.assertEqual(load_config(), self.mini)

    def test_guide_has_only_two_drivers_and_preserves_servo_and_imu_reference(self):
        guide = hardware_guide(self.mini)
        self.assertEqual(guide['capacity']['motors'], 4)
        self.assertEqual({m['driver'] for m in guide['wiring']['motor_connections']}, {1, 2})
        self.assertEqual(len(guide['wiring']['servo_boards'][0]['outputs']), 16)
        parts = {p['name']: p for g in guide['parts_groups'] for p in g['items']}
        self.assertEqual(parts['GODIYMODULES dual H-bridge']['quantity'], '2')
        self.assertEqual(parts['Brushed DC motors']['quantity'], 'Up to 4')
        self.assertIn('MPU6500 gyroscope + accelerometer', parts)
        self.assertNotIn('Controller mounting CAD', parts)
        header = {p['physical']: p for p in header_rows(self.mini, imu_guide=True)}
        for pin in (13, 15, 16, 18, 21, 23, 24, 26):
            self.assertEqual(header[pin]['category'], 'unused')
        self.assertIn('MPU6500', header[11]['role'])

    def test_robot_code_is_identical_between_mecanum_samples(self):
        for file in (ROOT / 'examples/Mecanum').glob('*.py'):
            if file.name != 'hardware.py':
                self.assertEqual(file.read_bytes(), (ROOT / 'examples/MecanumMini' / file.name).read_bytes())

    def test_same_project_drives_on_both_modules_without_changing_any_files(self):
        project = ROOT / 'examples/Mecanum'
        before = {p.name: p.read_bytes() for p in project.glob('*.py')}
        powers = []
        for variant, capacity in (('mini', 4), ('standard', 8)):
            with patch.dict(os.environ, {'MOTIONMODULE_VARIANT': variant}):
                config = load_config(project=project)
                self.assertEqual(config.motor_capacity, capacity)
                module = MotionModule(config, gpio=MockGPIO())
                try:
                    drive = load_drive(module, project / 'robot.py')
                    drive.drive(0.5, 0.2, 0.1, speed=0.5)
                    powers.append({key: value for key, value in module.snapshot()['motors'].items()
                                   if key in (1, 2, 3, 4)})
                    self.assertTrue(any(powers[-1].values()))
                    module.servo(15).set_angle(90)
                    self.assertIsNotNone(drive.sensors.reading())
                    self.assertEqual(drive.controls(), [])
                    if variant == 'mini':
                        with self.assertRaises(ValueError):
                            module.motor(5)
                    drive.stop()
                finally:
                    module.close()
        self.assertEqual(powers[0], powers[1])
        self.assertEqual(before, {p.name: p.read_bytes() for p in project.glob('*.py')})

    def test_legacy_default_controls_are_hidden_but_custom_controls_still_work(self):
        class MecanumDrive(IdleDrive):
            def controls(self):
                return [{'name': name} for name in ('spin_test', 'creep', 'zero_heading', 'recalibrate_gyro')]
        module = MotionModule(self.mini, gpio=MockGPIO())
        self.addCleanup(module.close)
        drive = MecanumDrive(module)
        class Dashboard:
            def snapshot(self):
                return {'driver_bindings': {'zero_heading': 'z'},
                        'gamepad_buttons': {'left_bumper': 'recalibrate_gyro'}}
        app = create_app(module, drive, dashboard_telemetry=Dashboard())
        client = app.test_client()
        telemetry = client.get('/api/drive/telemetry').get_json()
        self.assertEqual(telemetry['control_keys'], {})
        self.assertEqual(telemetry['control_buttons'], {})
        page = client.get('/driver-station').data.decode()
        self.assertIn('Competition console', page)
        self.assertIn('data-no-controls="true" hidden', page)
        self.assertEqual(client.get('/api/drive/controls').get_json()['controls'], [])
        drive.controls = lambda: [{'name': 'intake', 'label': 'Intake', 'kind': 'hold'}]
        self.assertEqual(client.get('/api/drive/controls').get_json()['controls'][0]['name'], 'intake')

    def test_mini_diagram_has_two_drivers_and_ships_offline(self):
        svg = (ROOT / 'docs/images/motionmodule-mini-complete-wiring.svg').read_text(encoding='utf-8')
        for n in (1, 2):
            self.assertIn(f'DRIVER {n}', svg)
        for n in (3, 4):
            self.assertNotIn(f'DRIVER {n}', svg)
        self.assertIn('MPU6500', svg)
        self.assertIn('16 servo outputs', svg)
        self.assertEqual((ROOT / 'docs/images/motionmodule-mini-complete-wiring.png').read_bytes(),
                         (ROOT / 'core/motion_module/static/motionmodule-mini-complete-wiring.png').read_bytes())

    def test_mini_dashboard_has_four_outputs_matching_header_diagram_and_update_selector(self):
        module = MotionModule(self.mini, gpio=MockGPIO())
        self.addCleanup(module.close)
        class Updates:
            def snapshot(self, **kwargs):
                return {'installed': {'ref': 'testing'}, 'lines': [], 'job': {'state': 'idle'}}
            def start_update(self, ref, password=None, variant=None):
                self.selected = (ref, variant)
                return 'Started'
        updates = Updates()
        app = create_app(module, IdleDrive(module), update_checker=updates)
        client = app.test_client()
        page = client.get('/').data.decode()
        self.assertIn('MotionModule Mini</span>', page)
        self.assertIn('0 / 4</div>', page)
        self.assertIn('2 BOARDS · 4 MOTORS', page)
        self.assertIn('/static/motionmodule-mini-complete-wiring.png', page)
        config = client.get('/api/config').get_json()
        self.assertEqual(len(config['motors']), 4)
        self.assertEqual(len(config['bench_motors']), 4)
        self.assertEqual(client.get('/api/cad/motion-module.step').status_code, 404)
        self.assertEqual(len(client.get('/api/status').get_json()['robot']['motors']), 4)
        response = client.get('/static/motionmodule-mini-complete-wiring.png')
        self.assertEqual(response.status_code, 200)
        response.close()
        self.assertEqual(client.get('/api/updates').get_json()['module_variant'], 'mini')
        headers = {'X-MotionModule-Token': app.config['DASHBOARD_TOKEN']}
        reply = client.post('/api/updates', json={'ref': 'testing', 'variant': 'standard'}, headers=headers)
        self.assertEqual(reply.status_code, 202)
        self.assertEqual(updates.selected, ('testing', 'standard'))
        with self.assertRaises(ValueError):
            module.motor(5)
