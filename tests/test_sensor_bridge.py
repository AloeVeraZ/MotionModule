"""The Pi side of the Arduino GIGA sensor board.

These tests exercise GPIO input declarations and USB recovery against a
simulated board (fake_giga.py). The IMU is tested on its own Pi I2C path.
"""

import time
import unittest

from fake_giga import Clock, FakeGiga, World, run
from motion_module.config import default_config
from motion_module.controller import MotionModule
from motion_module.gpio import MockGPIO
from motion_module.sensor_bridge import (
    GIGA_FIRMWARE_VERSION,
    PROTOCOL_V1,
    GigaPin,
    GigaR1Bridge,
    active_bridges,
)


GIGA = {
    "board_id": "arduino_giga_r1_wifi", "name": "Arduino GIGA R1 WiFi",
    "connected": True, "serial": "ABC", "port": "/dev/ttyACM0", "mode": "sketch",
}
class BridgeTestCase(unittest.TestCase):
    """A bridge wired to a simulated GIGA, with a clock the test moves."""

    def build(self, pins=(), board=None, **options):
        self.clock = Clock()
        self.world = World()
        self.board = board if board is not None else FakeGiga(self.world)
        options.setdefault("discovery", lambda: [dict(GIGA)])
        bridge = GigaR1Bridge(
            pins, autostart=False, clock=self.clock,
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

    def test_duplicate_and_empty_pin_declarations_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "only once"):
            GigaR1Bridge([GigaPin("D2", "A"), GigaPin("D2", "B")])
        with self.assertRaisesRegex(ValueError, "own name"):
            GigaR1Bridge([GigaPin("D2", "Same"), GigaPin("D3", "same")])
        with self.assertRaisesRegex(ValueError, "at least one"):
            GigaR1Bridge(autostart=False)


class ProtocolTests(BridgeTestCase):
    def test_the_board_is_told_only_which_input_pins_to_read(self):
        bridge = self.build([GigaPin("A0", "Pot", kind="analog"), GigaPin("D22", "Beam", pull="up")])
        bridge.poll()
        self.assertEqual(self.board.commands[0], f"MM3 CONFIG {bridge.config_id} 20 A0:A,D22:U -")
        self.assertEqual(self.board.streams, [])
        self.run_for(1)
        self.assertFalse(any(command.startswith("MM3 I2C") for command in self.board.commands))

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
        bridge = self.build([GigaPin("D2", "Limit")])
        self.board.pins["D2"] = 1
        self.run_for(0.2)
        self.assertTrue(bridge.value("Limit"))
        self.board.restart()
        self.run_for(1.2)
        self.assertEqual(self.board.config_id, bridge.config_id)
        self.assertTrue(bridge.value("Limit"))

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
        bridge = self.build([GigaPin("A0", "Pot", kind="analog")], board=board)
        self.run_for(2.0, step_ms=100)
        self.assertIn("MM1 CONFIG A0:A", board.commands)
        self.assertEqual(bridge.value("Pot"), 99.0)
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
            giga = module.giga(pins=[GigaPin("D2", "Limit")])
            self.assertTrue(giga.simulated)
            self.assertFalse(giga.poll())
            self.assertNotIn(giga, active_bridges())
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
