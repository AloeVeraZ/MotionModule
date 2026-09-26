"""Pi I2C discovery, transport and recovery tests for the MPU6500."""
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fake_giga import Clock, World
from motion_module.imu import IMUConfig
from motion_module.pi_imu import LocalIMU, find_i2c_gpio_bus

IMU = IMUConfig()


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
            declaration, bus=15, auto_start=False, clock=self.clock, auto_address=auto_address,
            bus_factory=bus_factory or (lambda _bus_number: self.bus),
        )
        self.addCleanup(self.imu.close)
        return self.imu

    def run_for(self, seconds: float, step_ms: int = 20) -> None:
        # Advance physical motion and the host clock before each I2C poll.
        for _cycle in range(max(1, int(seconds * 1000 / step_ms))):
            self.world.advance(step_ms / 1000.0)
            self.clock.advance(step_ms / 1000.0)
            self.imu.poll(self.clock.now)


class NoTransportTests(unittest.TestCase):
    """Without smbus2, or without a bus factory, the IMU must say so plainly
    instead of raising - on any platform, whether or not smbus2 actually
    happens to be installed here."""

    def test_missing_smbus2_is_a_clear_message_not_a_crash(self):
        with patch.dict(sys.modules, {"smbus2": None}):
            imu = LocalIMU(IMU, bus=15, auto_start=False)
            self.addCleanup(imu.close)
            self.assertFalse(imu.poll(0.0))
            self.assertEqual(imu.state, "waiting")
            self.assertIn("smbus2", imu.describe())
            self.assertIsNone(imu.heading())


class LocalIMURecoveryTests(unittest.TestCase):
    def test_background_reader_retries_an_initial_bus_failure(self):
        imu = LocalIMU(IMU, bus=15, auto_start=False)
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
            imu = LocalIMU(IMU, bus=15, auto_start=False)
            self.assertFalse(imu.poll(0))
            self.assertIn("temporarily unavailable", imu.describe())
            self.assertTrue(imu.poll(1))
            self.assertNotIn("temporarily unavailable", imu.describe())


if __name__ == "__main__":
    unittest.main()
