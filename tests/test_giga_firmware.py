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
from motion_module.sensor_bridge import (
    GIGA_FIRMWARE_VERSION,
    PROTOCOL_V1,
    PROTOCOL_V2,
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
        self.assertIn(PROTOCOL_V2, source)

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
    """The real sketch, compiled for this computer, against simulated IMUs."""

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
        return [(ms, message) for ms, message in self.messages if "seq" in message and ms >= since]

    def last(self):
        return self.readings()[-1][1]

    CONFIG = "send MM2 CONFIG 7 A0:A,D22:U BNO055@28,LSM6@6A"
    BOTH = ("attach bno055 40 700", "attach lsm6 106 107")

    def test_says_hello_until_configured_then_streams_fifty_times_a_second(self):
        self.simulate("run 2100", self.CONFIG, "run 1000")
        hellos = [message for _ms, message in self.messages if message.get("event") == "hello"]
        self.assertEqual([hello["firmware"] for hello in hellos], [GIGA_FIRMWARE_VERSION] * 2)
        configured = next(message for _ms, message in self.messages if message.get("event") == "configured")
        self.assertEqual((configured["config"], configured["pins"], configured["imus"]), (7, 2, 2))
        self.assertTrue(49 <= len(self.readings()) <= 51)

    def test_pins_arrive_as_on_off_and_numbers_with_their_pulls_set(self):
        self.simulate("pin A0 3071", "pin D22 1", "send MM2 CONFIG 3 A0:A,D22:U,D5:N -", "run 100",
                      "pin D22 0", "run 100", "pinmode D22", "pinmode D5")
        first = self.readings()[0][1]
        self.assertEqual(first["values"], {"A0": 3071, "D22": 1, "D5": 0})
        self.assertEqual(self.last()["values"]["D22"], 0)
        self.assertIn("PINMODE D22 2", self.lines)  # INPUT_PULLUP
        self.assertIn("PINMODE D5 3", self.lines)   # INPUT_PULLDOWN

    def test_both_imus_track_a_left_turn_as_positive_yaw(self):
        self.simulate(*self.BOTH, self.CONFIG, "run 3000", "spin 90", "run 1000", "spin 0", "run 200", "crystal 40")
        bno, lsm = self.last()["imus"]
        self.assertEqual((bno["state"], lsm["state"]), ("ok", "ok"))
        self.assertAlmostEqual(bno["yaw"], 90.0, delta=1.0)
        self.assertAlmostEqual(lsm["yaw"], 90.0, delta=1.0)
        turning = self.readings(since=3500)[0][1]["imus"]
        self.assertAlmostEqual(turning[0]["rate"], 90.0, delta=0.5)
        self.assertAlmostEqual(turning[1]["rate"], 90.0, delta=0.5)
        self.assertIn("CRYSTAL 1 0", self.lines)  # the BNO055 uses its board's crystal, degrees

    def test_tilt_reads_front_up_and_right_side_down_as_positive(self):
        self.simulate(*self.BOTH, "tilt 10 -6", self.CONFIG, "run 3500")
        for imu in self.last()["imus"]:
            self.assertAlmostEqual(imu["pitch"], 10.0, delta=0.5)
            self.assertAlmostEqual(imu["roll"], -6.0, delta=0.5)

    def test_the_six_axis_gyro_bias_is_removed_at_rest(self):
        self.simulate("attach lsm6 106 108", "bias 106 0.8 -0.6 1.3", "noise 106 0.3",
                      "send MM2 CONFIG 9 - LSM6@6A", "run 12000")
        imu = self.last()["imus"][0]
        self.assertEqual(imu["state"], "ok")
        self.assertEqual(imu["id"], 108)
        self.assertLess(abs(imu["yaw"]), 0.3)

    def test_calibration_waits_for_the_robot_to_stop(self):
        self.simulate("attach lsm6 106 107", "spin 40", "send MM2 CONFIG 9 - LSM6@6A", "run 2500")
        moving = self.last()["imus"][0]
        self.assertEqual(moving["state"], "calibrating")
        self.assertEqual(moving.get("moving"), 1)
        self.simulate("attach lsm6 106 107", "spin 40", "send MM2 CONFIG 9 - LSM6@6A", "run 2500",
                      "spin 0", "run 2600")
        self.assertEqual(self.last()["imus"][0]["state"], "ok")

    def test_a_missing_imu_is_reported_and_found_when_plugged_in(self):
        self.simulate("attach lsm6 106 107", self.CONFIG, "run 2500")
        missing = self.last()["imus"][0]
        self.assertEqual(missing["state"], "missing")
        self.assertEqual(missing["seen"], [106])
        self.simulate("attach lsm6 106 107", self.CONFIG, "run 2500", "attach bno055 40 0", "run 3500")
        self.assertEqual(self.last()["imus"][0]["state"], "ok")

    def test_sending_the_same_configuration_keeps_the_imus_running(self):
        self.simulate(*self.BOTH, self.CONFIG, "run 3000", "spin 45", "run 1000", "spin 0",
                      self.CONFIG, "run 500")
        states = {message["imus"][0]["state"] for _ms, message in self.readings(since=4000)}
        self.assertEqual(states, {"ok"})
        self.assertAlmostEqual(self.last()["imus"][0]["yaw"], 45.0, delta=1.0)
        self.assertEqual(sum(1 for _ms, message in self.messages if message.get("event") == "configured"), 2)

    def test_calibrate_command_measures_the_gyro_again_and_keeps_yaw(self):
        self.simulate("attach lsm6 106 107", "send MM2 CONFIG 9 - LSM6@6A", "run 1500", "spin 30",
                      "run 1000", "spin 0", "send MM2 CALIBRATE", "run 300")
        self.assertEqual(self.last()["imus"][0]["state"], "calibrating")
        self.simulate("attach lsm6 106 107", "send MM2 CONFIG 9 - LSM6@6A", "run 1500", "spin 30",
                      "run 1000", "spin 0", "send MM2 CALIBRATE", "run 1500")
        imu = self.last()["imus"][0]
        self.assertEqual(imu["state"], "ok")
        self.assertAlmostEqual(imu["yaw"], 30.0, delta=1.0)

    def test_a_bad_configuration_is_rejected_and_the_old_one_kept(self):
        self.simulate("pin D2 1", "send MM2 CONFIG 1 D2:D -", "run 100", "send MM2 CONFIG 2 D99:D -", "run 100")
        error = next(message for _ms, message in self.messages if message.get("event") == "error")
        self.assertIn("pin", error["message"])
        self.assertEqual(self.last()["config"], 1)

    def test_original_protocol_still_works_for_older_motionmodule(self):
        self.simulate("pin A0 1234", "send MM1 CONFIG A0:A", "run 1000")
        streamed = [message for _ms, message in self.messages if message.get("protocol") == PROTOCOL_V1 and "values" in message]
        self.assertTrue(9 <= len(streamed) <= 11)
        self.assertEqual(streamed[0]["values"], {"A0": 1234})
        self.assertEqual(streamed[0]["firmware"], GIGA_FIRMWARE_VERSION)

    def test_nothing_is_sent_while_the_pi_has_the_port_closed(self):
        self.simulate("send MM2 CONFIG 1 D2:D -", "run 200", "host 0", "run 500", "host 1", "run 200")
        gap = [ms for ms, _message in self.readings() if 220 <= ms < 700]
        self.assertEqual(gap, [])
        self.assertTrue(self.readings(since=700))

    def test_status_light(self):
        self.simulate("run 2060", "led")
        self.assertIn("LED 0 0 1", self.lines)  # blue blink: waiting for the Pi
        self.simulate("attach lsm6 106 107", self.CONFIG, "run 4060", "led")
        self.assertIn("LED 1 0 1", self.lines)  # magenta: an IMU is missing

    def test_the_python_bridge_reads_the_firmware(self):
        """End to end: the sketch's own output, fed to the Pi-side bridge."""

        pins = [GigaPin("A0", "Arm", kind="analog"), GigaPin("D22", "Beam", pull="up")]
        imus = [GigaIMU("bno055", "Main IMU"), GigaIMU("ism330dhcx", "Backup IMU")]
        bridge = GigaR1Bridge(pins, imus=imus, autostart=False, discovery=lambda: [{
            "board_id": "arduino_giga_r1_wifi", "port": "/dev/ttyACM0", "mode": "sketch"}],
            serial_factory=lambda *_args, **_kwargs: port)
        self.addCleanup(bridge.close)

        class Port:
            def __init__(self):
                self.incoming = bytearray()
                self.written = []

            @property
            def in_waiting(self):
                return len(self.incoming)

            def read(self, size):
                data = bytes(self.incoming[:size])
                del self.incoming[:size]
                return data

            def write(self, data):
                self.written.append(data)

            def close(self):
                pass

        port = Port()
        bridge.poll()
        config = port.written[0].decode().strip()
        self.simulate("pin A0 2048", "pin D22 0", *self.BOTH, f"send {config}", "run 3000",
                      "spin -60", "run 1500", "spin 0", "run 100")
        for line in self.lines:
            if line.startswith("OUT "):
                port.incoming += line.split(" ", 2)[2].encode() + b"\n"
        bridge.poll()
        self.assertEqual(bridge.value("Arm"), 2048.0)
        self.assertIs(bridge.value("Beam"), False)
        self.assertEqual(bridge.imu("Main IMU").chip, "BNO055")
        self.assertEqual(bridge.imu("Backup IMU").chip, "ISM330DHCX")
        # Turning right for 1.5 s at 60 degrees a second.
        self.assertAlmostEqual(bridge.imu("Main IMU").heading(), -90.0, delta=1.5)
        self.assertAlmostEqual(bridge.imu("Backup IMU").heading(), -90.0, delta=1.5)
        self.assertTrue(bridge.imu("Main IMU").calibrated)


if __name__ == "__main__":
    unittest.main()
