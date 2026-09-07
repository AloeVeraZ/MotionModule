import json
import unittest

from motion_module.sensor_bridge import GigaPin, GigaR1Bridge


class FakeSerial:
    def __init__(self, lines):
        self.lines = list(lines)
        self.writes = []
        self.closed = False

    @property
    def in_waiting(self):
        return len(self.lines)

    def write(self, value):
        self.writes.append(value)

    def readline(self, _maximum):
        return self.lines.pop(0) if self.lines else b""

    def close(self):
        self.closed = True


class SensorBridgeTests(unittest.TestCase):
    def test_giga_pin_validation_uses_the_exposed_input_ranges(self):
        self.assertEqual(GigaPin("a7", "Pot", kind="analog").pin, "A7")
        self.assertEqual(GigaPin("d75", "Limit").pin, "D75")
        with self.assertRaisesRegex(ValueError, "A0-A7"):
            GigaPin("A8", "Not an ADC pin", kind="analog")

    def test_giga_bridge_auto_discovers_configures_and_reads_pin_values(self):
        packet = json.dumps({
            "protocol": "motionmodule-sensor-v1",
            "values": {"A0": 2048, "D22": 1},
        }).encode() + b"\n"
        serial = FakeSerial([packet])
        device = {
            "board_id": "arduino_giga_r1_wifi", "name": "Arduino GIGA R1 WiFi",
            "connected": True, "serial": "ABC", "port": "/dev/ttyACM0",
        }
        bridge = GigaR1Bridge(
            [
                GigaPin("A0", "Pot", kind="analog", minimum=0, maximum=4095),
                GigaPin("D22", "Beam", kind="digital", pull="up"),
            ],
            discovery=lambda: [device],
            serial_factory=lambda *_args, **_kwargs: serial,
        )
        snapshot = bridge.snapshot()
        self.assertTrue(snapshot.connected)
        self.assertEqual(snapshot.bridge, "streaming")
        self.assertEqual(snapshot.pins[0].value, 2048.0)
        self.assertIs(snapshot.pins[1].value, True)
        self.assertEqual(serial.writes, [b"MM1 CONFIG A0:A,D22:U\n"])
        bridge.close()
        self.assertTrue(serial.closed)

    def test_missing_giga_is_reported_offline_without_opening_a_port(self):
        bridge = GigaR1Bridge(
            [GigaPin("D2", "Limit")], discovery=lambda: [],
            serial_factory=lambda *_args, **_kwargs: self.fail("serial should not open"),
        )
        snapshot = bridge.snapshot()
        self.assertFalse(snapshot.connected)
        self.assertEqual(snapshot.pins[0].status, "offline")


if __name__ == "__main__":
    unittest.main()
