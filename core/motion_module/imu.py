"""IMU drivers that run on the Raspberry Pi.

The Arduino GIGA only moves bytes: the Pi tells it which I2C registers to read
and how often, and these classes decide what to write during start-up, what
the raw registers mean, and what the robot's heading is. Everything about a
particular sensor lives here, so the GIGA's firmware never changes when the
robot's sensors do.

Angles are degrees. Yaw counts up as the robot turns counter-clockwise seen
from above, pitch as its front rises, and roll as its right side dips, so a
positive ``rotate`` and a rising heading mean the same direction.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


# chip name -> (driver, default address, address with the jumper set)
IMU_CHIPS = {
    "bno055": ("BNO055", 0x28, 0x29),
    "ism330dhcx": ("LSM6", 0x6A, 0x6B),
    "lsm6dsox": ("LSM6", 0x6A, 0x6B),
    "lsm6dso": ("LSM6", 0x6A, 0x6B),
    "lsm6ds3trc": ("LSM6", 0x6A, 0x6B),
}
# WHO_AM_I values of the 6-axis chips this driver understands.
LSM6_CHIPS = {0x69: "LSM6DS33", 0x6A: "LSM6DS3TR-C", 0x6B: "ISM330DHCX", 0x6C: "LSM6DSOX"}
DEGREES_PER_RADIAN = 57.29577951308232
RETRY_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class GigaIMU:
    """One IMU on the GIGA's I2C pins: SDA 20, SCL 21, 3.3V, and GND.

    ``chip`` is ``"bno055"`` for the 9-axis BNO055, or ``"ism330dhcx"``,
    ``"lsm6dsox"``, ``"lsm6dso"``, or ``"lsm6ds3trc"`` for a 6-axis IMU.
    ``address`` defaults to the board's own (0x28 for the BNO055, 0x6A for the
    6-axis boards). ``compass=True`` lets a BNO055 use its magnetometer for a
    north-referenced heading, which motors and steel can disturb.
    """

    chip: str
    name: str = "IMU"
    address: int | None = None
    compass: bool = False
    detail: str = ""

    def __post_init__(self) -> None:
        chip = str(self.chip).strip().casefold().replace("-", "").replace("_", "")
        if chip not in IMU_CHIPS:
            raise ValueError(
                "GIGA IMUs are bno055 (9-axis) or ism330dhcx, lsm6dsox, lsm6dso, lsm6ds3trc (6-axis)"
            )
        driver, default_address, jumper_address = IMU_CHIPS[chip]
        address = default_address if self.address is None else self.address
        if not isinstance(address, int) or isinstance(address, bool) or address not in (default_address, jumper_address):
            raise ValueError(
                f"A {chip} answers at 0x{default_address:02X}, or 0x{jumper_address:02X} "
                "with its address jumper set"
            )
        if self.compass and driver != "BNO055":
            raise ValueError("Only the 9-axis BNO055 has a compass")
        if not str(self.name).strip():
            raise ValueError("Every GIGA IMU needs a name")
        object.__setattr__(self, "chip", chip)
        object.__setattr__(self, "name", str(self.name).strip())
        object.__setattr__(self, "address", address)
        object.__setattr__(self, "compass", bool(self.compass))

    @property
    def driver(self) -> str:
        return IMU_CHIPS[self.chip][0]


# -- what a driver asks the GIGA to do ------------------------------------

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


def _int16(data: bytes, index: int) -> int:
    value = data[index] | (data[index + 1] << 8)
    return value - 0x10000 if value & 0x8000 else value


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


class ImuDriver:
    """Sets one IMU up through the GIGA, then reads its registers.

    Start-up is written as a generator of Read, Write, and Wait steps, so it
    reads in order while the reader thread stays free between answers.
    """

    streams: tuple[tuple[int, int], ...] = ()   # (register, length) read every cycle

    def __init__(self, declaration: GigaIMU) -> None:
        self.declaration = declaration
        self.address = declaration.address
        self.state = "waiting"
        self.chip_id: int | None = None
        self.yaw: float | None = None      # degrees, counter-clockwise, past a full turn
        self.rate: float | None = None
        self.pitch: float | None = None
        self.roll: float | None = None
        self.calibrated = False
        self.levels: tuple[int, ...] | None = None
        self.moving = False
        self.message = ""
        self.updated = 0.0
        self.seen: tuple[int, ...] = ()
        self._steps = None
        self._pending: Read | Write | None = None
        self._answer: bytes | None = None
        self._resume_at = 0.0
        self._retry_at = 0.0
        self._started_at = 0.0
        self._attempts = 0
        self._failures = 0
        self._now = 0.0   # the bridge's clock, so tests can run without waiting

    # -- driven by the bridge's reader thread ------------------------------

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
        """One Read or Write the GIGA carried out; the next step sends it on."""

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

    def recalibrate(self) -> None:
        """Measure what the sensor reads at rest again. 6-axis IMUs only."""

    # -- for subclasses ----------------------------------------------------

    def _setup(self):
        raise NotImplementedError

    def decode(self, values: list[bytes], board_ms: int, now: float) -> None:
        raise NotImplementedError

    @property
    def chip(self) -> str:
        return self.declaration.chip.upper()

    def _patient(self, seconds: float) -> bool:
        """A sensor powered up with the GIGA can take a moment to answer."""

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


class Bno055Driver(ImuDriver):
    """Bosch BNO055: a 9-axis sensor that fuses its own readings.

    Registers from Bosch's BST-BNO055-DS000 datasheet. The chip reports a
    heading, its own gravity direction, and how well it is calibrated; the Pi
    turns that into the robot's heading.
    """

    CHIP_ID = 0x00
    EXPECTED_ID = 0xA0
    PAGE = 0x07
    MOTION = 0x14        # gyro x, y, z, then heading, roll, pitch
    GRAVITY = 0x2E       # gravity x, y, z, temperature, calibration
    UNIT_SELECT = 0x3B
    MODE = 0x3D
    POWER = 0x3E
    TRIGGER = 0x3F
    MODE_CONFIG = 0x00
    MODE_IMU = 0x08      # gyro and accelerometer: motors cannot disturb it
    MODE_NDOF = 0x0C     # adds the magnetometer for a compass heading

    streams = ((MOTION, 12), (GRAVITY, 8))

    def __init__(self, declaration: GigaIMU) -> None:
        super().__init__(declaration)
        self._heading: float | None = None
        self._had_heading = False

    @property
    def chip(self) -> str:
        return "BNO055"

    def _setup(self):
        wanted = self.MODE_NDOF if self.declaration.compass else self.MODE_IMU
        while True:
            answer = yield Read(self.CHIP_ID, 1)
            if answer is None:
                if self._patient(1.5):
                    yield Wait(0.05)
                    continue
                raise Missing()
            self.chip_id = answer[0]
            if answer[0] == self.EXPECTED_ID:
                break
            if self._patient(1.5):
                yield Wait(0.05)
                continue
            raise WrongChip(f"chip id 0x{answer[0]:02X} is not a BNO055")

        yield Write(self.MODE, bytes([self.MODE_CONFIG]))
        yield Wait(0.025)
        # It can reset before acknowledging this write, so the answer is ignored.
        yield Write(self.TRIGGER, b"\x20")
        yield Wait(0.7)
        for _attempt in range(40):
            answer = yield Read(self.CHIP_ID, 1)
            if answer is not None and answer[0] == self.EXPECTED_ID:
                break
            yield Wait(0.05)
        else:
            raise Unusable("it did not restart")

        # Normal power; degrees and degrees per second; the board's crystal.
        for register, value in ((self.PAGE, 0), (self.POWER, 0), (self.UNIT_SELECT, 0), (self.TRIGGER, 0x80)):
            if (yield Write(register, bytes([value]))) is None:
                raise Unusable("it stopped answering while starting")
        yield Wait(0.02)
        yield Write(self.MODE, bytes([wanted]))
        yield Wait(0.03)
        answer = yield Read(self.MODE, 1)
        if answer is None or (answer[0] & 0x0F) != wanted:
            raise Unusable("it did not enter its fusion mode")
        self._heading = None

    def decode(self, values: list[bytes], board_ms: int, now: float) -> None:
        motion, gravity = values
        gyro = (_int16(motion, 0) / 16.0, _int16(motion, 2) / 16.0, _int16(motion, 4) / 16.0)
        heading = (motion[6] | (motion[7] << 8)) / 16.0   # 0-360, clockwise
        # Gravity reads +9.8 m/s2 along whichever axis points up.
        lift = (_int16(gravity, 0) / 100.0, _int16(gravity, 2) / 100.0, _int16(gravity, 4) / 100.0)
        strength = _length(lift)
        up = _scaled(lift, 1.0 / strength) if strength > 4.0 else (0.0, 0.0, 1.0)

        # Its heading grows clockwise; yaw grows counter-clockwise and keeps
        # counting past a full turn. A compass heading is absolute, so it is
        # taken as it is; a relative one carries on after a restart.
        if self._heading is None:
            if self.declaration.compass or not self._had_heading or self.yaw is None:
                self.yaw = -heading
            self._had_heading = True
        else:
            change = heading - self._heading
            if change > 180.0:
                change -= 360.0
            elif change < -180.0:
                change += 360.0
            self.yaw -= change
        self._heading = heading
        self.rate = _dot(gyro, up)
        self.pitch, self.roll = _tilt(up)

        calibration = gravity[7]
        self.levels = ((calibration >> 6) & 3, (calibration >> 4) & 3, (calibration >> 2) & 3, calibration & 3)
        self.calibrated = self.levels[0] == 3 if self.declaration.compass else self.levels[1] == 3

    def describe(self) -> str:
        if self.state == "ok" and self.levels is not None:
            system, gyro, accel, magnet = self.levels
            text = f"calibration gyro {gyro}/3, accelerometer {accel}/3"
            if self.declaration.compass:
                text += f", magnetometer {magnet}/3, overall {system}/3"
            return text if self.calibrated else text + ". Hold still for a few seconds to finish"
        return ""


class Lsm6Driver(ImuDriver):
    """ST's 6-axis family: ISM330DHCX, LSM6DSOX, LSM6DSO, LSM6DS3TR-C.

    These report only a raw gyro and accelerometer, so the Pi does the rest:
    it measures what the gyro reads at rest, carries the up direction along
    with the gyro while leaning it toward the accelerometer, and turns the
    part of the rotation that is about "up" into the robot's heading.
    """

    WHO_AM_I = 0x0F
    CTRL1_XL = 0x10
    CTRL2_G = 0x11
    CTRL3_C = 0x12
    CTRL9_XL = 0x18
    OUTPUT = 0x22        # gyro x, y, z, then accelerometer x, y, z
    DPS_PER_COUNT = 0.070          # at the +-2000 degrees per second range
    STILL_WINDOW = 1.0             # seconds of quiet needed to trust a rest reading
    STILL_SPREAD_DPS = 1.5         # how much a resting gyro may wobble
    STILL_RATE_DPS = 10.0          # a steady turn wobbles too little to spot otherwise
    BIAS_TRACK_LIMIT_DPS = 0.2     # never mistake a slow turn for drift
    UP_TIME_CONSTANT = 1.0         # seconds for the accelerometer to correct tilt
    MAXIMUM_STEP = 0.2             # seconds; a long gap is not a long turn

    streams = ((OUTPUT, 12),)

    def __init__(self, declaration: GigaIMU) -> None:
        super().__init__(declaration)
        self._bias = (0.0, 0.0, 0.0)
        self._up = (0.0, 0.0, 1.0)
        self._resting = 0.0
        self._last_ms: int | None = None
        self._window_start = 0.0
        self._window: list[tuple[tuple[float, float, float], tuple[float, float, float]]] = []

    @property
    def chip(self) -> str:
        return LSM6_CHIPS.get(self.chip_id, self.declaration.chip.upper())

    def _setup(self):
        answer = yield Read(self.WHO_AM_I, 1)
        if answer is None:
            if self._patient(0.3):
                yield Wait(0.05)
                answer = yield Read(self.WHO_AM_I, 1)
            if answer is None:
                raise Missing()
        self.chip_id = answer[0]
        if answer[0] not in LSM6_CHIPS:
            raise WrongChip(f"chip id 0x{answer[0]:02X} is not a supported 6-axis IMU")

        yield Write(self.CTRL3_C, b"\x01")   # software reset
        yield Wait(0.02)
        for _attempt in range(20):
            answer = yield Read(self.CTRL3_C, 1)
            if answer is not None and not answer[0] & 0x01:
                break
            yield Wait(0.01)
        else:
            raise Unusable("it did not reset")

        # Block data update keeps each reading's two bytes from one sample.
        if (yield Write(self.CTRL3_C, b"\x44")) is None:
            raise Unusable("it stopped answering while starting")
        # Bit 1 of CTRL9_XL switches I3C off on the LSM6DSOX and LSM6DSO, and
        # is DEVICE_CONF, which ST says to set, on the ISM330DHCX.
        if self.chip_id in (0x6B, 0x6C):
            answer = yield Read(self.CTRL9_XL, 1)
            if answer is None:
                raise Unusable("it stopped answering while starting")
            yield Write(self.CTRL9_XL, bytes([answer[0] | 0x02]))
        if (yield Write(self.CTRL1_XL, b"\x48")) is None:   # accelerometer 104 Hz, +-4 g
            raise Unusable("it stopped answering while starting")
        if (yield Write(self.CTRL2_G, b"\x6c")) is None:    # gyro 416 Hz, +-2000 dps
            raise Unusable("it stopped answering while starting")
        yield Wait(0.1)  # let the gyro settle

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
        data = values[0]
        gyro = tuple(_int16(data, index * 2) * self.DPS_PER_COUNT for index in range(3))
        accel = tuple(float(_int16(data, 6 + index * 2)) for index in range(3))
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


def driver_for(declaration: GigaIMU) -> ImuDriver:
    return Bno055Driver(declaration) if declaration.driver == "BNO055" else Lsm6Driver(declaration)
