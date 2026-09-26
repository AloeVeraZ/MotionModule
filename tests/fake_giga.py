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


class SimChip:
    """One simulated I2C device."""

    present = True

    def read(self, register: int, length: int, now_ms: int) -> bytes | None:
        raise NotImplementedError

    def write(self, register: int, data: bytes, now_ms: int) -> bool:
        raise NotImplementedError


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
