"""The Pi side of the Arduino GIGA sensor board.

The GIGA only moves bytes, so these tests run the real drivers and the real
heading maths against a simulated board and simulated chips (fake_giga.py).
"""

import time
import unittest

from fake_giga import Clock, FakeGiga, SimBno055, SimLsm6, World, run
from motion_module.config import default_config
from motion_module.controller import MotionModule
from motion_module.gpio import MockGPIO
from motion_module.sensor_bridge import (
    GIGA_FIRMWARE_VERSION,
    PROTOCOL_V1,
    GigaIMU,
    GigaPin,
    GigaR1Bridge,
    active_bridges,
)


GIGA = {
    "board_id": "arduino_giga_r1_wifi", "name": "Arduino GIGA R1 WiFi",
    "connected": True, "serial": "ABC", "port": "/dev/ttyACM0", "mode": "sketch",
}
NINE_AXIS = GigaIMU("bno055", "Main IMU")
SIX_AXIS = GigaIMU("ism330dhcx", "Backup IMU")


class BridgeTestCase(unittest.TestCase):
    """A bridge wired to a simulated GIGA, with a clock the test moves."""

    def build(self, pins=(), imus=(), board=None, **options):
        self.clock = Clock()
        self.world = World()
        self.board = board if board is not None else FakeGiga(self.world)
        options.setdefault("discovery", lambda: [dict(GIGA)])
        bridge = GigaR1Bridge(
            pins, imus=imus, autostart=False, clock=self.clock,
            serial_factory=lambda *_args, **_keywords: self.board, **options,
        )
        self.addCleanup(bridge.close)
        self.bridge = bridge
        return bridge

    def run_for(self, seconds, step_ms=None):
        run(self.bridge, self.board, self.clock, seconds, step_ms)


class DeclarationTests(unittest.TestCase):
    def test_giga_pin_validation_uses_the_exposed_input_ranges(self):
        self.assertEqual(GigaPin("a7", "Pot", kind="analog").pin, "A7")
        self.assertEqual(GigaPin("d75", "Limit").pin, "D75")
        with self.assertRaisesRegex(ValueError, "A0-A7"):
            GigaPin("A8", "Not an ADC pin", kind="analog")

    def test_imus_default_to_their_boards_addresses(self):
        self.assertEqual(GigaIMU("BNO055", "Main").address, 0x28)
        self.assertEqual(GigaIMU("ISM330DHCX", "Six").address, 0x6A)
        self.assertEqual(GigaIMU("lsm6dsox", "Six", address=0x6B).address, 0x6B)
        self.assertEqual(GigaIMU("bno055", "Nine", compass=True).driver, "BNO055")

    def test_imu_declarations_catch_wiring_mistakes(self):
        with self.assertRaisesRegex(ValueError, "0x28"):
            GigaIMU("bno055", "Main", address=0x6A)
        with self.assertRaisesRegex(ValueError, "compass"):
            GigaIMU("ism330dhcx", "Six", compass=True)
        with self.assertRaisesRegex(ValueError, "bno055"):
            GigaIMU("mpu6050", "Old")
        with self.assertRaisesRegex(ValueError, "share an I2C address"):
            GigaR1Bridge(imus=[GigaIMU("bno055", "A"), GigaIMU("bno055", "B")], autostart=False)
        with self.assertRaisesRegex(ValueError, "own name"):
            GigaR1Bridge([GigaPin("D2", "Same")], imus=[GigaIMU("bno055", "same")], autostart=False)
        with self.assertRaisesRegex(ValueError, "at least one"):
            GigaR1Bridge(autostart=False)


class ProtocolTests(BridgeTestCase):
    def test_the_board_is_told_which_pins_and_registers_to_read(self):
        bridge = self.build([GigaPin("A0", "Pot", kind="analog"), GigaPin("D22", "Beam", pull="up")],
                            imus=[NINE_AXIS, SIX_AXIS])
        bridge.poll()
        self.assertEqual(
            self.board.commands[0],
            f"MM3 CONFIG {bridge.config_id} 20 A0:A,D22:U 28:14:12,28:2E:8,6A:22:12",
        )
        self.assertEqual(self.board.streams, [(0x28, 0x14, 12), (0x28, 0x2E, 8), (0x6A, 0x22, 12)])

    def test_pins_arrive_as_on_off_and_numbers(self):
        bridge = self.build([GigaPin("A0", "Pot", kind="analog", minimum=0, maximum=4095),
                             GigaPin("D22", "Beam", pull="up")])
        self.board.pins.update({"A0": 2048, "D22": 1})
        self.run_for(0.1)
        self.assertEqual(bridge.value("Pot"), 2048.0)
        self.assertIs(bridge.value("Beam"), True)
        self.board.pins["D22"] = 0
        self.run_for(0.1)
        self.assertIs(bridge.value("Beam"), False)
        snapshot = bridge.snapshot()
        self.assertEqual(snapshot.bridge, "streaming")
        self.assertEqual(snapshot.pins[0].value, 2048.0)
        self.assertEqual(bridge.firmware, GIGA_FIRMWARE_VERSION)

    def test_lines_split_across_reads_are_joined(self):
        bridge = self.build([GigaPin("D2", "Limit")])
        self.board.pins["D2"] = 1
        bridge.poll()
        self.board.tick(20)
        whole = bytes(self.board.incoming)
        self.board.incoming = bytearray(whole[:17])
        bridge.poll()
        self.assertIsNone(bridge.value("Limit"))
        self.board.incoming += whole[17:]
        bridge.poll()
        self.assertIs(bridge.value("Limit"), True)

    def test_readings_for_another_configuration_are_ignored_and_config_is_resent(self):
        bridge = self.build([GigaPin("D2", "Limit")])
        self.board.pins["D2"] = 1
        self.run_for(0.1)
        self.assertIs(bridge.value("Limit"), True)
        # Someone else configured the board: its readings are no longer ours.
        self.board.config_id = bridge.config_id + 1
        self.board.commands.clear()
        self.run_for(0.2)
        self.clock.advance(1.5)
        self.assertIsNone(bridge.value("Limit"))
        # Within a second the bridge asks for its own sensors again.
        self.run_for(1.5)
        self.assertTrue(any(command.startswith("MM3 CONFIG") for command in self.board.commands))
        self.assertIs(bridge.value("Limit"), True)

    def test_stale_readings_turn_into_none(self):
        bridge = self.build([GigaPin("D2", "Limit")], stale_after=0.1)
        self.board.pins["D2"] = 1
        self.run_for(0.1)
        self.assertIs(bridge.value("Limit"), True)
        self.clock.advance(0.2)
        self.assertIsNone(bridge.value("Limit"))
        self.assertFalse(bridge.streaming)

    def test_missing_giga_is_reported_offline_without_opening_a_port(self):
        bridge = self.build([GigaPin("D2", "Limit")], discovery=lambda: [])
        bridge._serial_factory = lambda *_args, **_keywords: self.fail("serial should not open")
        self.assertFalse(bridge.poll())
        snapshot = bridge.snapshot()
        self.assertFalse(snapshot.connected)
        self.assertEqual(snapshot.pins[0].status, "offline")
        self.assertIn("Plug it into", snapshot.detail)

    def test_a_giga_in_its_bootloader_is_not_opened(self):
        bridge = self.build([GigaPin("D2", "Limit")],
                            discovery=lambda: [{**GIGA, "port": "", "mode": "bootloader"}])
        bridge._serial_factory = lambda *_args, **_keywords: self.fail("serial should not open")
        self.assertFalse(bridge.poll())
        self.assertIn("motionmodule giga flash", bridge.status)

    def test_permission_errors_explain_the_dialout_group(self):
        class SerialException(OSError):
            """pyserial's own error, which wraps the refused open's errno."""

        def denied(*_args, **_keywords):
            raise SerialException(13, "could not open port /dev/ttyACM0: [Errno 13] Permission denied")

        bridge = self.build([GigaPin("D2", "Limit")])
        bridge._serial_factory = denied
        self.assertFalse(bridge.poll())
        self.assertIn("dialout", bridge.status)

    def test_a_lost_port_is_closed_and_found_again(self):
        bridge = self.build([GigaPin("D2", "Limit")])
        self.board.pins["D2"] = 1
        self.run_for(0.1)

        def unplugged(_size):
            raise OSError("device disconnected")

        self.board.read = unplugged
        bridge.poll()
        self.assertTrue(self.board.closed)
        self.assertIsNone(bridge.value("Limit"))
        self.assertIn("Lost", bridge.status)

    def test_board_rejections_are_shown(self):
        bridge = self.build([GigaPin("D2", "Limit")])
        bridge.poll()
        self.board._error("pin list not understood")
        bridge.poll()
        self.assertIn("pin list not understood", bridge.status)

    def test_a_restarted_board_is_configured_again(self):
        bridge = self.build([GigaPin("D2", "Limit")], imus=[SIX_AXIS])
        self.board.attach(0x6A, SimLsm6(self.world))
        self.run_for(2.5)
        self.assertEqual(bridge.imu().state, "ok")
        self.board.restart()
        self.run_for(1.2)
        self.assertEqual(self.board.config_id, bridge.config_id)
        self.run_for(2.0)
        self.assertEqual(bridge.imu().state, "ok")

    def test_background_thread_reads_without_being_polled(self):
        board = FakeGiga()
        board.pins["D2"] = 1
        bridge = GigaR1Bridge([GigaPin("D2", "Limit")], discovery=lambda: [dict(GIGA)],
                              serial_factory=lambda *_args, **_keywords: board)
        self.addCleanup(bridge.close)
        bridge.start()
        self.assertIn(bridge, active_bridges())
        deadline = time.monotonic() + 3
        while bridge.value("Limit") is None and time.monotonic() < deadline:
            board.tick(20)
            time.sleep(0.005)
        self.assertIs(bridge.value("Limit"), True)
        bridge.close()
        self.assertNotIn(bridge, active_bridges())
        self.assertTrue(board.closed)

    def test_two_bridges_cannot_read_the_same_board(self):
        first = GigaR1Bridge([GigaPin("D2", "Limit")], discovery=lambda: [])
        second = GigaR1Bridge([GigaPin("D3", "Other")], discovery=lambda: [])
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        first.start()
        with self.assertRaisesRegex(RuntimeError, "sensors.py"):
            second.start()


class NineAxisTests(BridgeTestCase):
    """The BNO055, which fuses its own readings."""

    def setUp(self):
        self.build(imus=[NINE_AXIS])
        self.chip = self.board.attach(0x28, SimBno055(self.world))
        self.imu = self.bridge.imu()

    def test_the_pi_sets_the_sensor_up_and_reads_its_heading(self):
        self.run_for(2.0)
        self.assertEqual(self.imu.state, "ok")
        self.assertEqual(self.imu.chip, "BNO055")
        self.assertEqual(self.chip.resets, 1)         # the Pi restarts it cleanly
        self.assertTrue(self.chip.crystal)            # and uses the board's crystal
        self.assertEqual(self.chip.units, 0)          # degrees and degrees per second
        self.assertEqual(self.chip.mode, 0x08)        # gyro and accelerometer, no compass
        self.assertTrue(self.imu.calibrated)

        self.world.rate = 90                          # turning left
        self.run_for(1.0)
        self.assertAlmostEqual(self.imu.rate(), 90.0, delta=1.0)
        self.world.rate = 0
        self.run_for(0.1)
        self.assertAlmostEqual(self.imu.heading(), 90.0, delta=1.0)

    def test_heading_wraps_and_zeroes(self):
        self.run_for(2.0)
        self.world.rate = 190          # a long left turn, past half a circle
        self.run_for(1.0)
        self.world.rate = 0
        self.run_for(0.1)
        self.assertAlmostEqual(self.imu.heading(), -170.0, delta=2.0)
        self.assertAlmostEqual(self.imu.total_rotation(), 190.0, delta=2.0)
        self.imu.zero()
        self.assertAlmostEqual(self.imu.heading(), 0.0, delta=0.1)
        self.world.rate = 90
        self.run_for(1.0)
        self.world.rate = 0
        self.run_for(0.1)
        self.assertAlmostEqual(self.imu.heading(), 90.0, delta=2.0)
        self.imu.zero(45)
        self.assertAlmostEqual(self.imu.heading(), 45.0, delta=0.1)

    def test_zero_before_the_sensor_streams_applies_to_the_first_reading(self):
        self.imu.zero(10)
        self.world.yaw = 300.0
        self.run_for(2.0)
        self.assertAlmostEqual(self.imu.heading(), 10.0, delta=1.0)

    def test_tilt_reads_front_up_and_right_side_down_as_positive(self):
        self.world.pitch, self.world.roll = 10.0, -6.0
        self.run_for(2.0)
        self.assertAlmostEqual(self.imu.pitch(), 10.0, delta=0.5)
        self.assertAlmostEqual(self.imu.roll(), -6.0, delta=0.5)

    def test_a_compass_imu_uses_the_ninedof_mode(self):
        self.build(imus=[GigaIMU("bno055", "Compass IMU", compass=True)])
        chip = self.board.attach(0x28, SimBno055(self.world))
        self.run_for(2.0)
        self.assertEqual(chip.mode, 0x0C)

    def test_driver_station_reading_matches_robot_code(self):
        self.run_for(2.0)
        panel = self.imu.reading()
        self.assertTrue(panel.connected)
        self.assertTrue(panel.calibrated)
        self.assertAlmostEqual(panel.yaw, self.imu.heading())
        self.assertIn("gyro 3/3", panel.detail)


class SixAxisTests(BridgeTestCase):
    """An ST 6-axis IMU, which the Pi fuses itself."""

    def setUp(self):
        self.build(imus=[SIX_AXIS])
        self.chip = self.board.attach(0x6A, SimLsm6(self.world, bias=(0.8, -0.6, 1.3), noise=0.3))
        self.imu = self.bridge.imu()

    def test_the_pi_measures_the_gyro_at_rest_then_holds_a_heading(self):
        self.run_for(0.4)
        self.assertEqual(self.imu.state, "calibrating")
        self.assertIsNone(self.imu.heading())
        self.run_for(1.5)
        self.assertEqual(self.imu.state, "ok")
        self.assertEqual(self.imu.chip, "ISM330DHCX")
        self.assertEqual(self.chip.resets, 1)
        self.assertEqual(self.chip.registers[0x11], 0x6C)          # gyro 416 Hz, 2000 dps
        self.assertEqual(self.chip.registers[0x18] & 0x02, 0x02)   # I3C off / DEVICE_CONF
        # Sitting still with a biased gyro must not drift.
        self.run_for(8.0)
        self.assertAlmostEqual(self.imu.heading(), 0.0, delta=1.0)

    def test_it_follows_a_left_turn(self):
        self.run_for(2.0)
        self.world.rate = 60
        self.run_for(1.5)
        self.world.rate = 0
        self.run_for(0.1)
        self.assertAlmostEqual(self.imu.heading(), 90.0, delta=2.0)
        self.assertAlmostEqual(self.imu.rate(), 0.0, delta=1.0)

    def test_tilting_is_not_turning(self):
        self.run_for(2.0)
        self.world.pitch = 12.0     # driven onto a ramp
        self.run_for(4.0)
        self.assertAlmostEqual(self.imu.pitch(), 12.0, delta=1.5)
        self.assertAlmostEqual(self.imu.heading(), 0.0, delta=2.0)

    def test_calibration_waits_for_the_robot_to_stop(self):
        self.world.rate = 40
        self.run_for(2.5)
        self.assertEqual(self.imu.state, "calibrating")
        self.assertIn("moving", self.imu.describe())
        self.world.rate = 0
        self.run_for(2.5)
        self.assertEqual(self.imu.state, "ok")

    def test_calibrate_measures_the_gyro_again_and_keeps_the_heading(self):
        self.run_for(2.0)
        self.world.rate = 60        # a half-second quarter turn
        self.run_for(0.5)
        self.world.rate = 0
        self.bridge.calibrate()
        self.run_for(0.2)
        self.assertEqual(self.imu.state, "calibrating")
        self.run_for(1.5)
        self.assertEqual(self.imu.state, "ok")
        self.assertAlmostEqual(self.imu.heading(), 30.0, delta=2.0)


class SensorProblemTests(BridgeTestCase):
    def test_a_missing_sensor_says_what_to_check_and_what_answered(self):
        bridge = self.build(imus=[NINE_AXIS])
        self.board.attach(0x6A, SimLsm6(self.world))
        self.run_for(2.5)
        imu = bridge.imu()
        self.assertEqual(imu.state, "missing")
        self.assertIsNone(imu.heading())
        self.assertIn("configured sensor connection and address", imu.describe())
        bridge.scan()
        self.run_for(0.1)
        self.assertIn("0x6A", imu.describe())

    def test_a_sensor_plugged_in_later_is_picked_up(self):
        bridge = self.build(imus=[SIX_AXIS])
        self.run_for(1.0)
        self.assertEqual(bridge.imu().state, "missing")
        self.board.attach(0x6A, SimLsm6(self.world))
        self.run_for(4.0)
        self.assertEqual(bridge.imu().state, "ok")

    def test_the_wrong_chip_at_an_address_is_named(self):
        bridge = self.build(imus=[NINE_AXIS])
        self.board.attach(0x28, SimBno055(self.world, chip_id=0x4A))
        self.run_for(2.5)
        self.assertEqual(bridge.imu().state, "wrong-chip")
        self.assertIn("0x4A", bridge.imu().describe())

    def test_a_sensor_that_goes_quiet_is_retried(self):
        bridge = self.build(imus=[SIX_AXIS])
        chip = self.board.attach(0x6A, SimLsm6(self.world))
        self.run_for(2.0)
        self.assertEqual(bridge.imu().state, "ok")
        chip.present = False
        self.run_for(1.0)
        self.assertIn(bridge.imu().state, {"failed", "missing", "starting"})
        self.assertIsNone(bridge.imu().heading())
        chip.present = True
        self.run_for(4.0)
        self.assertEqual(bridge.imu().state, "ok")


class OldFirmwareTests(BridgeTestCase):
    def test_the_original_sketch_still_reads_pins_and_asks_for_an_update(self):
        class OldSketch(FakeGiga):
            """The first bridge sketch: pins only, and it never says a version."""

            def tick(self, milliseconds=20):
                self.ms += milliseconds
                if self.ms >= self._next_reading:
                    self._next_reading = self.ms + 100
                    self._send({"protocol": PROTOCOL_V1, "board": "arduino_giga_r1_wifi",
                                "values": self._pin_values()})

            def _handle(self, line):
                self.commands.append(line)
                if line.startswith("MM1 CONFIG "):
                    self.declared_pins = [
                        (item.split(":")[0], item.split(":")[1])
                        for item in line[11:].split(",") if ":" in item
                    ]

        board = OldSketch()
        board.pins["A0"] = 99
        bridge = self.build([GigaPin("A0", "Pot", kind="analog")], imus=[NINE_AXIS], board=board)
        self.run_for(2.0, step_ms=100)
        self.assertIn("MM1 CONFIG A0:A", board.commands)
        self.assertEqual(bridge.value("Pot"), 99.0)
        self.assertEqual(bridge.imu().state, "update-firmware")
        self.assertIn("motionmodule giga flash", bridge.status)

    def test_firmware_from_another_motionmodule_asks_to_be_flashed(self):
        board = FakeGiga(firmware="2.0.0", protocol="motionmodule-sensor-v2")
        bridge = self.build([GigaPin("D2", "Limit")], board=board)
        self.run_for(2.0)
        self.assertIn("motionmodule giga flash", bridge.status)
        self.assertIn("motionmodule-sensor-v2", bridge.status)
        # It is never asked to fall back to the original pins-only protocol.
        self.assertFalse(any(command.startswith("MM1") for command in board.commands))

    def test_older_current_firmware_asks_for_the_bundled_version(self):
        board = FakeGiga(firmware="2.9.0")
        bridge = self.build([GigaPin("D2", "Limit")], board=board)
        self.run_for(0.2)
        self.assertIn(f"ships {GIGA_FIRMWARE_VERSION}", bridge.status)


class ModuleGigaTests(unittest.TestCase):
    def test_simulated_robots_never_open_the_board(self):
        with MotionModule(default_config(), gpio=MockGPIO()) as module:
            self.assertFalse(module.hardware)
            giga = module.giga(pins=[GigaPin("D2", "Limit")], imus=[NINE_AXIS])
            self.assertTrue(giga.simulated)
            self.assertFalse(giga.poll())
            self.assertNotIn(giga, active_bridges())
            self.assertIsNone(giga.imu().heading())
            self.assertEqual(giga.imu().state, "simulated")
            self.assertEqual(giga.snapshot().bridge, "simulated")

    def test_the_giga_is_set_up_once(self):
        pins = [GigaPin("D2", "Limit")]
        with MotionModule(default_config(), gpio=MockGPIO()) as module:
            giga = module.giga(pins=pins)
            self.assertIs(module.giga(pins=list(pins)), giga)
            with self.assertRaisesRegex(ValueError, "sensors.py"):
                module.giga(pins=[GigaPin("D3", "Other")])

    def test_closing_the_module_closes_the_bridge(self):
        closed = []
        module = MotionModule(default_config(), gpio=MockGPIO())
        giga = module.giga(pins=[GigaPin("D2", "Limit")])
        giga.close = lambda: closed.append(True)
        module.close()
        self.assertTrue(closed)


if __name__ == "__main__":
    unittest.main()
