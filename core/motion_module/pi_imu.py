"""Read the robot's IMU directly on the Pi's independent I2C bus.

The reference wiring is VCC to physical pin 17, GND to 6 and AD0 to 20, SDA to 11,
and SCL to 12. Enable the i2c-gpio overlay on GPIO17/18;
see docs/PINOUT.md and Debug > Wiring for the complete board guide.
The MPU6500 board must be in I2C mode; INT is left disconnected.

The chip drivers in imu.py are transport-independent. LocalIMU executes
those register operations on the Pi; the Mecanum sample uses this path.
"""

from __future__ import annotations

import math
import re
import threading
import time
from dataclasses import replace
from pathlib import Path

from .imu import IMUConfig, MPU6500_ADDRESSES, MPU6500_ID, Mpu6500Driver, Read, wrap180
from .telemetry import IMUReading

POLL_SECONDS = 0.02   # ~50 Hz, the same cadence the GIGA bridge reads at
STALE_AFTER = 1.0     # seconds; an older reading is treated as disconnected
RETRY_SECONDS = 2.0
_NO_SMBUS2 = "Install smbus2 to read an IMU wired directly to the Pi."


def find_i2c_gpio_bus(sysfs_root: str | Path = "/sys/class/i2c-dev") -> int | None:
    """The bus number of the Pi's bit-banged i2c-gpio adapter, if one is set up.

    ``dtoverlay=i2c-gpio,i2c_gpio_sda=17,i2c_gpio_scl=18`` in
    /boot/firmware/config.txt enables the reference IMU bus on physical
    pins 11 and 12, independently of the PCA9685 bus. The kernel assigns a
    number that can shift between boots, so discovery uses the adapter name.
    Returns None if no such adapter exists yet - the overlay line above needs
    adding, then a reboot.
    """

    root = Path(sysfs_root)
    if not root.is_dir():
        return None
    for entry in sorted(root.iterdir()):
        match = re.fullmatch(r"i2c-(\d+)", entry.name)
        if not match:
            continue
        try:
            name = (entry / "name").read_text(encoding="utf-8", errors="replace").strip()
        except OSError:
            continue
        # Device-tree adapters may be named i2c@0, not "i2c-gpio".
        # Read the compatible property rather than guessing from that name.
        compatible = b""
        for node in (entry / "device/of_node/compatible", entry / "of_node/compatible"):
            try:
                compatible = node.read_bytes()
                break
            except OSError:
                pass
        if b"i2c-gpio" in compatible.split(b"\0") or re.fullmatch(r"i2c-gpio(?:\d+|[.@-][\w.-]+)?", name):
            return int(match.group(1))
    return None


class LocalIMU:
    """One IMU read directly over the Pi's own I2C bus, on its own thread.

    ``declaration`` is the shared IMUConfig chip declaration. Pass the bus
    returned by find_i2c_gpio_bus() for the reference wiring, or use
    module.local_imu() to manage discovery and shutdown.
    """

    def __init__(
        self,
        declaration: IMUConfig = IMUConfig(),
        *,
        bus: int,
        auto_start: bool = True,
        bus_factory=None,
        clock=None,
        auto_address: bool = False,
    ):
        if not isinstance(declaration, IMUConfig):
            raise TypeError("Use IMUConfig for the Pi-connected MPU6500")
        self.declaration = declaration
        self.name = declaration.name
        self._bus_number = bus
        self._bus_factory = bus_factory
        self._bus = None
        self._clock = clock if clock is not None else time.monotonic
        self._driver = Mpu6500Driver(declaration)
        self._auto_address = auto_address
        self._next_address_probe = 0.0
        self._lock = threading.Lock()
        self._offset = 0.0
        self._pending_zero: float | None = None
        self._pending_level = False
        # Pitch and roll that read as level, set by zero(level=True).
        self._level = (0.0, 0.0)
        self._error = ""
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        if auto_start:
            self.start()

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def _open_bus(self):
        if self._bus_factory is not None:
            return self._bus_factory(self._bus_number)
        try:
            import smbus2
        except ImportError:
            with self._lock:
                self._error = _NO_SMBUS2
            return None
        try:
            return smbus2.SMBus(self._bus_number)
        except OSError as error:
            with self._lock:
                self._error = f"Could not open I2C bus {self._bus_number}: {error}"
            return None

    # -- the ImuDriver's io, called only while a poll() is in progress -----

    def request(self, driver, request) -> None:
        """One Read or Write, carried out at once - the bus is synchronous."""

        try:
            if isinstance(request, Read):
                data = bytes(self._bus.read_i2c_block_data(driver.address, request.register, request.length))
            else:
                self._bus.write_i2c_block_data(driver.address, request.register, list(request.data))
                data = b""
        except OSError:
            data = None
        driver.on_answer(data, self._clock())

    def poll(self, now: float | None = None) -> bool:
        """Step the driver once, and read its registers once it is running.

        The background thread calls this every ~20ms. It is also how a test
        drives this with its own clock and a fake bus_factory - no thread,
        no real hardware, and no real waiting for the sensor's start-up
        delays. Returns False once the bus could not be opened at all.
        """

        now = self._clock() if now is None else now
        if self._bus is None:
            self._bus = self._open_bus()
            if self._bus is None:
                return False
            self._detect_address(now)
            with self._lock:
                self._error = ""
                self._driver.begin(now)
            return True
        if self._driver.state in ("missing", "wrong-chip", "failed") and self._detect_address(now):
            with self._lock:
                self._driver.begin(now)
        with self._lock:
            self._driver.step(self, now)
            state = self._driver.state
        if state in ("ok", "calibrating"):
            self._read_streams(self._driver, now)
        return True

    def _detect_address(self, now: float) -> bool:
        """Find the declared chip at either address without writing to it.

        A missing board is checked again so connecting it after startup works.
        Only a matching chip ID may replace the declared default address.
        """
        if not self._auto_address or now < self._next_address_probe:
            return False
        self._next_address_probe = now + RETRY_SECONDS
        register, expected = Mpu6500Driver.WHO_AM_I, MPU6500_ID
        # Prefer the selected address when two boards answer on the bus.
        addresses = dict.fromkeys((self._driver.address, *MPU6500_ADDRESSES))
        for address in addresses:
            try:
                chip_id = self._bus.read_i2c_block_data(address, register, 1)[0]
            except (OSError, IndexError):
                continue
            if chip_id == expected:
                if address != self._driver.address:
                    with self._lock:
                        self._driver = Mpu6500Driver(replace(self.declaration, address=address))
                    return True
                return False
        return False

    def _run(self) -> None:
        try:
            while not self._stop.is_set():
                delay = POLL_SECONDS if self.poll() else RETRY_SECONDS
                self._stop.wait(delay)
        finally:
            close = getattr(self._bus, "close", None)
            if callable(close):
                close()
            with self._lock:
                self._driver.stop()

    def _read_streams(self, driver, now: float) -> None:
        """One cycle of the registers this driver reads, outside the lock -
        an I2C transaction can take a few milliseconds and must not hold up
        a heading() call from robot code."""

        streams: dict[str, bytes | None] = {}
        for register, length in driver.streams:
            try:
                data = bytes(self._bus.read_i2c_block_data(driver.address, register, length))
            except OSError:
                data = None
            streams[f"{driver.address:02x}:{register:02x}"] = data
        with self._lock:
            driver.on_readings(streams, int(now * 1000) & 0xFFFFFFFF, now)
            self._apply_pending_zero()

    def _apply_pending_zero(self) -> None:
        if self._pending_zero is not None and self._driver.state == "ok" and self._driver.yaw is not None:
            self._offset = self._driver.yaw - self._pending_zero
            self._pending_zero = None
            if self._pending_level and self._driver.pitch is not None and self._driver.roll is not None:
                self._level = (self._driver.pitch, self._driver.roll)
                self._pending_level = False

    # -- read by robot code --------------------------------------------------

    def _usable(self, now: float) -> bool:
        driver = self._driver
        return driver.state == "ok" and driver.yaw is not None and now - driver.updated <= STALE_AFTER

    @property
    def state(self) -> str:
        """ok, starting, calibrating, missing, wrong-chip, failed, or waiting."""

        with self._lock:
            return self._driver.state

    @property
    def connected(self) -> bool:
        """True while the IMU is streaming usable angles."""

        with self._lock:
            return self._usable(self._clock())

    @property
    def calibrated(self) -> bool:
        with self._lock:
            return self._usable(self._clock()) and self._driver.calibrated

    @property
    def chip(self) -> str:
        """The supported chip: MPU6500."""

        with self._lock:
            return self._driver.chip

    def heading(self) -> float | None:
        """Degrees from -180 to 180; counter-clockwise (a left turn) is positive.

        0 is where :meth:`zero` was last called, or where the IMU started.
        None while the IMU is missing, starting, calibrating, or not streaming.
        """

        total = self.total_rotation()
        return None if total is None else wrap180(total)

    def total_rotation(self) -> float | None:
        """Degrees turned since zero, counting whole turns: two left turns read 720."""

        with self._lock:
            if not self._usable(self._clock()):
                return None
            return self._driver.yaw - self._offset

    def rate(self) -> float | None:
        """Degrees per second, counter-clockwise positive."""

        with self._lock:
            return self._driver.rate if self._usable(self._clock()) else None

    def pitch(self) -> float | None:
        """Degrees; positive while the front of the robot is raised."""

        with self._lock:
            return self._tilt(self._driver.pitch, 0) if self._usable(self._clock()) else None

    def roll(self) -> float | None:
        """Degrees; positive while the right side of the robot is lower."""

        with self._lock:
            return self._tilt(self._driver.roll, 1) if self._usable(self._clock()) else None

    def _tilt(self, value, axis: int):
        """Caller holds the lock."""

        return None if value is None else value - self._level[axis]

    def zero(self, heading: float = 0.0, *, level: bool = False) -> None:
        """Make the direction the robot faces now read ``heading`` degrees.

        ``level=True`` also makes the robot's present pitch and roll read 0.
        Nothing zeroes the IMU except this call: it keeps its zero until the
        next one (a heading cannot outlive a power-off, since the MPU6500 has
        no compass). Called before the IMU is streaming, the heading takes
        effect on the first reading; the level only when it is streaming.
        """

        target = float(heading)
        with self._lock:
            usable = self._usable(self._clock())
            if usable:
                self._offset = self._driver.yaw - target
                self._pending_zero = None
            else:
                self._pending_zero = target
            if level and usable and self._driver.pitch is not None and self._driver.roll is not None:
                self._level = (self._driver.pitch, self._driver.roll)

    @property
    def level(self) -> tuple[float, float]:
        """The (pitch, roll) that read as level; (0, 0) until zero(level=True)."""

        with self._lock:
            return self._level

    def set_level(self, pitch: float, roll: float) -> None:
        """Restore a level saved from an earlier zero(level=True)."""

        values = (float(pitch), float(roll))
        if not all(math.isfinite(value) and abs(value) <= 90.0 for value in values):
            raise ValueError("A level offset is two angles between -90 and 90 degrees")
        with self._lock:
            self._level = values

    def calibrate_zero(self) -> None:
        """Measure bias at rest, then make the first usable pose the new zero."""
        with self._lock:
            if not self._usable(self._clock()):
                raise ValueError("Wait for a connected, calibrated IMU before calibrating again")
            self._driver.recalibrate()
            self._pending_zero = 0.0
            self._pending_level = True

    def recalibrate(self) -> None:
        """Measure the gyro at rest again; keep the robot still for a second.

        The heading and its zero are kept. The gyro is also measured once at
        every start-up, because its resting error changes with temperature and
        an unmeasured one would make the heading drift.
        """

        with self._lock:
            self._driver.recalibrate()

    def describe(self) -> str:
        """One sentence on what this IMU is doing, for people."""

        with self._lock:
            return self._describe()

    def _describe(self) -> str:
        """Caller holds the lock."""

        driver = self._driver
        if self._error:
            return self._error
        where = f"{driver.chip} at 0x{driver.address:02X}"
        state = driver.state
        if state == "missing":
            setup = (
                " Check soldered header joints, NCS high for I2C and SDA/SCL pull-ups to 3.3 V."
            )
            return (
                f"Nothing answers at 0x{driver.address:02X} on I2C bus {self._bus_number}. "
                "Check the reference Pi wiring: 3.3 V pin 17, GND pin 6 and AD0 pin 20, "
                "SDA pin 11 and SCL pin 12." + setup
            )
        if state == "wrong-chip":
            return f"0x{driver.address:02X} answered, but {driver.message}."
        if state == "failed":
            return f"{where} {driver.message or 'could not be set up'}. Retrying every 2 seconds."
        if state == "starting":
            return f"{where} is starting."
        if state in ("ok", "calibrating") and self._clock() - driver.updated > STALE_AFTER:
            return f"{where}: readings are stale; heading unavailable."
        described = driver.describe()
        if state == "calibrating":
            return f"{where}: {described or 'calibrating'}. Keep the robot still."
        if state == "ok":
            return f"{where}: {described or 'streaming'}."
        return "Waiting to start."

    def reading(self) -> IMUReading:
        """This IMU for the Driver Station's gyro panel."""

        with self._lock:
            now = self._clock()
            usable = self._usable(now)
            driver = self._driver
            return IMUReading(
                name=self.name,
                connected=(driver.state == "starting" or (
                    driver.state in ("ok", "calibrating") and now - driver.updated <= STALE_AFTER
                )),
                calibrated=usable and driver.calibrated,
                yaw=wrap180(driver.yaw - self._offset) if usable else None,
                pitch=self._tilt(driver.pitch, 0) if usable else None,
                roll=self._tilt(driver.roll, 1) if usable else None,
                rate=driver.rate if usable else None,
                detail=self._describe(),
            )

    def close(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
        else:
            # A manually polled reader owns its bus just as a threaded one does.
            close = getattr(self._bus, "close", None)
            if callable(close):
                close()
            with self._lock:
                self._driver.stop()
