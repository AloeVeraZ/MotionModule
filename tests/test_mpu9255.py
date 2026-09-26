"""MPU9255 identity and AK8963 register-level integration, no real hardware."""

import struct
import unittest

from fake_giga import World
from test_mpu6500 import SimMpu6500
from test_pi_imu import FakeBus, LocalImuTestCase
from motion_module.imu import IMUConfig


class NineAxisBus(FakeBus):
    def __init__(self, chip, clock):
        super().__init__(chip, clock)
        self.mag_id = 0x48
        self.mag_mode = 0
        self.asa = [128, 160, 96]
        self.xyz = (100, -200, 300)
        self.ready = True
        self.overflow = False
        self.mag_present = True
        self.mag_writes = []
        self.read_st2 = 0

    def read_i2c_block_data(self, address, register, length):
        if address != 0x0C:
            if address != self.chip.address:
                raise OSError('no MPU at this address')
            return super().read_i2c_block_data(address, register, length)
        if not self.mag_present or self.chip.registers[0x37] != 2:
            raise OSError('magnetometer not accessible')
        if register == 0:
            return [self.mag_id]
        if register == 0x10:
            assert self.mag_mode == 0x0F
            return self.asa
        if register == 0x0A:
            return [self.mag_mode]
        if register == 2:
            return [int(self.ready)]
        if register == 3:
            assert length == 7
            self.read_st2 += 1
            return list(struct.pack('<3hB', *self.xyz, 0x10 | (8 if self.overflow else 0)))
        raise AssertionError(f'unexpected register {register}')

    def write_i2c_block_data(self, address, register, data):
        if address != 0x0C:
            return super().write_i2c_block_data(address, register, data)
        assert register == 0x0A
        self.mag_writes.append(data[0])
        self.mag_mode = data[0]


class NineAxisTests(LocalImuTestCase):
    def make(self, identity=0x73, address=0x68, mag_id=0x48):
        world = World()
        self.chip = SimMpu6500(world)
        self.chip.chip_id = identity
        self.chip.address = address

        def bus_factory(_):
            self.nine_bus = NineAxisBus(self.chip, self.clock)
            self.nine_bus.mag_id = mag_id
            return self.nine_bus

        self.build(IMUConfig(), self.chip, world, auto_address=True, bus_factory=bus_factory)
        self.run_for(3)

    def test_all_supported_identities_and_both_addresses_are_honest(self):
        for identity, name in ((0x73, 'MPU9255'), (0x71, 'MPU9250'), (0x70, 'MPU6500')):
            for address in (0x68, 0x69):
                with self.subTest(identity=identity, address=address):
                    self.make(identity, address)
                    self.assertTrue(self.imu.calibrated)
                    reading = self.imu.reading()
                    self.assertEqual(reading.chip, name)
                    self.assertEqual(reading.identity, f'0x{identity:02X}')
                    self.assertIsNotNone(reading.magnetic_ut)
                    self.imu.close()

    def test_factory_adjustment_signed_axes_and_status_latch(self):
        self.make()
        self.assertEqual(self.nine_bus.mag_writes, [0, 15, 0, 22])
        self.assertGreater(self.nine_bus.read_st2, 0)
        for actual, expected in zip(self.imu.reading().magnetic_ut, (15, -33.75, 39.375)):
            self.assertAlmostEqual(actual, expected)

    def test_wrong_magnetometer_is_never_written_and_gyro_keeps_working(self):
        self.make(mag_id=0x12)
        self.assertEqual(self.nine_bus.mag_writes, [])
        self.assertIsNone(self.imu.reading().magnetic_ut)
        self.assertIsNotNone(self.imu.heading())
        self.assertIn('expected 0x48', self.imu.reading().magnetometer_detail)

    def test_overflow_stale_loss_and_recovery_do_not_break_heading(self):
        self.make()
        self.nine_bus.overflow = True
        self.run_for(0.1)
        self.assertIsNone(self.imu.reading().magnetic_ut)
        self.assertIn('overflow', self.imu.reading().magnetometer_detail)
        self.nine_bus.overflow = False
        self.run_for(0.1)
        self.assertIsNotNone(self.imu.reading().magnetic_ut)
        self.nine_bus.ready = False
        self.run_for(1.2)
        self.assertIsNone(self.imu.reading().magnetic_ut)
        self.assertIn('stale', self.imu.reading().magnetometer_detail)
        self.nine_bus.mag_present = False
        self.run_for(0.1)
        self.assertIsNotNone(self.imu.heading())
        self.nine_bus.mag_present = True
        self.nine_bus.ready = True
        self.run_for(3)
        self.assertIsNotNone(self.imu.reading().magnetic_ut)


if __name__ == '__main__':
    unittest.main()
