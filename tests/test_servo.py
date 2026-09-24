import unittest

from motion_module.config import load_config
from motion_module.servo import LED0_ON_L, PCA9685Controller


class FakeBus:
    def __init__(self, present=True):
        self.registers = {}
        self.blocks = []
        self.closed = False
        # A board that is not on the bus raises, exactly as smbus2 does.
        self.present = present
        self.writes_fail = False

    def _check(self):
        if not self.present:
            raise OSError(121, "Remote I/O error")

    def write_byte_data(self, address, register, value):
        self._check()
        self.registers[(address, register)] = value

    def read_byte_data(self, address, register):
        self._check()
        return self.registers.get((address, register), 0)

    def write_i2c_block_data(self, address, register, payload):
        self._check()
        if self.writes_fail:
            raise OSError(121, "Remote I/O error")
        self.blocks.append((address, register, list(payload)))
        # Model the chip's register pointer, not just the outgoing payload.
        # MODE1.AI (bit 5) is required for sequential multi-byte writes.
        increment = bool(self.registers.get((address, 0x00), 0) & 0x20)
        for value in payload:
            self.registers[(address, register)] = value
            if increment:
                register += 1

    def close(self):
        self.closed = True


class ServoTests(unittest.TestCase):
    def test_commands_program_pwm_registers_on_every_channel(self):
        bus = FakeBus()
        controller = PCA9685Controller(load_config().servos, bus=bus)
        for channel in range(16):
            register = LED0_ON_L + 4 * channel
            with self.subTest(channel=channel):
                self.assertEqual(bus.read_byte_data(0x40, register + 3), 0x10)
                for angle, pulse_us in [(0, 500), (90, 1500), (180, 2500)]:
                    controller.set_angle(0, channel, angle)
                    counts = round(pulse_us * 50 * 4096 / 1_000_000)
                    self.assertEqual(
                        [bus.read_byte_data(0x40, register + i) for i in range(4)],
                        [0, 0, counts & 0xFF, counts >> 8],
                    )
                controller.release(0, channel)
                self.assertEqual(bus.read_byte_data(0x40, register + 3), 0x10)

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

    def test_calibrated_pulse_supports_all_sixteen_channels(self):
        config = load_config().servos
        bus = FakeBus()
        controller = PCA9685Controller(config, bus=bus)
        controller.set_pulse_us(0, 15, 2100)
        address, register, payload = bus.blocks[-1]
        counts = payload[2] | ((payload[3] & 0x0F) << 8)
        self.assertEqual(address, 0x40)
        self.assertEqual(register, LED0_ON_L + 4 * 15)
        self.assertEqual(counts, round(2100 * 50 * 4096 / 1_000_000))
        self.assertEqual(controller.pulses[(0, 15)], 2100)
        with self.assertRaisesRegex(ValueError, "0 through 15"):
            controller.set_pulse_us(0, 16, 1500)
        with self.assertRaisesRegex(ValueError, "500 through 2500"):
            controller.set_pulse_us(0, 0, 3000)


class DetectionTests(unittest.TestCase):
    """Detection has to keep up with the wires, not just report boot state."""

    def test_a_board_unplugged_after_boot_stops_reporting_as_available(self):
        config = load_config().servos
        bus = FakeBus()
        controller = PCA9685Controller(config, bus=bus)
        self.assertEqual(controller.available, {0x40})

        bus.present = False
        controller.probe()
        self.assertEqual(controller.available, set())
        self.assertIn("Remote I/O error", controller.errors[0x40])

    def test_a_board_plugged_in_after_boot_is_picked_up_and_initialized(self):
        config = load_config().servos
        bus = FakeBus(present=False)
        controller = PCA9685Controller(config, bus=bus)
        self.assertEqual(controller.available, set())

        bus.present = True
        controller.probe()
        self.assertEqual(controller.available, {0x40})
        self.assertNotIn(0x40, controller.errors)
        controller.set_angle(0, 0, 90)   # usable without a restart

    def test_a_board_that_answers_but_refuses_a_write_is_recorded_as_faulted(self):
        config = load_config().servos
        bus = FakeBus()
        controller = PCA9685Controller(config, bus=bus)
        bus.writes_fail = True
        with self.assertRaises(OSError):
            controller.set_angle(0, 0, 90)
        self.assertIn(0x40, controller.faults)
        self.assertEqual(controller.available, {0x40})

        bus.writes_fail = False
        controller.set_angle(0, 0, 90)
        self.assertEqual(controller.faults, {})


if __name__ == "__main__":
    unittest.main()
