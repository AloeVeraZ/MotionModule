"""Exercise the real MPU9255 driver through a register-level fake I2C bus."""

import unittest

from fake_giga import World
from test_pi_imu import FakeBus, LocalImuTestCase
from motion_module.imu import GigaIMU, Mpu9255Driver


class SimMpu9255:
    def __init__(self, world):
        self.world = world
        self.present = True
        self.chip_id = 0x73
        self.registers = bytearray(128)
        self.registers[0x6B] = 0x40
        self.reset_until = 0
        self.bias = (1.0, -2.0, 0.5)
        self.refuse = None
        self.writes = []

    def read(self, register, length, now_ms):
        if not self.present:
            return None
        data = bytearray(self.registers)
        data[0x75] = self.chip_id
        if now_ms < self.reset_until:
            data[0x6B] |= 0x80
        for axis, up in enumerate(self.world.up):
            accel = round(up * 8192)  # +/-4 g
            gyro = round((self.world.rate * up + self.bias[axis]) * 16.4)
            data[0x3B + 2*axis:0x3D + 2*axis] = accel.to_bytes(2, 'big', signed=True)
            data[0x43 + 2*axis:0x45 + 2*axis] = gyro.to_bytes(2, 'big', signed=True)
        data[0x41:0x43] = b'\x7f\xff'  # temperature must not become a gyro axis
        return bytes(data[register:register + length])

    def write(self, register, data, now_ms):
        if not self.present or register == self.refuse:
            return False
        self.writes.append((register, bytes(data)))
        if register == 0x6B and data == b'\x80':
            self.registers = bytearray(128)
            self.registers[0x6B] = 0x40
            self.reset_until = now_ms + 100
        else:
            self.registers[register:register + len(data)] = data
        return True


class Mpu9255Tests(LocalImuTestCase):
    def setUp(self):
        self.world = World()
        self.chip = SimMpu9255(self.world)
        self.build(GigaIMU('mpu9255'), self.chip, self.world)

    def test_calibrates_bias_and_tracks_left_and_right_turns(self):
        self.run_for(3)
        self.assertTrue(self.imu.calibrated)
        self.run_for(2)
        self.assertAlmostEqual(self.imu.heading(), 0, delta=0.2)
        for rate in (90, -90):
            self.imu.zero()
            self.world.rate = rate
            self.run_for(1)
            self.assertAlmostEqual(self.imu.heading(), rate, delta=1)
            self.assertAlmostEqual(self.imu.rate(), rate, delta=0.1)

    def test_signed_big_endian_vectors_skip_temperature(self):
        data = bytes.fromhex('2000 e000 1000 7fff 0668 f998 0000')
        gyro, accel = Mpu9255Driver(GigaIMU('mpu9255'))._vectors(data)
        self.assertEqual(accel, (8192, -8192, 4096))
        self.assertAlmostEqual(gyro[0], 100)
        self.assertAlmostEqual(gyro[1], -100)
        self.assertEqual(gyro[2], 0)

    def test_tilt_does_not_become_a_turn(self):
        self.run_for(3)
        self.world.pitch = 20
        self.run_for(5)
        self.assertAlmostEqual(self.imu.pitch(), 20, delta=1)
        self.assertAlmostEqual(self.imu.heading(), 0, delta=1)

    def test_startup_motion_delays_calibration_and_pending_zero(self):
        self.imu.zero(45)
        self.world.rate = 40
        self.run_for(3)
        self.assertEqual(self.imu.state, 'calibrating')
        self.assertIsNone(self.imu.heading())
        self.world.rate = 0
        self.run_for(3)
        self.assertAlmostEqual(self.imu.heading(), 45, delta=0.1)

    def test_missing_wrong_chip_and_failed_writes(self):
        self.chip.present = False
        self.run_for(1)
        self.assertEqual(self.imu.state, 'missing')
        self.chip.present = True
        self.chip.chip_id = 0x71  # a 9250 is not a verified 9255
        self.run_for(3)
        self.assertEqual(self.imu.state, 'wrong-chip')
        self.assertFalse(self.chip.writes)
        self.chip.chip_id = 0x73
        self.chip.refuse = 0x1B
        for _ in range(200):
            self.run_for(0.02)
            if self.imu.state == 'failed':
                break
        self.assertEqual(self.imu.state, 'failed')
        self.assertIsNone(self.imu.heading())
        self.chip.refuse = None
        self.run_for(5)
        self.assertTrue(self.imu.calibrated)

    def test_disconnect_and_recovery(self):
        self.run_for(3)
        self.chip.present = False
        self.run_for(0.3)
        self.assertFalse(self.imu.reading().connected)
        self.assertIsNone(self.imu.heading())
        self.chip.present = True
        self.run_for(5)
        self.assertTrue(self.imu.calibrated)

    def test_reset_timeout_and_configuration_readback_fail_closed(self):
        original = self.chip.read
        for broken_register, bad_value, message in (
            (0x6B, 0x80, 'did not reset'),
            (0x1B, 0, 'did not retain'),
        ):
            with self.subTest(register=broken_register):
                def broken_read(register, length, now_ms):
                    if register == broken_register:
                        return bytes([bad_value])
                    return original(register, length, now_ms)

                self.chip.read = broken_read
                self.imu._driver.begin(self.clock.now)
                # Open the fake bus before stepping the new setup.
                for _ in range(150):
                    self.run_for(0.02)
                    if self.imu.state == 'failed':
                        break
                self.assertEqual(self.imu.state, 'failed')
                self.assertIn(message, self.imu.describe())
                self.assertIsNone(self.imu.heading())

    def test_short_reads_fail_without_decoding_or_crashing(self):
        self.run_for(3)
        original = self.chip.read

        def short_read(register, length, now_ms):
            if register == 0x3B:
                return b'\x00' * 13
            return original(register, length, now_ms)

        self.chip.read = short_read
        self.run_for(0.3)
        self.assertEqual(self.imu.state, 'failed')
        self.assertIsNone(self.imu.heading())

    def test_alternate_address_and_wrong_device_at_default(self):
        class AddressedBus(FakeBus):
            def read_i2c_block_data(self, address, register, length):
                if address == 0x68:
                    return [0x71] * length
                return super().read_i2c_block_data(address, register, length)

            def write_i2c_block_data(self, address, register, data):
                self.assert_address(address)
                return super().write_i2c_block_data(address, register, data)

            def assert_address(self, address):
                if address != 0x69:
                    raise AssertionError('must not write to the wrong chip')

        self.imu.close()
        self.build(GigaIMU('mpu9255'), self.chip, self.world, auto_address=True,
                   bus_factory=lambda _: AddressedBus(self.chip, self.clock))
        self.run_for(3)
        self.assertTrue(self.imu.calibrated)
        self.assertIn('0x69', self.imu.describe())

    def test_explicit_address_is_preferred_when_both_addresses_answer(self):
        self.imu.close()
        self.build(GigaIMU('mpu9255', address=0x69), self.chip, self.world, auto_address=True)
        self.run_for(3)
        self.assertTrue(self.imu.calibrated)
        self.assertIn('0x69', self.imu.describe())

    def test_chip_connected_late_at_alternate_address_is_found(self):
        class AlternateBus(FakeBus):
            def read_i2c_block_data(self, address, register, length):
                if address != 0x69:
                    raise OSError('no answer')
                return super().read_i2c_block_data(address, register, length)

            def write_i2c_block_data(self, address, register, data):
                if address != 0x69:
                    raise AssertionError('write sent to an unidentified address')
                return super().write_i2c_block_data(address, register, data)

        self.imu.close()
        self.build(GigaIMU('mpu9255'), self.chip, self.world, auto_address=True,
                   bus_factory=lambda _: AlternateBus(self.chip, self.clock))
        self.chip.present = False
        self.run_for(3)
        self.assertEqual(self.imu.state, 'missing')
        self.chip.present = True
        self.run_for(5)
        self.assertTrue(self.imu.calibrated)
        self.assertIn('0x69', self.imu.describe())

    def test_stale_data_and_close_are_offline(self):
        self.run_for(3)
        self.clock.advance(2)
        self.assertFalse(self.imu.reading().connected)
        self.assertIn('stale', self.imu.describe())
        self.assertIsNone(self.imu.heading())
        self.imu.close()
        self.assertTrue(self.bus.closed)
        self.assertEqual(self.imu.state, 'waiting')

    def test_invalid_declarations_fail_early(self):
        self.assertEqual(GigaIMU('MPU-9255').address, 0x68)
        for kwargs in ({'address': 0x28}, {'compass': True}):
            with self.assertRaises(ValueError):
                GigaIMU('mpu9255', **kwargs)


if __name__ == '__main__':
    unittest.main()
