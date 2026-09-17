import json
import threading
import time
import unittest

from motion_module.controller import MotionModule
from motion_module.config import default_config
from motion_module.gpio import MockGPIO
from motion_module.sensor_bridge import (
    GIGA_FIRMWARE_VERSION,
    GigaIMU,
    GigaPin,
    GigaR1Bridge,
    active_bridges,
)


GIGA = {
    "board_id": "arduino_giga_r1_wifi", "name": "Arduino GIGA R1 WiFi",
    "connected": True, "serial": "ABC", "port": "/dev/ttyACM0", "mode": "sketch",
}


class FakeSerial:
    """A USB serial port whose other end is scripted by the test."""

    def __init__(self):
        self.incoming = bytearray()
        self.writes = []
        self.closed = False

    def feed(self, *payloads):
        for payload in payloads:
            text = payload if isinstance(payload, str) else json.dumps(payload)
            self.incoming += text.encode() + b"\n"

    @property
    def in_waiting(self):
        return len(self.incoming)

    def read(self, size):
        data = bytes(self.incoming[:size])
        del self.incoming[:size]
        return data

    def write(self, value):
        self.writes.append(value)

    def close(self):
        self.closed = True


def reading(bridge, values=None, imus=None, **extra):
    return {
        "protocol": "motionmodule-sensor-v2", "firmware": GIGA_FIRMWARE_VERSION,
        "config": bridge.config_id, "seq": 1, "ms": 10,
        "values": values or {}, "imus": imus or [], **extra,
    }


def bno055(yaw=0.0, state="ok", **extra):
    entry = {"type": "bno055", "addr": 0x28, "state": state, "id": 0xA0}
    if state == "ok":
        entry.update({"cal": 1, "yaw": yaw, "rate": 0.0, "pitch": 1.5, "roll": -2.0, "levels": [0, 3, 1, 0]})
    entry.update(extra)
    return entry


class BridgeTestCase(unittest.TestCase):
    def make(self, pins=(), imus=(), **options):
        self.port = FakeSerial()
        options.setdefault("discovery", lambda: [dict(GIGA)])
        bridge = GigaR1Bridge(
            pins, imus=imus, autostart=False,
            serial_factory=lambda *_args, **_kwargs: self.port, **options,
        )
        self.addCleanup(bridge.close)
        return bridge


class DeclarationTests(unittest.TestCase):
    def test_giga_pin_validation_uses_the_exposed_input_ranges(self):
        self.assertEqual(GigaPin("a7", "Pot", kind="analog").pin, "A7")
        self.assertEqual(GigaPin("d75", "Limit").pin, "D75")
        with self.assertRaisesRegex(ValueError, "A0-A7"):
            GigaPin("A8", "Not an ADC pin", kind="analog")

    def test_imus_default_to_their_boards_addresses(self):
        self.assertEqual(GigaIMU("BNO055", "Main").address, 0x28)
        self.assertEqual(GigaIMU("ISM330DHCX", "Six").bridge_spec, "LSM6@6A")
        self.assertEqual(GigaIMU("lsm6dsox", "Six", address=0x6B).bridge_spec, "LSM6@6B")
        self.assertEqual(GigaIMU("bno055", "Nine", compass=True).bridge_spec, "BNO055@28:NDOF")

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


class StreamingTests(BridgeTestCase):
    def test_bridge_configures_the_board_and_reads_pins_as_on_off_and_numbers(self):
        bridge = self.make(
            [GigaPin("A0", "Pot", kind="analog", minimum=0, maximum=4095),
             GigaPin("D22", "Beam", pull="up")],
            imus=[GigaIMU("bno055", "Main IMU")],
        )
        self.assertTrue(bridge.poll())
        self.assertEqual(
            self.port.writes[0],
            f"MM2 CONFIG {bridge.config_id} A0:A,D22:U BNO055@28\n".encode(),
        )
        self.port.feed(reading(bridge, {"A0": 2048, "D22": 1}, [bno055(12.5)]))
        bridge.poll()
        snapshot = bridge.snapshot()
        self.assertTrue(snapshot.connected)
        self.assertEqual(snapshot.bridge, "streaming")
        self.assertEqual(snapshot.pins[0].value, 2048.0)
        self.assertIs(snapshot.pins[1].value, True)
        self.assertEqual(snapshot.pins[2].name, "Main IMU heading")
        self.assertEqual(snapshot.pins[2].value, 12.5)
        self.assertEqual(bridge.value("Beam"), True)
        self.assertEqual(bridge.value("A0"), 2048.0)
        self.assertEqual(bridge.firmware, GIGA_FIRMWARE_VERSION)
        bridge.close()
        self.assertTrue(self.port.closed)

    def test_lines_split_across_reads_are_joined(self):
        bridge = self.make([GigaPin("D2", "Limit")])
        bridge.poll()
        line = json.dumps(reading(bridge, {"D2": 0})).encode() + b"\n"
        self.port.incoming += line[:17]
        bridge.poll()
        self.assertIsNone(bridge.value("Limit"))
        self.port.incoming += line[17:]
        bridge.poll()
        self.assertIs(bridge.value("Limit"), False)

    def test_readings_for_another_configuration_are_ignored_and_config_is_resent(self):
        bridge = self.make([GigaPin("D2", "Limit")])
        bridge.poll()
        stale = reading(bridge, {"D2": 1})
        stale["config"] = bridge.config_id + 1
        self.port.feed(stale)
        bridge.poll()
        self.assertIsNone(bridge.value("Limit"))
        bridge._config_sent_at -= 2.0
        bridge.poll()
        self.assertEqual(self.port.writes[-1], self.port.writes[0])

    def test_stale_readings_turn_into_none(self):
        bridge = self.make([GigaPin("D2", "Limit")], stale_after=0.1)
        bridge.poll()
        self.port.feed(reading(bridge, {"D2": 1}))
        bridge.poll()
        self.assertIs(bridge.value("Limit"), True)
        time.sleep(0.15)
        self.assertIsNone(bridge.value("Limit"))
        self.assertFalse(bridge.streaming)

    def test_missing_giga_is_reported_offline_without_opening_a_port(self):
        bridge = GigaR1Bridge(
            [GigaPin("D2", "Limit")], discovery=lambda: [], autostart=False,
            serial_factory=lambda *_args, **_kwargs: self.fail("serial should not open"),
        )
        self.assertFalse(bridge.poll())
        snapshot = bridge.snapshot()
        self.assertFalse(snapshot.connected)
        self.assertEqual(snapshot.pins[0].status, "offline")
        self.assertIn("Plug it into", snapshot.detail)

    def test_a_giga_in_its_bootloader_is_not_opened(self):
        bridge = GigaR1Bridge(
            [GigaPin("D2", "Limit")], autostart=False,
            discovery=lambda: [{**GIGA, "port": "", "mode": "bootloader"}],
            serial_factory=lambda *_args, **_kwargs: self.fail("serial should not open"),
        )
        self.assertFalse(bridge.poll())
        self.assertIn("motionmodule giga flash", bridge.status)

    def test_permission_errors_explain_the_dialout_group(self):
        class SerialException(OSError):
            """pyserial's own error, which wraps the refused open's errno."""

        def denied(*_args, **_kwargs):
            raise SerialException(13, "could not open port /dev/ttyACM0: [Errno 13] Permission denied")

        bridge = GigaR1Bridge([GigaPin("D2", "Limit")], autostart=False,
                              discovery=lambda: [dict(GIGA)], serial_factory=denied)
        self.assertFalse(bridge.poll())
        self.assertIn("dialout", bridge.status)

    def test_a_lost_port_is_closed_and_found_again(self):
        bridge = self.make([GigaPin("D2", "Limit")])
        bridge.poll()
        self.port.feed(reading(bridge, {"D2": 1}))
        bridge.poll()

        def unplugged(_size):
            raise OSError("device disconnected")

        self.port.read = unplugged
        bridge.poll()
        self.assertTrue(self.port.closed)
        self.assertIsNone(bridge.value("Limit"))
        self.assertIn("Lost", bridge.status)

    def test_board_rejections_are_shown(self):
        bridge = self.make([GigaPin("D2", "Limit")])
        bridge.poll()
        self.port.feed({"protocol": "motionmodule-sensor-v2", "event": "error",
                        "firmware": "2.0.0", "message": "pin list not understood"})
        bridge.poll()
        self.assertIn("pin list not understood", bridge.status)

    def test_background_thread_reads_without_being_polled(self):
        port = FakeSerial()
        bridge = GigaR1Bridge([GigaPin("D2", "Limit")], discovery=lambda: [dict(GIGA)],
                              serial_factory=lambda *_args, **_kwargs: port)
        self.addCleanup(bridge.close)
        bridge.start()
        self.assertIn(bridge, active_bridges())
        port.feed(reading(bridge, {"D2": 1}))
        deadline = time.monotonic() + 2
        while bridge.value("Limit") is None and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertIs(bridge.value("Limit"), True)
        bridge.close()
        self.assertNotIn(bridge, active_bridges())
        self.assertTrue(port.closed)

    def test_two_bridges_cannot_read_the_same_board(self):
        first = GigaR1Bridge([GigaPin("D2", "Limit")], discovery=lambda: [])
        second = GigaR1Bridge([GigaPin("D3", "Other")], discovery=lambda: [])
        self.addCleanup(first.close)
        self.addCleanup(second.close)
        first.start()
        with self.assertRaisesRegex(RuntimeError, "sensors.py"):
            second.start()

    def test_commands_are_written_by_the_reader(self):
        bridge = self.make(imus=[GigaIMU("ism330dhcx", "Six")])
        bridge.poll()
        bridge.calibrate()
        bridge.poll()
        self.assertEqual(self.port.writes[-1], b"MM2 CALIBRATE\n")


class IMUTests(BridgeTestCase):
    def setUp(self):
        self.bridge = self.make(imus=[GigaIMU("bno055", "Main IMU"), GigaIMU("ism330dhcx", "Backup IMU")])
        self.bridge.poll()
        self.imu = self.bridge.imu("Main IMU")

    def send(self, *imus):
        self.port.feed(reading(self.bridge, imus=list(imus)))
        self.bridge.poll()

    def test_heading_wraps_counter_clockwise_positive_and_zeroes(self):
        self.send(bno055(190.0), {"type": "lsm6", "addr": 0x6A, "state": "calibrating", "id": 0x6B})
        self.assertAlmostEqual(self.imu.heading(), -170.0)
        self.assertAlmostEqual(self.imu.total_rotation(), 190.0)
        self.assertEqual(self.imu.pitch(), 1.5)
        self.imu.zero()
        self.assertAlmostEqual(self.imu.heading(), 0.0)
        self.send(bno055(280.0))
        self.assertAlmostEqual(self.imu.heading(), 90.0)
        self.imu.zero(45)
        self.assertAlmostEqual(self.imu.heading(), 45.0)

    def test_calibrating_imus_have_no_heading_but_are_present(self):
        self.send(bno055(5.0), {"type": "lsm6", "addr": 0x6A, "state": "calibrating", "id": 0x6B, "moving": 1})
        backup = self.bridge.imu("Backup IMU")
        self.assertIsNone(backup.heading())
        self.assertEqual(backup.state, "calibrating")
        self.assertEqual(backup.chip, "ISM330DHCX")
        reading_ = backup.reading()
        self.assertTrue(reading_.connected)
        self.assertFalse(reading_.calibrated)
        self.assertIn("Keep it still", reading_.detail)

    def test_zero_before_streaming_applies_to_the_first_reading(self):
        self.imu.zero(10)
        self.send(bno055(300.0))
        self.assertAlmostEqual(self.imu.heading(), 10.0)

    def test_missing_imu_explains_the_wiring_and_what_did_answer(self):
        self.send(bno055(state="missing", seen=[0x29, 0x6A]))
        self.assertIsNone(self.imu.heading())
        self.assertEqual(self.imu.state, "missing")
        detail = self.imu.describe()
        self.assertIn("SDA 20", detail)
        self.assertIn("0x29", detail)

    def test_driver_station_reading_matches_robot_code(self):
        self.send(bno055(-30.0))
        panel = self.imu.reading()
        self.assertTrue(panel.connected)
        self.assertTrue(panel.calibrated)
        self.assertAlmostEqual(panel.yaw, self.imu.heading())
        self.assertIn("gyro 3/3", panel.detail)

    def test_a_board_restart_clears_the_zero(self):
        self.send(bno055(50.0))
        self.imu.zero()
        self.port.feed({"protocol": "motionmodule-sensor-v2", "event": "hello", "firmware": "2.0.0"})
        self.bridge.poll()
        self.send(bno055(0.0))
        self.assertAlmostEqual(self.imu.heading(), 0.0)

    def test_imu_names_must_exist(self):
        with self.assertRaisesRegex(ValueError, "Backup IMU"):
            self.bridge.imu("Spare")
        with self.assertRaisesRegex(ValueError, "Name the IMU"):
            self.bridge.imu()


class OriginalSketchTests(BridgeTestCase):
    def test_original_sketch_gets_the_original_configuration_and_imus_ask_for_an_update(self):
        bridge = self.make([GigaPin("A0", "Pot", kind="analog")], imus=[GigaIMU("bno055", "Main IMU")])
        bridge.poll()
        self.port.feed({"protocol": "motionmodule-sensor-v1", "board": "arduino_giga_r1_wifi", "values": {}})
        bridge.poll()
        bridge.poll()
        self.assertEqual(self.port.writes[-1], b"MM1 CONFIG A0:A\n")
        self.port.feed({"protocol": "motionmodule-sensor-v1", "board": "arduino_giga_r1_wifi", "values": {"A0": 99}})
        bridge.poll()
        self.assertEqual(bridge.value("Pot"), 99.0)
        self.assertEqual(bridge.imu().state, "update-firmware")
        self.assertIn("motionmodule giga flash", bridge.status)

    def test_current_firmware_left_in_the_old_mode_is_switched_back(self):
        bridge = self.make([GigaPin("D2", "Limit")])
        bridge.poll()
        writes = len(self.port.writes)
        self.port.feed({"protocol": "motionmodule-sensor-v1", "firmware": "2.0.0", "values": {"D2": 1}})
        bridge.poll()
        self.assertIsNone(bridge.value("Limit"))  # old-mode readings are not trusted
        bridge._config_sent_at -= 2.0              # the once-a-second retry comes due
        bridge.poll()
        self.assertEqual(len(self.port.writes), writes + 1)
        self.assertTrue(self.port.writes[-1].startswith(b"MM2 CONFIG"))

    def test_older_current_firmware_asks_for_the_bundled_version(self):
        bridge = self.make([GigaPin("D2", "Limit")])
        bridge.poll()
        old = reading(bridge, {"D2": 1})
        old["firmware"] = "1.9.0"
        self.port.feed(old)
        bridge.poll()
        self.assertIn(f"ships {GIGA_FIRMWARE_VERSION}", bridge.status)


class ModuleGigaTests(unittest.TestCase):
    def test_simulated_robots_never_open_the_board(self):
        with MotionModule(default_config(), gpio=MockGPIO()) as module:
            self.assertFalse(module.hardware)
            giga = module.giga(pins=[GigaPin("D2", "Limit")], imus=[GigaIMU("bno055", "Main IMU")])
            self.assertTrue(giga.simulated)
            self.assertFalse(giga.poll())
            self.assertNotIn(giga, active_bridges())
            self.assertIsNone(giga.imu().heading())
            self.assertEqual(giga.snapshot().bridge, "simulated")

    def test_the_giga_is_set_up_once(self):
        pins = [GigaPin("D2", "Limit")]
        with MotionModule(default_config(), gpio=MockGPIO()) as module:
            giga = module.giga(pins=pins)
            self.assertIs(module.giga(pins=list(pins)), giga)
            with self.assertRaisesRegex(ValueError, "sensors.py"):
                module.giga(pins=[GigaPin("D3", "Other")])

    def test_closing_the_module_closes_the_bridge(self):
        closed = threading.Event()
        module = MotionModule(default_config(), gpio=MockGPIO())
        giga = module.giga(pins=[GigaPin("D2", "Limit")])
        giga.close = closed.set
        module.close()
        self.assertTrue(closed.is_set())


if __name__ == "__main__":
    unittest.main()
