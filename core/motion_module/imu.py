"""MPU6500 setup and relative heading on the Raspberry Pi.

The driver initializes the chip and interprets its registers. LocalIMU accesses the MPU6500 directly from the Pi over I2C.
Other sensors belong on the optional Arduino expansion.

Angles are degrees. Yaw counts up as the robot turns counter-clockwise seen
from above, pitch as its front rises, and roll as its right side dips, so a
positive ``rotate`` and a rising heading mean the same direction.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from struct import unpack


MPU6500_ID = 0x70
MPU6500_ADDRESSES = (0x68, 0x69)
DEGREES_PER_RADIAN = 57.29577951308232
RETRY_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class IMUConfig:
    """The Pi-connected MPU6500. AD0 low selects 0x68; high selects 0x69."""

    name: str = "Main IMU"
    address: int = 0x68

    def __post_init__(self) -> None:
        if type(self.address) is not int or self.address not in MPU6500_ADDRESSES:
            raise ValueError("The MPU6500 address must be 0x68 or 0x69")
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("The IMU needs a name")
        object.__setattr__(self, "name", self.name.strip())


def GigaIMU(chip="mpu6500", name="IMU", address=None, compass=False, detail=""):  # noqa: N802
    """Old releases' IMU declaration, kept so a preserved sensors.py still imports.

    Releases before 0.12 declared IMUs as ``GigaIMU("mpu9255", "Main IMU",
    address=0x68)``, and older ones ``GigaIMU("bno055", ...)`` on the Arduino.
    The installer keeps robot folders someone edited, so those lines must not
    stop the robot from starting. Every declaration now means the one built-in
    IMU, the MPU6500 on the Pi: this returns its IMUConfig. No other chip is
    read; ``compass`` and ``detail`` are ignored. Replace it with
    ``IMUConfig(...)`` when you next edit sensors.py.
    """

    import logging

    chip_name = str(chip).strip().casefold().replace("-", "").replace("_", "")
    note = "" if chip_name in {"mpu6500", "mpu9255", "mpu9250"} else (
        f" It declared a {chip}; that chip is no longer read."
    )
    logging.getLogger(__name__).warning(
        "sensors.py uses the retired GigaIMU(%r, %r) declaration; reading the Pi's "
        "MPU6500 instead.%s Replace it with IMUConfig(%r, address=0x68).",
        chip, name, note, str(name).strip() or "Main IMU",
    )
    if address not in MPU6500_ADDRESSES:
        address = 0x68
    return IMUConfig(name=str(name).strip() or "Main IMU", address=address)


# -- transport-independent register operations --------------------------

@dataclass(frozen=True, slots=True)
class Read:
    """Read ``length`` bytes from one register, once."""

    register: int
    length: int


@dataclass(frozen=True, slots=True)
class Write:
    """Write bytes to one register, once."""

    register: int
    data: bytes


@dataclass(frozen=True, slots=True)
class Wait:
    """Let the sensor settle before the next step."""

    seconds: float


class Missing(Exception):
    """Nothing answered at the address."""


class WrongChip(Exception):
    """Something answered, but it is not the declared sensor."""


class Unusable(Exception):
    """The sensor answered but could not be set up."""


def wrap180(degrees: float) -> float:
    return (degrees + 180.0) % 360.0 - 180.0


def _length(vector) -> float:
    return math.sqrt(vector[0] ** 2 + vector[1] ** 2 + vector[2] ** 2)


def _scaled(vector, factor):
    return (vector[0] * factor, vector[1] * factor, vector[2] * factor)


def _difference(first, second):
    return (first[0] - second[0], first[1] - second[1], first[2] - second[2])


def _dot(first, second) -> float:
    return first[0] * second[0] + first[1] * second[1] + first[2] * second[2]


def _cross(first, second):
    return (
        first[1] * second[2] - first[2] * second[1],
        first[2] * second[0] - first[0] * second[2],
        first[0] * second[1] - first[1] * second[0],
    )


def _tilt(up) -> tuple[float, float]:
    """Pitch and roll in degrees from the direction that points up."""

    pitch = math.atan2(up[1], math.sqrt(up[0] ** 2 + up[2] ** 2)) * DEGREES_PER_RADIAN
    roll = math.atan2(-up[0], up[2]) * DEGREES_PER_RADIAN
    return pitch, roll


class _Startup:
    """Sets one IMU up through its transport, then reads its registers.

    Start-up is written as a generator of Read, Write, and Wait steps, so it
    reads in order while the reader thread stays free between answers.
    """

    streams: tuple[tuple[int, int], ...] = ()   # (register, length) read every cycle

    def __init__(self, declaration: IMUConfig) -> None:
        self.declaration = declaration
        self.address = declaration.address
        self.state = "waiting"
        self.chip_id: int | None = None
        self.yaw: float | None = None      # degrees, counter-clockwise, past a full turn
        self.rate: float | None = None
        self.pitch: float | None = None
        self.roll: float | None = None
        self.calibrated = False
        self.moving = False
        self.message = ""
        self.updated = 0.0
        self._steps = None
        self._pending: Read | Write | None = None
        self._answer: bytes | None = None
        self._resume_at = 0.0
        self._retry_at = 0.0
        self._started_at = 0.0
        self._attempts = 0
        self._failures = 0
        self._now = 0.0   # the reader's clock, so tests can run without waiting

    # -- driven by the Pi reader thread ------------------------------

    def begin(self, now: float) -> None:
        """Start (or restart) setting the sensor up."""

        self.state = "starting"
        self.calibrated = False
        self.message = ""
        self._now = now
        self._steps = self._setup()
        self._pending = None
        self._answer = None
        self._resume_at = 0.0
        self._started_at = now
        self._attempts += 1
        self._failures = 0

    def stop(self) -> None:
        self.state = "waiting"
        self.calibrated = False
        self._steps = None
        self._pending = None
        self.updated = 0.0

    def step(self, io, now: float) -> None:
        """Send the next start-up step, or retry a sensor that went quiet."""

        self._now = now
        if self.state in {"missing", "wrong-chip", "failed"}:
            if now >= self._retry_at:
                self.begin(now)
            return
        if self.state != "starting" or self._pending is not None or now < self._resume_at:
            return
        answer, self._answer = self._answer, None
        self._pump(io, now, answer)

    def on_answer(self, data: bytes | None, _now: float) -> None:
        """One Read or Write the transport carried out; the next step sends it on."""

        if self._pending is None:
            return
        self._pending = None
        self._answer = data

    def on_readings(self, streams: dict[str, bytes | None], board_ms: int, now: float) -> None:
        """One cycle of the registers this driver asked to have read."""

        self._now = now
        if self.state not in {"calibrating", "ok"}:
            return
        values = [streams.get(f"{self.address:02x}:{register:02x}") for register, _length in self.streams]
        if any(value is None or len(value) != length for value, (_register, length) in zip(values, self.streams)):
            self._failures += 1
            if self._failures >= 10:
                self._fail("failed", "stopped answering")
            return
        self._failures = 0
        self.updated = now
        self.decode(values, board_ms, now)

    # -- for subclasses ----------------------------------------------------

    def _setup(self):
        raise NotImplementedError

    def decode(self, values: list[bytes], board_ms: int, now: float) -> None:
        raise NotImplementedError

    @property
    def chip(self) -> str:
        return "MPU6500"

    def _patient(self, seconds: float) -> bool:
        """A sensor powered up with the Pi can take a moment to answer."""

        return self._attempts <= 1 and self._now - self._started_at < seconds

    def _pump(self, io, now: float, answer) -> None:
        """Hand the last answer to the start-up steps and send what they ask for next."""

        self._now = now
        try:
            request = self._steps.send(answer)
        except StopIteration:
            self._steps = None
            self._begin_running(now)
            return
        except Missing:
            return self._fail("missing", "nothing answered")
        except WrongChip as reason:
            return self._fail("wrong-chip", str(reason))
        except Unusable as reason:
            return self._fail("failed", str(reason))
        if isinstance(request, Wait):
            self._resume_at = now + request.seconds
            return
        self._pending = request
        io.request(self, request)

    def _begin_running(self, now: float) -> None:
        self.state = "ok"
        self.message = ""

    def _fail(self, state: str, message: str) -> None:
        self.state = state
        self.calibrated = False
        self.message = message
        self._steps = None
        self._pending = None
        self._answer = None
        self._retry_at = self._now + RETRY_SECONDS


class Mpu6500Driver(_Startup):
    """MPU6500 setup, calibration and tilt-compensated relative heading."""

    STILL_WINDOW = 1.0             # seconds of quiet needed to trust a rest reading
    STILL_SPREAD_DPS = 1.5         # how much a resting gyro may wobble
    STILL_RATE_DPS = 10.0          # a steady turn wobbles too little to spot otherwise
    BIAS_TRACK_LIMIT_DPS = 0.2     # never mistake a slow turn for drift
    UP_TIME_CONSTANT = 1.0         # seconds for the accelerometer to correct tilt
    MAXIMUM_STEP = 0.2             # seconds; a long gap is not a long turn

    def __init__(self, declaration: IMUConfig) -> None:
        super().__init__(declaration)
        self._bias = (0.0, 0.0, 0.0)
        self._up = (0.0, 0.0, 1.0)
        self._resting = 0.0
        self._last_ms: int | None = None
        self._window_start = 0.0
        self._window: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []

    def _begin_running(self, now: float) -> None:
        self._start_calibration(now)

    def recalibrate(self) -> None:
        if self.state in {"ok", "calibrating"}:
            self._start_calibration(self._now)

    def _start_calibration(self, now: float) -> None:
        self.state = "calibrating"
        self.calibrated = False
        self.message = ""
        self._last_ms = None
        self._window_start = now
        self._window.clear()

    def decode(self, values: list[bytes], board_ms: int, now: float) -> None:
        gyro, accel = self._vectors(values[0])
        seconds = 0.0
        if self._last_ms is not None:
            seconds = min(((board_ms - self._last_ms) & 0xFFFFFFFF) / 1000.0, self.MAXIMUM_STEP)
        self._last_ms = board_ms
        self._window.append((gyro, accel))

        if self.state == "calibrating":
            if now - self._window_start < self.STILL_WINDOW:
                return
            if self._still():
                self._bias = self._average(0)
                resting = self._average(1)
                self._resting = _length(resting)
                if self._resting > 0:
                    self._up = _scaled(resting, 1.0 / self._resting)
                self.pitch, self.roll = _tilt(self._up)
                if self.yaw is None:
                    self.yaw = 0.0
                self.rate = 0.0
                self.state = "ok"
                self.calibrated = True
                self.moving = False
            else:
                self.moving = True
            self._reset_window(now)
            return

        # Tilt: carry the up direction along with the gyro, and lean it gently
        # toward the accelerometer whenever that reads about one g.
        turn = _difference(gyro, self._bias)
        spin = _scaled(turn, 1.0 / DEGREES_PER_RADIAN)
        up = _difference(self._up, _scaled(_cross(spin, self._up), seconds))
        strength = _length(accel)
        if self._resting > 0 and abs(strength - self._resting) < 0.1 * self._resting:
            blend = min(1.0, seconds / self.UP_TIME_CONSTANT)
            up = _difference(up, _scaled(_difference(up, _scaled(accel, 1.0 / strength)), blend))
        size = _length(up)
        self._up = _scaled(up, 1.0 / size) if size > 0 else (0.0, 0.0, 1.0)

        # Heading: the turn about the up direction, so tilting never reads as turning.
        self.rate = _dot(turn, self._up)
        self.yaw = (self.yaw or 0.0) + self.rate * seconds
        self.pitch, self.roll = _tilt(self._up)

        # A resting robot keeps re-measuring the gyro's drift as it warms up.
        if now - self._window_start >= self.STILL_WINDOW:
            if self._still():
                correction = _difference(self._average(0), self._bias)
                if all(abs(value) < self.BIAS_TRACK_LIMIT_DPS for value in correction):
                    self._bias = tuple(
                        bias + value * 0.2 for bias, value in zip(self._bias, correction)
                    )
            self._reset_window(now)

    def describe(self) -> str:
        if self.state == "calibrating":
            return "measuring the gyro at rest" + (", but the robot is moving" if self.moving else "")
        return ""

    def _reset_window(self, now: float) -> None:
        self._window_start = now
        self._window.clear()

    def _average(self, index: int):
        samples = [sample[index] for sample in self._window]
        count = float(len(samples))
        return tuple(sum(axis) / count for axis in zip(*samples))

    def _still(self) -> bool:
        if len(self._window) < 10:
            return False
        readings = [sample[0] for sample in self._window]
        mean = self._average(0)
        for axis, values in enumerate(zip(*readings)):
            if max(values) - min(values) >= self.STILL_SPREAD_DPS:
                return False
            if abs(mean[axis]) >= self.STILL_RATE_DPS:
                return False
        return True

    WHO_AM_I = 0x75
    EXPECTED_ID = MPU6500_ID
    POWER = 0x6B
    OUTPUT = 0x3B
    DPS_PER_COUNT = 1.0 / 16.4  # GYRO_CONFIG FS_SEL=3: +/-2000 dps
    streams = ((OUTPUT, 14),)

    @property
    def chip(self) -> str:
        return "MPU6500"

    def _setup(self):
        while True:
            answer = yield Read(self.WHO_AM_I, 1)
            if answer:
                self.chip_id = answer[0]
                if self.chip_id != self.EXPECTED_ID:
                    raise WrongChip(
                        f"chip id 0x{self.chip_id:02X} is not supported "
                        "(expected MPU6500 0x70)"
                    )
                break
            if not self._patient(0.3):
                raise Missing()
            yield Wait(0.05)

        # Reset may remove the device before the write is acknowledged.
        yield Write(self.POWER, b"\x80")
        yield Wait(0.1)
        for _attempt in range(20):
            answer = yield Read(self.POWER, 1)
            if answer and not answer[0] & 0x80:
                break
            yield Wait(0.01)
        else:
            raise Unusable("it did not reset")

        # PLL clock, all axes enabled; FIFO/DMP/master disabled. Filter the
        # gyro and accel at ~20 Hz and sample at 100 Hz for our 50 Hz reader.
        settings = (
            (self.POWER, 0x01), (0x6C, 0x00), (0x6A, 0x00), (0x23, 0x00),
            (0x1A, 0x04), (0x19, 0x09), (0x1B, 0x18), (0x1C, 0x08), (0x1D, 0x04),
        )
        for register, value in settings:
            if (yield Write(register, bytes([value]))) is None:
                raise Unusable("it stopped answering while starting")
        yield Wait(0.1)
        # Acknowledged but ineffective writes must not silently mis-scale yaw.
        for register, value in settings:
            answer = yield Read(register, 1)
            if not answer or answer[0] != value:
                raise Unusable(f"configuration register 0x{register:02X} did not retain its setting")

    def _vectors(self, data: bytes):
        ax, ay, az, _temperature, gx, gy, gz = unpack(">7h", data)
        accel = (ax, ay, az)
        gyro = (gx * self.DPS_PER_COUNT, gy * self.DPS_PER_COUNT, gz * self.DPS_PER_COUNT)
        return gyro, accel
