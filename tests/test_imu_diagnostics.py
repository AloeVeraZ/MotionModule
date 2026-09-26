import errno
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from motion_module.diagnostics import local_imu_check
from motion_module.config import load_config
from motion_module.pinout import header_rows


class IMUDiagnosticsTests(unittest.TestCase):
    def report(self, reads):
        bus = MagicMock()
        bus.read_byte_data.side_effect = [*reads, OSError(), OSError()]
        factory = MagicMock()
        factory.return_value.__enter__.return_value = bus
        with patch('motion_module.diagnostics.find_i2c_gpio_bus', return_value=11), \
             patch.dict(sys.modules, {'smbus2': SimpleNamespace(SMBus=factory)}):
            report = local_imu_check(True)
        factory.assert_called_once_with(11)
        factory.return_value.__exit__.assert_called_once()
        self.assertTrue(all(call.args in ((0x68, 0x75), (0x69, 0x75))
                            for call in bus.read_byte_data.call_args_list))
        self.assertIn("MPU6500", report["title"])
        bus.write_byte_data.assert_not_called()
        bus.write_i2c_block_data.assert_not_called()
        return report

    def test_missing_and_wrong_chip_are_not_success(self):
        for reads in ([OSError(), OSError()], [0x12, 0x34]):
            self.assertEqual(self.report(reads)['level'], 'warn')

    def test_other_chip_identities_are_not_misreported_as_mpu6500(self):
        for identity in (0x71, 0x73, 0xA0, 0x6B):
            report = self.report([identity, OSError()])
            self.assertEqual(report['level'], 'warn')
            self.assertIn(f'0x68 returned chip ID 0x{identity:02X}', report['detail'])

    def test_mpu6500_identity_is_named_correctly_at_both_addresses(self):
        for reads, address in (([0x70], '0x68'), ([OSError(), 0x70], '0x69')):
            report = self.report(reads)
            self.assertEqual(report['level'], 'pass')
            self.assertIn(f'MPU6500 detected at {address}', report['detail'])
            self.assertIn('chip ID 0x70', report['detail'])
            self.assertNotIn('MPU9255 detected', report['detail'])

    def test_read_errors_preserve_linux_failure_details(self):
        report = self.report([
            OSError(errno.ETIMEDOUT, 'Connection timed out'),
            OSError(errno.EOPNOTSUPP, 'Operation not supported'),
        ])
        self.assertEqual(report['level'], 'warn')
        self.assertIn('0x68: [Errno', report['detail'])
        self.assertIn('Connection timed out', report['detail'])
        self.assertIn('0x69: [Errno', report['detail'])
        self.assertIn('Operation not supported', report['detail'])
        self.assertNotIn('No response', report['detail'])

    def test_wrong_chip_and_read_error_are_both_reported(self):
        report = self.report([0x12, OSError(errno.EIO, 'Input/output error')])
        self.assertIn('0x68 returned chip ID 0x12', report['detail'])
        self.assertIn('0x69: [Errno', report['detail'])
        self.assertIn('Input/output error', report['detail'])

    def test_simulation_does_not_probe(self):
        with patch('motion_module.diagnostics.find_i2c_gpio_bus') as find:
            self.assertEqual(local_imu_check(False)['level'], 'info')
            find.assert_not_called()

    def test_missing_overlay_gives_exact_setup(self):
        with patch('motion_module.diagnostics.find_i2c_gpio_bus', return_value=None):
            self.assertIn('i2c_gpio_sda=17,i2c_gpio_scl=18', local_imu_check(True)['detail'])

    def test_missing_library_and_permission_failure(self):
        with patch('motion_module.diagnostics.find_i2c_gpio_bus', return_value=11):
            with patch.dict(sys.modules, {'smbus2': None}):
                self.assertIn('smbus2', local_imu_check(True)['detail'])
            factory = MagicMock(side_effect=PermissionError('denied'))
            with patch.dict(sys.modules, {'smbus2': SimpleNamespace(SMBus=factory)}):
                self.assertIn('permissions', local_imu_check(True)['detail'])

    def test_optional_guide_preserves_all_existing_wires(self):
        config = load_config(project='')
        base = header_rows(config)
        guide = header_rows(config, imu_guide=True)
        for old, new in zip(base, guide):
            if old['physical'] in {6, 11, 12, 17, 20}:
                self.assertIn('IMU', new['role'])
                self.assertFalse(new['configured'])
            else:
                self.assertEqual(old, new)
