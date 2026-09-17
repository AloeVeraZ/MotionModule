"""The GIGA sensor firmware, its prebuilt binary, and flashing it from the Pi.

The last group compiles the real sketch for this computer and runs it against
simulated IMUs (tests/firmware/harness.cpp). It needs a C++ compiler, so it
runs only when asked:

    MOTIONMODULE_FIRMWARE_TESTS=1 python -m unittest tests.test_giga_firmware

MOTIONMODULE_CXX picks the compiler (for example "zig c++"); otherwise c++,
g++, or clang++ from PATH is used.
"""

import hashlib
import json
import os
import re
import shlex
import shutil
import struct
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from motion_module.errors import MotionModuleError
from motion_module.giga_firmware import (
    FLASH_ADDRESS,
    bundled_firmware,
    find_boards,
    flash_giga,
)
from fake_giga import Clock, FakeGiga
from motion_module.sensor_bridge import (
    GIGA_FIRMWARE_VERSION,
    PROTOCOL,
    PROTOCOL_V1,
    GigaIMU,
    GigaPin,
    GigaR1Bridge,
)


ROOT = Path(__file__).resolve().parents[1]
FIRMWARE = ROOT / "firmware"
SKETCH = FIRMWARE / "giga_sensor_bridge" / "giga_sensor_bridge.ino"


class PrebuiltFirmwareTests(unittest.TestCase):
    def test_sketch_version_matches_the_bridge(self):
        source = SKETCH.read_text(encoding="utf-8")
        self.assertIn(f'const char BRIDGE_VERSION[] = "{GIGA_FIRMWARE_VERSION}";', source)
        self.assertIn(PROTOCOL_V1, source)
        self.assertIn(PROTOCOL, source)

    def test_binary_was_built_from_this_sketch(self):
        """Change the sketch, then run python firmware/build.py to rebuild the binary."""

        manifest = json.loads((FIRMWARE / "giga_sensor_bridge.json").read_text(encoding="utf-8"))
        source = SKETCH.read_text(encoding="utf-8").replace("\r\n", "\n")
        self.assertEqual(manifest["source_sha256"], hashlib.sha256(source.encode("utf-8")).hexdigest(),
                         "firmware/giga_sensor_bridge.bin is older than the sketch: run python firmware/build.py")
        self.assertEqual(manifest["version"], GIGA_FIRMWARE_VERSION)
        self.assertEqual(manifest["flash_address"], FLASH_ADDRESS)
        bundled = bundled_firmware()
        self.assertEqual(bundled["bytes"], manifest["bytes"])

    def test_binary_starts_where_dfu_util_writes_it(self):
        data = (FIRMWARE / "giga_sensor_bridge.bin").read_bytes()
        stack, reset = struct.unpack_from("<II", data, 0)
        start = int(FLASH_ADDRESS, 16)
        self.assertTrue(0x20000000 <= stack <= 0x24080000, hex(stack))
        self.assertTrue(start <= reset < start + len(data), hex(reset))
        self.assertIn(GIGA_FIRMWARE_VERSION.encode(), data)

    def test_a_damaged_binary_is_refused(self):
        with tempfile.TemporaryDirectory() as directory:
            folder = Path(directory)
            shutil.copy(FIRMWARE / "giga_sensor_bridge.json", folder)
            data = bytearray((FIRMWARE / "giga_sensor_bridge.bin").read_bytes())
            data[100] ^= 0xFF
            (folder / "giga_sensor_bridge.bin").write_bytes(bytes(data))
            with self.assertRaisesRegex(MotionModuleError, "checksum"):
                bundled_firmware(folder)


def usb(product, port="", node="/dev/bus/usb/001/005"):
    return {"vendor_id": "2341", "product_id": product, "path": "1-1.2", "serial": "GIGA1",
            "serial_port": port, "device_node": node}


class FakeUsb:
    """A GIGA that reboots into its bootloader when touched and back after dfu-util."""

    def __init__(self, mode="sketch", enters_bootloader=True, returns=True):
        self.mode = mode
        self.enters_bootloader = enters_bootloader
        self.returns = returns
        self.commands = []
        self.opened = []

    def inventory(self):
        if self.mode is None:
            return {"available": True, "devices": []}
        product = "0366" if self.mode == "bootloader" else "0266"
        port = "/dev/ttyACM0" if self.mode == "sketch" else ""
        return {"available": True, "devices": [usb(product, port)]}

    def serial(self, port, baudrate, **_options):
        test = self

        class Port:
            def __init__(self):
                test.opened.append((port, baudrate))
                self.sent = b'{"protocol":"motionmodule-sensor-v2","event":"hello","firmware":"%s"}\n' % (
                    GIGA_FIRMWARE_VERSION.encode()
                )

            def close(self):
                if baudrate == 1200 and test.enters_bootloader:
                    test.mode = "bootloader"

            def write(self, _data):
                pass

            def read(self, _size):
                data, self.sent = self.sent, b""
                return data

        return Port()

    def run(self, command, **_options):
        self.commands.append(command)
        if self.returns:
            self.mode = "sketch"
        return subprocess.CompletedProcess(
            command, 74,
            stdout="Download\t[=========================] 100%  140864 bytes\nDownload done.\n",
            stderr="dfu-util: Error during download get_status\n",
        )


class FlashTests(unittest.TestCase):
    def flash(self, board, **options):
        messages = []
        clock = iter(range(0, 100000)).__next__
        options.setdefault("which", lambda _name: "/usr/bin/dfu-util")
        result = flash_giga(
            log=messages.append, inventory=board.inventory, run=board.run,
            serial_factory=board.serial, sleep=lambda _seconds: None, clock=clock, **options,
        )
        return result, messages

    def test_running_board_is_touched_flashed_and_checked(self):
        board = FakeUsb()
        with mock.patch("motion_module.giga_firmware.os.access", return_value=True):
            result, messages = self.flash(board)
        self.assertIn(("/dev/ttyACM0", 1200), board.opened)
        self.assertEqual(board.commands, [[
            "/usr/bin/dfu-util", "--device", "0x2341:0x0366", "-D", bundled_firmware()["path"],
            "-a0", "--dfuse-address=0x08040000:leave",
        ]])
        self.assertTrue(result["verified"])
        self.assertEqual(result["version"], GIGA_FIRMWARE_VERSION)
        self.assertTrue(any("bootloader" in message for message in messages))

    def test_a_board_already_in_its_bootloader_is_flashed_directly(self):
        board = FakeUsb(mode="bootloader")
        with mock.patch("motion_module.giga_firmware.os.access", return_value=True):
            result, _messages = self.flash(board)
        self.assertNotIn(("/dev/ttyACM0", 1200), board.opened)
        self.assertEqual(len(board.commands), 1)
        self.assertTrue(result["verified"])

    def test_missing_pieces_are_explained(self):
        with self.assertRaisesRegex(MotionModuleError, "apt install dfu-util"):
            self.flash(FakeUsb(), which=lambda _name: None)
        with self.assertRaisesRegex(MotionModuleError, "plugged into the Pi"):
            self.flash(FakeUsb(mode=None))
        with self.assertRaisesRegex(MotionModuleError, "RESET button twice"):
            self.flash(FakeUsb(enters_bootloader=False))

    def test_usb_permission_problems_point_at_the_installer(self):
        with mock.patch("motion_module.giga_firmware.os.access", return_value=False):
            with self.assertRaisesRegex(MotionModuleError, "installer"):
                self.flash(FakeUsb(mode="bootloader"))

    def test_a_failed_write_is_an_error_even_though_leave_errors_are_not(self):
        board = FakeUsb(mode="bootloader")

        def refuse(command, **_options):
            return subprocess.CompletedProcess(command, 74, stdout="", stderr="dfu-util: No DFU capable USB device available\n")

        board.run = refuse
        with mock.patch("motion_module.giga_firmware.os.access", return_value=True):
            with self.assertRaisesRegex(MotionModuleError, "No DFU capable"):
                self.flash(board)

    def test_board_that_does_not_come_back_needs_a_reset(self):
        with mock.patch("motion_module.giga_firmware.os.access", return_value=True):
            with self.assertRaisesRegex(MotionModuleError, "RESET button once"):
                self.flash(FakeUsb(mode="bootloader", returns=False))

    def test_two_boards_are_refused(self):
        inventory = {"devices": [usb("0266", "/dev/ttyACM0"), usb("0366")]}
        self.assertEqual([board["mode"] for board in find_boards(inventory)], ["sketch", "bootloader"])
        board = FakeUsb()
        board.inventory = lambda: inventory
        with self.assertRaisesRegex(MotionModuleError, "More than one"):
            self.flash(board)


def compiler() -> list[str] | None:
    configured = os.environ.get("MOTIONMODULE_CXX", "")
    if configured:
        return shlex.split(configured)
    for name in ("c++", "g++", "clang++"):
        found = shutil.which(name)
        if found:
            return [found]
    return None


@unittest.skipUnless(os.environ.get("MOTIONMODULE_FIRMWARE_TESTS") == "1" and compiler(),
                     "set MOTIONMODULE_FIRMWARE_TESTS=1 and provide a C++ compiler")
class FirmwareSimulationTests(unittest.TestCase):
    """The real firmware, compiled for this computer, against simulated chips.

    The firmware only moves bytes, so these tests check exactly that: the pins
    and registers the Pi asked for come back, one-off reads and writes reach
    the right chip, and nothing is invented along the way.
    """

    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory()
        cls.harness = Path(cls.directory.name) / ("harness.exe" if os.name == "nt" else "harness")
        subprocess.run(
            compiler() + [
                "-std=c++17", "-O1", f"-I{ROOT / 'tests' / 'firmware'}", f"-I{SKETCH.parent}",
                str(ROOT / "tests" / "firmware" / "harness.cpp"), "-o", str(cls.harness),
            ],
            check=True, capture_output=True, text=True,
        )

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def simulate(self, *script):
        result = subprocess.run([str(self.harness)], input="\n".join(script) + "\n",
                                capture_output=True, text=True, check=True, timeout=120)
        self.lines = result.stdout.splitlines()
        self.messages = []
        for line in self.lines:
            match = re.match(r"OUT (\d+) (.*)", line)
            if match:
                self.messages.append((int(match.group(1)), json.loads(match.group(2))))
        return self.messages

    def readings(self, since=0):
        return [(ms, message) for ms, message in self.messages if "seq" in message and "values" in message
                and ms >= since]

    def events(self, name):
        return [message for _ms, message in self.messages if message.get("event") == name]

    def last(self):
        return self.readings()[-1][1]

    CONFIG = "send MM3 CONFIG 7 20 A0:A,D22:U 28:1A:6,6A:22:12"

    def test_says_hello_until_configured_then_reads_at_the_asked_rate(self):
        self.simulate("run 2100", self.CONFIG, "run 1000")
        self.assertEqual([hello["firmware"] for hello in self.events("hello")], [GIGA_FIRMWARE_VERSION] * 2)
        configured = self.events("configured")[0]
        self.assertEqual(
            (configured["config"], configured["pins"], configured["streams"], configured["interval"]),
            (7, 2, 2, 20),
        )
        self.assertTrue(49 <= len(self.readings()) <= 51)
        self.simulate("send MM3 CONFIG 8 50 - -", "run 1000")
        self.assertTrue(19 <= len(self.readings()) <= 21)

    def test_pins_arrive_as_on_off_and_numbers_with_their_pulls_set(self):
        self.simulate("pin A0 3071", "pin D22 1", "send MM3 CONFIG 3 20 A0:A,D22:U,D5:N -", "run 100",
                      "pin D22 0", "run 100", "pinmode D22", "pinmode D5")
        self.assertEqual(self.readings()[0][1]["values"], {"A0": 3071, "D22": 1, "D5": 0})
        self.assertEqual(self.last()["values"]["D22"], 0)
        self.assertIn("PINMODE D22 2", self.lines)  # INPUT_PULLUP
        self.assertIn("PINMODE D5 3", self.lines)   # INPUT_PULLDOWN

    def test_registers_are_relayed_exactly_and_missing_chips_read_as_nothing(self):
        self.simulate("attach 40", "poke 40 26 171", "poke 40 27 205", self.CONFIG, "run 60")
        readings = self.last()["i2c"]
        self.assertEqual(readings["28:1a"], "abcd0000" + "0000")
        self.assertIsNone(readings["6a:22"])        # nothing is attached at 0x6A
        # A chip that stops answering reads as nothing, and the light says so.
        self.simulate("attach 40", self.CONFIG, "run 60", "quiet 40 1", "run 4060", "led")
        self.assertIsNone(self.last()["i2c"]["28:1a"])
        self.assertIn("LED 1 0 1", self.lines)      # magenta: check the wiring

    def test_one_off_reads_and_writes_reach_the_chip(self):
        self.simulate("attach 40", "poke 40 0 160", self.CONFIG, "run 60",
                      "send MM3 I2C 11 28 R 00 1", "send MM3 I2C 12 28 W 3D 08", "run 60", "peek 40 61")
        answers = {message["seq"]: message for message in self.events("i2c")}
        self.assertEqual(answers[11]["data"], "a0")
        self.assertEqual((answers[11]["addr"], answers[11]["reg"], answers[11]["ok"]), (40, 0, 1))
        self.assertEqual(answers[12]["ok"], 1)
        self.assertIn("PEEK 40 61 8", self.lines)   # the write landed in the chip
        # A chip that is not there is reported, not guessed at.
        self.simulate(self.CONFIG, "run 60", "send MM3 I2C 13 6a R 0F 1", "run 60")
        self.assertEqual(self.events("i2c")[0]["ok"], 0)

    def test_scan_lists_what_is_on_the_bus(self):
        self.simulate("attach 40", "attach 106", self.CONFIG, "run 60", "send MM3 SCAN 4", "run 60")
        self.assertEqual(self.events("scan")[0]["found"], [40, 106])

    def test_sending_the_same_configuration_again_does_not_interrupt_readings(self):
        self.simulate("attach 40", self.CONFIG, "run 500", self.CONFIG, "run 500")
        self.assertEqual(len(self.events("configured")), 2)
        gaps = [second - first for (first, _a), (second, _b) in zip(self.readings(), self.readings()[1:])]
        self.assertTrue(all(gap <= 40 for gap in gaps), gaps)

    def test_a_bad_configuration_is_rejected_and_the_old_one_kept(self):
        self.simulate("pin D2 1", "send MM3 CONFIG 1 20 D2:D -", "run 100",
                      "send MM3 CONFIG 2 20 D99:D -", "run 100",
                      "send MM3 CONFIG 3 20 - ZZ:00:4", "run 100")
        messages = [event["message"] for event in self.events("error")]
        self.assertIn("pin list not understood", messages)
        self.assertIn("I2C stream list not understood", messages)
        self.assertEqual(self.last()["config"], 1)

    def test_original_protocol_still_works_for_older_motionmodule(self):
        self.simulate("pin A0 1234", "send MM1 CONFIG A0:A", "run 1000")
        streamed = [message for _ms, message in self.messages
                    if message.get("protocol") == PROTOCOL_V1 and "values" in message]
        self.assertTrue(9 <= len(streamed) <= 11)
        self.assertEqual(streamed[0]["values"], {"A0": 1234})
        self.assertEqual(streamed[0]["firmware"], GIGA_FIRMWARE_VERSION)

    def test_nothing_is_sent_while_the_pi_has_the_port_closed(self):
        self.simulate("send MM3 CONFIG 1 20 D2:D -", "run 200", "host 0", "run 500", "host 1", "run 200")
        self.assertEqual([ms for ms, _message in self.readings() if 220 <= ms < 700], [])
        self.assertTrue(self.readings(since=700))

    def test_status_light(self):
        self.simulate("run 2060", "led")
        self.assertIn("LED 0 0 1", self.lines)   # blue blink: waiting for the Pi
        self.simulate("attach 40", self.CONFIG.replace("6A:22:12", "28:1A:6"), "run 2060", "led")
        self.assertIn("LED 0 1 0", self.lines)   # green blip: sending readings

    def test_the_firmware_and_the_pi_agree_on_the_protocol(self):
        """The bridge's own command line, and the firmware's own readings."""

        board = FakeGiga()   # only to open the bridge; the firmware answers below
        clock = Clock()
        bridge = GigaR1Bridge(
            [GigaPin("A0", "Arm", kind="analog"), GigaPin("D22", "Beam", pull="up")],
            imus=[GigaIMU("bno055", "Main IMU")], autostart=False, clock=clock,
            discovery=lambda: [{"board_id": "arduino_giga_r1_wifi", "port": "/dev/ttyACM0"}],
            serial_factory=lambda *_args, **_keywords: board,
        )
        self.addCleanup(bridge.close)
        bridge.poll()
        config = board.commands[0]

        # The firmware accepts exactly what the bridge sends.
        self.simulate("attach 40", "poke 40 26 171", "pin A0 2048", "pin D22 0",
                      f"send {config}", "run 100")
        configured = self.events("configured")[0]
        self.assertEqual(configured["config"], bridge.config_id)
        self.assertEqual((configured["pins"], configured["streams"]), (2, 2))

        # And the bridge accepts exactly what the firmware sends back.
        for _ms, message in self.readings():
            board.incoming += json.dumps(message).encode() + b"\n"
        bridge.poll()
        self.assertEqual(bridge.value("Arm"), 2048.0)
        self.assertIs(bridge.value("Beam"), False)
        self.assertTrue(bridge.streaming)
        self.assertIn("Streaming", bridge.status)
        # Seeing its own configuration, the bridge starts setting the IMU up.
        bridge.poll()
        self.assertTrue(any(command.startswith("MM3 I2C") for command in board.commands))


if __name__ == "__main__":
    unittest.main()
