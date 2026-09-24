"""A BNO055 or 6-axis IMU wired straight to the Pi's own I2C bus, not a GIGA.

Reuses fake_giga.py's simulated chips: the register-level I2C protocol a
BNO055 or LSM6 answers is identical whether the bytes travel over a GIGA's
serial link or straight to smbus2, so the same simulated chips exercise both
transports.
"""

import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fake_giga import Clock, SimBno055, SimLsm6, World
from motion_module.imu import GigaIMU
from motion_module.pi_imu import LocalIMU, find_i2c_gpio_bus

NINE_AXIS = GigaIMU("bno055", "Main IMU")
SIX_AXIS = GigaIMU("ism330dhcx", "Backup IMU")


class FindI2cGpioBusTests(unittest.TestCase):
    def test_device_tree_adapter_name_is_not_the_driver_name(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._adapter(root, "i2c-11", "i2c@0")
            node = root / "i2c-11/device/of_node"
            node.mkdir(parents=True)
            (node / "compatible").write_bytes(b"i2c-gpio\0")
            self.assertEqual(find_i2c_gpio_bus(root), 11)

    def _adapter(self, root: Path, entry: str, name: str) -> None:
        directory = root / entry
        directory.mkdir()
        (directory / "name").write_text(name + "\n", encoding="utf-8")

    def test_missing_sysfs_returns_none(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(find_i2c_gpio_bus(Path(directory) / "missing"))

    def test_no_i2c_gpio_adapter_returns_none(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._adapter(root, "i2c-1", "bcm2835 (i2c@7e804000)")
            self.assertIsNone(find_i2c_gpio_bus(root))

    def test_finds_the_i2c_gpio_adapter_by_name_not_by_number(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            self._adapter(root, "i2c-1", "bcm2835 (i2c@7e804000)")   # the servo board's bus
            self._adapter(root, "i2c-11", "i2c-gpio")                # assigned a high, unpredictable number
            self.assertEqual(find_i2c_gpio_bus(root), 11)


class FakeBus:
    """A stand-in smbus2.SMBus backed by one fake_giga SimChip."""

    def __init__(self, chip, clock: Clock):
        self.chip = chip
        self.clock = clock
        self.closed = False

    def read_i2c_block_data(self, _address, register, length):
        data = self.chip.read(register, length, int(self.clock.now * 1000))
        if data is None:
            raise OSError("no answer")
        return list(data)

    def write_i2c_block_data(self, _address, register, data):
        if not self.chip.write(register, bytes(data), int(self.clock.now * 1000)):
            raise OSError("write refused")

    def close(self):
        self.closed = True


class LocalImuTestCase(unittest.TestCase):
    """A LocalIMU wired to a simulated chip, with a clock the test moves."""

    def build(self, declaration, chip, world, *, auto_address=False, bus_factory=None):
        self.clock = Clock()
        self.world = world
        self.bus = FakeBus(chip, self.clock)
        self.imu = LocalIMU(
            declaration, auto_start=False, clock=self.clock, auto_address=auto_address,
            bus_factory=bus_factory or (lambda _bus_number: self.bus),
        )
        self.addCleanup(self.imu.close)
        return self.imu

    def run_for(self, seconds: float, step_ms: int = 20) -> None:
        # A real chip's own fusion runs continuously; the simulated world's
        # yaw only moves when something advances it, the way fake_giga's own
        # board.tick() does for the GIGA-relayed tests.
        for _cycle in range(max(1, int(seconds * 1000 / step_ms))):
            self.world.advance(step_ms / 1000.0)
            self.clock.advance(step_ms / 1000.0)
            self.imu.poll(self.clock.now)


class NineAxisOverPiI2cTests(LocalImuTestCase):
    def setUp(self):
        self.world = World()
        self.chip = SimBno055(self.world)
        self.build(NINE_AXIS, self.chip, self.world)

    def test_waits_for_external_crystal_before_entering_fusion(self):
        class SlowCrystal(SimBno055):
            def write(self, register, data, now_ms):
                accepted = super().write(register, data, now_ms)
                if accepted and register == 0x3F and data == b"\x80":
                    # Bosch specifies approximately 600 ms minimum for the
                    # clock switch; configuration writes during it can fail.
                    self.ready_at = now_ms + 600
                return accepted

        self.imu.close()
        self.chip = SlowCrystal(self.world)
        self.build(NINE_AXIS, self.chip, self.world)
        self.run_for(3.0)
        self.assertEqual(self.imu.state, "ok")
        self.assertEqual(self.chip.mode, 0x08)
        self.assertEqual(self.chip.resets, 1)
        self.assertIsNotNone(self.imu.heading())

    def test_polls_a_clock_that_takes_longer_than_the_minimum(self):
        class BusyClock(SimBno055):
            clock_ready_at = 0

            def write(self, register, data, now_ms):
                if register == 0x3D and data == b"\x08" and now_ms < self.clock_ready_at:
                    return False
                accepted = super().write(register, data, now_ms)
                if accepted and register == 0x3F and data == b"\x80":
                    self.clock_ready_at = now_ms + 1000
                return accepted

            def read(self, register, length, now_ms):
                if register == 0x38:
                    return bytes([int(now_ms < self.clock_ready_at)])
                return super().read(register, length, now_ms)

        self.imu.close()
        self.chip = BusyClock(self.world)
        self.build(NINE_AXIS, self.chip, self.world)
        self.run_for(3.5)
        self.assertEqual(self.imu.state, "ok")
        self.assertEqual(self.chip.resets, 1)
        self.assertTrue(self.imu.calibrated)

    def test_a_clock_that_never_becomes_ready_has_a_bounded_failure(self):
        class StuckClock(SimBno055):
            def read(self, register, length, now_ms):
                if register == 0x38:
                    return b"\x01"
                return super().read(register, length, now_ms)

        self.imu.close()
        self.chip = StuckClock(self.world)
        self.build(NINE_AXIS, self.chip, self.world)
        self.run_for(4.0)
        self.assertEqual(self.imu.state, "failed")
        self.assertIn("clock did not become ready", self.imu.describe())
        self.assertEqual(self.chip.mode, 0)
        self.assertIsNone(self.imu.heading())

    def test_the_pi_sets_the_sensor_up_and_reads_its_heading(self):
        self.run_for(3.0)  # reset, external clock startup, then calibration
        self.assertEqual(self.imu.state, "ok")
        self.assertEqual(self.imu.chip, "BNO055")
        self.assertEqual(self.chip.resets, 1)
        self.assertTrue(self.chip.crystal)
        self.assertEqual(self.chip.mode, 0x08)  # gyro and accelerometer, no compass
        self.assertTrue(self.imu.calibrated)
        self.assertFalse(self.bus.closed)

        self.world.rate = 90
        self.run_for(1.0)
        self.assertAlmostEqual(self.imu.rate(), 90.0, delta=1.0)
        self.world.rate = 0
        self.run_for(0.1)
        self.assertAlmostEqual(self.imu.heading(), 90.0, delta=1.0)

    def test_heading_wraps_and_zeroes(self):
        self.run_for(2.0)
        self.world.rate = 190
        self.run_for(1.0)
        self.world.rate = 0
        self.run_for(0.1)
        self.assertAlmostEqual(self.imu.heading(), -170.0, delta=2.0)
        self.imu.zero()
        self.assertAlmostEqual(self.imu.heading(), 0.0, delta=0.1)
        self.imu.zero(45)
        self.assertAlmostEqual(self.imu.heading(), 45.0, delta=0.1)

    def test_driver_station_reading_matches_robot_code(self):
        self.run_for(3.0)
        panel = self.imu.reading()
        self.assertTrue(panel.connected)
        self.assertTrue(panel.calibrated)
        self.assertAlmostEqual(panel.yaw, self.imu.heading())
        self.assertIn("BNO055 at 0x28", panel.detail)

    def test_a_missing_chip_is_reported_as_missing_not_a_crash(self):
        self.chip.present = False
        self.run_for(3.0)
        self.assertEqual(self.imu.state, "missing")
        self.assertIn("Nothing answers at 0x28", self.imu.describe())
        self.assertIsNone(self.imu.heading())
        self.assertFalse(self.imu.reading().connected)

    def test_auto_detection_finds_alternate_address_after_startup(self):
        class AddressedBus(FakeBus):
            def read_i2c_block_data(self, address, register, length):
                if address != 0x29:
                    raise OSError("no answer")
                return super().read_i2c_block_data(address, register, length)

            def write_i2c_block_data(self, address, register, data):
                if address != 0x29:
                    raise OSError("no answer")
                return super().write_i2c_block_data(address, register, data)

        self.imu.close()
        bus = AddressedBus(self.chip, self.clock)
        self.imu = LocalIMU(
            NINE_AXIS, auto_start=False, clock=self.clock, auto_address=True,
            bus_factory=lambda _number: bus,
        )
        self.addCleanup(self.imu.close)
        self.chip.present = False
        self.run_for(3.0)
        self.assertEqual(self.imu.state, "missing")
        self.chip.present = True
        self.run_for(3.0)
        self.assertEqual(self.imu.state, "ok")
        self.assertEqual(self.imu._driver.address, 0x29)
        self.assertIn("0x29", self.imu.describe())


class SixAxisOverPiI2cTests(LocalImuTestCase):
    def setUp(self):
        self.world = World()
        self.chip = SimLsm6(self.world, chip_id=0x6B)
        self.build(SIX_AXIS, self.chip, self.world)

    def test_calibrates_at_rest_then_tracks_turns(self):
        self.run_for(2.0)
        self.assertEqual(self.imu.state, "ok")
        self.assertTrue(self.imu.calibrated)
        self.world.rate = 45
        self.run_for(2.0)
        self.assertAlmostEqual(self.imu.rate(), 45.0, delta=2.0)


class NoTransportTests(unittest.TestCase):
    """Without smbus2, or without a bus factory, the IMU must say so plainly
    instead of raising - on any platform, whether or not smbus2 actually
    happens to be installed here."""

    def test_missing_smbus2_is_a_clear_message_not_a_crash(self):
        with patch.dict(sys.modules, {"smbus2": None}):
            imu = LocalIMU(NINE_AXIS, auto_start=False)
            self.addCleanup(imu.close)
            self.assertFalse(imu.poll(0.0))
            self.assertEqual(imu.state, "waiting")
            self.assertIn("smbus2", imu.describe())
            self.assertIsNone(imu.heading())


class LocalIMURecoveryTests(unittest.TestCase):
    def test_background_reader_retries_an_initial_bus_failure(self):
        imu = LocalIMU(NINE_AXIS, auto_start=False)
        attempts = []

        def poll():
            attempts.append(True)
            if len(attempts) == 2:
                imu._stop.set()
                return True
            return False

        with patch.object(imu, "poll", side_effect=poll), \
                patch("motion_module.pi_imu.RETRY_SECONDS", 0.001):
            imu.start()
            imu._thread.join(timeout=1)
            imu.close()
        self.assertEqual(len(attempts), 2)

    def test_recovered_bus_clears_the_previous_open_error(self):
        bus = Mock()
        smbus = Mock(SMBus=Mock(side_effect=[OSError("temporarily unavailable"), bus]))
        with patch.dict(sys.modules, {"smbus2": smbus}):
            imu = LocalIMU(NINE_AXIS, auto_start=False)
            self.assertFalse(imu.poll(0))
            self.assertIn("temporarily unavailable", imu.describe())
            self.assertTrue(imu.poll(1))
            self.assertNotIn("temporarily unavailable", imu.describe())


if __name__ == "__main__":
    unittest.main()
