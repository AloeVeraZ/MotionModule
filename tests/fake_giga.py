"""A stand-in Arduino GIGA for the Pi-side tests.

It answers the sensor bridge's commands the way the firmware does and carries
simulated I2C chips, so the drivers, their maths, and the protocol are all
exercised without hardware. The robot it describes is a simple one: it turns
at whatever rate a test sets and can be tilted.
"""

from __future__ import annotations

import json
import math

from motion_module.sensor_bridge import PROTOCOL, PROTOCOL_V1


GRAVITY = 9.80665
COUNTS_PER_G = 1000.0 / 0.122   # the +-4 g range the driver selects
DPS_PER_COUNT = 0.070


class Clock:
    """A clock the tests move themselves, so nothing waits in real time."""

    def __init__(self, start: float = 1000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class World:
    """What the robot is really doing."""

    def __init__(self) -> None:
        self.yaw = 0.0    # degrees, counter-clockwise
        self.rate = 0.0   # degrees per second about vertical
        self.pitch = 0.0
        self.roll = 0.0

    def advance(self, seconds: float) -> None:
        self.yaw += self.rate * seconds

    @property
    def up(self) -> tuple[float, float, float]:
        """Which way is up, in the axes of a flat-mounted sensor."""

        pitch = math.radians(self.pitch)
        roll = math.radians(self.roll)
        return (-math.sin(roll) * math.cos(pitch), math.sin(pitch), math.cos(roll) * math.cos(pitch))


def _put(data: bytearray, index: int, value: float) -> None:
    number = max(-32768, min(32767, int(round(value)))) & 0xFFFF
    data[index] = number & 0xFF
    data[index + 1] = number >> 8


class SimChip:
    """One simulated I2C device."""

    present = True

    def read(self, register: int, length: int, now_ms: int) -> bytes | None:
        raise NotImplementedError

    def write(self, register: int, data: bytes, now_ms: int) -> bool:
        raise NotImplementedError


class SimBno055(SimChip):
    """A BNO055 that fuses its own readings, as the real one does."""

    def __init__(self, world: World, chip_id: int = 0xA0) -> None:
        self.world = world
        self.chip_id = chip_id
        self.mode = 0
        self.units = 0x80
        self.crystal = False
        self.ready_at = 0
        self.fusion_yaw = 0.0
        self.fusion_since = 0
        self.resets = 0

    def _image(self, now_ms: int) -> bytearray:
        data = bytearray(0x40)
        data[0x00] = self.chip_id
        data[0x3D] = self.mode
        data[0x3B] = self.units
        if self.mode:
            heading = (-(self.world.yaw - self.fusion_yaw)) % 360.0
            _put(data, 0x18, self.world.rate * 16)          # gyro z
            _put(data, 0x1A, heading * 16)                  # heading, clockwise
            up = self.world.up
            for axis in range(3):
                _put(data, 0x2E + axis * 2, up[axis] * GRAVITY * 100)
            data[0x34] = 25                                  # temperature
            data[0x35] = 0x34 if now_ms - self.fusion_since >= 1000 else 0x00
            data[0x39] = 5                                   # fusion running
        return data

    def read(self, register: int, length: int, now_ms: int) -> bytes | None:
        if not self.present or now_ms < self.ready_at:
            return None
        image = self._image(now_ms)
        if register + length > len(image):
            return None
        return bytes(image[register:register + length])

    def write(self, register: int, data: bytes, now_ms: int) -> bool:
        if not self.present or now_ms < self.ready_at:
            return False
        value = data[0] if data else 0
        if register == 0x3D:
            self.mode = value & 0x0F
            if self.mode:
                self.fusion_yaw = self.world.yaw
                self.fusion_since = now_ms
        elif register == 0x3F:
            if value & 0x20:       # system reset: silent for 650 ms
                self.ready_at = now_ms + 650
                self.mode = 0
                self.crystal = False
                self.resets += 1
            else:
                self.crystal = bool(value & 0x80)
        elif register == 0x3B:
            self.units = value
        return True


class SimLsm6(SimChip):
    """An ST 6-axis IMU: a raw gyro and accelerometer, and nothing else."""

    def __init__(self, world: World, chip_id: int = 0x6B, bias=(0.0, 0.0, 0.0), noise: float = 0.0) -> None:
        self.world = world
        self.chip_id = chip_id
        self.bias = bias
        self.noise = noise
        self.registers = bytearray(0x80)
        self.registers[0x12] = 0x04
        self.resetting_until = 0
        self.resets = 0
        self._random = 12345

    def _wobble(self) -> float:
        self._random = (self._random * 1103515245 + 12345) & 0xFFFFFFFF
        return self.noise * (((self._random >> 8) & 0xFFFF) / 65535.0 - 0.5)

    def read(self, register: int, length: int, now_ms: int) -> bytes | None:
        if not self.present:
            return None
        data = bytearray(self.registers)
        data[0x0F] = self.chip_id
        if now_ms < self.resetting_until:
            data[0x12] |= 0x01
        up = self.world.up
        for axis in range(3):
            rate = self.world.rate * up[axis] + self.bias[axis] + self._wobble()
            _put(data, 0x22 + axis * 2, rate / DPS_PER_COUNT)
            _put(data, 0x28 + axis * 2, up[axis] * COUNTS_PER_G)
        data[0x1E] = 0x03  # a new sample is ready
        if register + length > len(data):
            return None
        return bytes(data[register:register + length])

    def write(self, register: int, data: bytes, now_ms: int) -> bool:
        if not self.present:
            return False
        value = data[0] if data else 0
        if register == 0x12 and value & 0x01:
            self.resetting_until = now_ms + 10
            self.resets += 1
            self.registers = bytearray(0x80)
            self.registers[0x12] = 0x04
            return True
        self.registers[register] = value
        return True


class FakeGiga:
    """The firmware's side of the protocol, over a fake serial port."""

    def __init__(self, world: World | None = None, firmware: str = "3.0.0", protocol: str = PROTOCOL) -> None:
        self.world = world or World()
        self.firmware = firmware
        self.protocol = protocol
        self.chips: dict[int, SimChip] = {}
        self.pins: dict[str, int] = {}
        self.incoming = bytearray()
        self.commands: list[str] = []
        self.closed = False
        self.ms = 0
        self.config_id = None
        self.interval = 20
        self.declared_pins: list[tuple[str, str]] = []
        self.streams: list[tuple[int, int, int]] = []
        self.legacy = False
        self._command = bytearray()
        self._next_reading = 0
        self._next_hello = 0
        self._sequence = 0

    # -- the serial port the bridge opens ---------------------------------

    @property
    def in_waiting(self) -> int:
        return len(self.incoming)

    def read(self, size: int) -> bytes:
        data = bytes(self.incoming[:size])
        del self.incoming[:size]
        return data

    def write(self, data: bytes) -> None:
        self._command += data
        while b"\n" in self._command:
            line, _, rest = bytes(self._command).partition(b"\n")
            self._command = bytearray(rest)
            self._handle(line.decode("ascii", errors="replace").strip())

    def close(self) -> None:
        self.closed = True

    # -- what tests drive --------------------------------------------------

    def attach(self, address: int, chip: SimChip) -> SimChip:
        self.chips[address] = chip
        return chip

    def detach(self, address: int) -> None:
        self.chips.pop(address, None)

    def tick(self, milliseconds: int = 20) -> None:
        """Move the board's clock on and send whatever is due."""

        self.ms += milliseconds
        self.world.advance(milliseconds / 1000.0)
        if self.config_id is not None and self.ms >= self._next_reading:
            self._next_reading = self.ms + self.interval
            self._send_reading()
        elif self.legacy and self.ms >= self._next_reading:
            self._next_reading = self.ms + 100
            self._send({"protocol": PROTOCOL_V1, "board": "arduino_giga_r1_wifi",
                        "firmware": self.firmware, "values": self._pin_values()})
        elif self.config_id is None and not self.legacy and self.ms >= self._next_hello:
            self._next_hello = self.ms + 1000
            self._send({"protocol": self.protocol, "event": "hello", "firmware": self.firmware,
                        "board": "arduino_giga_r1_wifi", "streams": 6, "stream_bytes": 32, "pins": 20})

    def restart(self) -> None:
        """The board lost power and came back with nothing configured."""

        self.config_id = None
        self.streams = []
        self.declared_pins = []
        self.ms = 0
        self._next_hello = 0
        self.tick(0)
        self._send({"protocol": self.protocol, "event": "hello", "firmware": self.firmware,
                    "board": "arduino_giga_r1_wifi"})

    # -- the firmware's own behaviour --------------------------------------

    def _send(self, payload: dict) -> None:
        self.incoming += json.dumps(payload).encode() + b"\n"

    def _pin_values(self) -> dict:
        return {label: int(self.pins.get(label, 0)) for label, _mode in self.declared_pins}

    def _send_reading(self) -> None:
        self._sequence += 1
        readings = {}
        for address, register, length in self.streams:
            chip = self.chips.get(address)
            data = chip.read(register, length, self.ms) if chip is not None else None
            readings[f"{address:02x}:{register:02x}"] = data.hex() if data else None
        self._send({
            "protocol": self.protocol, "firmware": self.firmware, "config": self.config_id,
            "seq": self._sequence, "ms": self.ms, "values": self._pin_values(), "i2c": readings,
        })

    def _error(self, message: str) -> None:
        self._send({"protocol": self.protocol, "event": "error", "firmware": self.firmware,
                    "message": message})

    def _handle(self, line: str) -> None:
        self.commands.append(line)
        if line.startswith("MM3 CONFIG "):
            return self._configure(line[11:])
        if line.startswith("MM3 I2C "):
            return self._i2c(line[8:])
        if line.startswith("MM3 SCAN "):
            found = sorted(address for address, chip in self.chips.items() if chip.present)
            return self._send({"protocol": self.protocol, "event": "scan", "firmware": self.firmware,
                               "seq": int(line[9:]), "found": found})
        if line == "MM3 HELLO":
            return self._send({"protocol": self.protocol, "event": "hello", "firmware": self.firmware,
                               "board": "arduino_giga_r1_wifi"})
        if line.startswith("MM1 CONFIG "):
            self.legacy = True
            self.config_id = None
            self.declared_pins = [
                (item.split(":")[0], item.split(":")[1])
                for item in line[11:].split(",") if ":" in item
            ]
            return self._send({"protocol": PROTOCOL_V1, "event": "configured", "firmware": self.firmware})

    def _configure(self, arguments: str) -> None:
        parts = arguments.split(" ")
        if len(parts) != 4:
            return self._error("expected MM3 CONFIG <id> <ms> <pins> <streams>")
        identifier, interval, pins, streams = parts
        try:
            declared_pins = [] if pins == "-" else [
                (item.split(":")[0], item.split(":")[1]) for item in pins.split(",")
            ]
            declared_streams = [] if streams == "-" else [
                (int(item.split(":")[0], 16), int(item.split(":")[1], 16), int(item.split(":")[2]))
                for item in streams.split(",")
            ]
            self.config_id = int(identifier)
            self.interval = int(interval)
        except (IndexError, ValueError):
            return self._error("pin list not understood")
        self.legacy = False
        self.declared_pins = declared_pins
        self.streams = declared_streams
        self._next_reading = self.ms
        self._send({"protocol": self.protocol, "event": "configured", "firmware": self.firmware,
                    "config": self.config_id, "pins": len(declared_pins),
                    "streams": len(declared_streams), "interval": self.interval})

    def _i2c(self, arguments: str) -> None:
        parts = arguments.split(" ")
        if len(parts) != 5:
            return self._error("expected MM3 I2C <seq> <addr> R|W <reg> <len or hex>")
        seq, address, direction, register, value = parts
        chip = self.chips.get(int(address, 16))
        reply = {"protocol": self.protocol, "event": "i2c", "firmware": self.firmware,
                 "seq": int(seq), "addr": int(address, 16), "reg": int(register, 16)}
        if chip is None:
            reply["ok"] = 0
            return self._send(reply)
        if direction == "R":
            data = chip.read(int(register, 16), int(value), self.ms)
            reply["ok"] = 1 if data is not None else 0
            if data is not None:
                reply["data"] = data.hex()
        else:
            reply["ok"] = 1 if chip.write(int(register, 16), bytes.fromhex(value), self.ms) else 0
        self._send(reply)


def run(bridge, board: FakeGiga, clock: Clock, seconds: float, step_ms: int | None = None) -> None:
    """Run the bridge and the board together for a while of simulated time."""

    step = step_ms if step_ms is not None else board.interval
    for _cycle in range(max(1, int(seconds * 1000 / step))):
        board.tick(step)
        clock.advance(step / 1000.0)
        bridge.poll()
