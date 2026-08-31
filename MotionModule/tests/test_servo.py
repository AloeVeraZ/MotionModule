import unittest

from motion_module.config import load_config
from motion_module.servo import LED0_ON_L, PCA9685Controller


class FakeBus:
    def __init__(self):
        self.registers = {}
        self.blocks = []
        self.closed = False

    def write_byte_data(self, address, register, value):
        self.registers[(address, register)] = value

    def read_byte_data(self, address, register):
        return self.registers.get((address, register), 0)

    def write_i2c_block_data(self, address, register, payload):
        self.blocks.append((address, register, list(payload)))

    def close(self):
        self.closed = True


class ServoTests(unittest.TestCase):
    def test_angle_generates_pca9685_counts(self):
        config = load_config().servos
        bus = FakeBus()
        controller = PCA9685Controller(config, bus=bus)
        controller.set_angle(0, 3, 90)
        address, register, payload = bus.blocks[-1]
        counts = payload[2] | ((payload[3] & 0x0F) << 8)
        self.assertEqual(address, 0x40)
        self.assertEqual(register, LED0_ON_L + 4 * 3)
        self.assertEqual(counts, round(1500 * 50 * 4096 / 1_000_000))

    def test_release_sets_full_off_bit(self):
        config = load_config().servos
        bus = FakeBus()
        controller = PCA9685Controller(config, bus=bus)
        controller.release(0, 2)
        self.assertEqual(bus.blocks[-1][2][3] & 0x10, 0x10)


if __name__ == "__main__":
    unittest.main()
