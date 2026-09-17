"""The Arduino GIGA R1 WiFi as the robot's sensor extender.

The GIGA runs ``firmware/giga_sensor_bridge``, installed from the Pi with
``motionmodule giga flash``. It reads digital pins as on or off, analog pins
as numbers, and does the IMU maths itself. A robot says what is wired to it,
normally in ``sensors.py``::

    giga = module.giga(
        pins=[GigaPin("A0", "Arm potentiometer", kind="analog"),
              GigaPin("D22", "Intake beam", pull="up")],
        imus=[GigaIMU("bno055", "Main IMU")],
    )
    giga.value("Intake beam")        # True, False, or None when not streaming
    giga.imu("Main IMU").heading()   # degrees, counter-clockwise positive

MotionModule finds the board by its USB ID, sends those declarations after
every connection, and keeps the newest readings from a background thread, so
robot code reads them instantly and never touches the serial port.
"""

from __future__ import annotations

import errno
import json
import math
import threading
import time
import weakref
import zlib
from dataclasses import dataclass
from typing import Callable, Iterable

from .telemetry import IMUReading, SensorReading, USBController
from .usb import sensor_controllers


GIGA_BOARD_ID = "arduino_giga_r1_wifi"
GIGA_DIGITAL_PINS = frozenset(f"D{number}" for number in range(76))
GIGA_ANALOG_PINS = frozenset(f"A{number}" for number in range(8))
# The version of firmware/giga_sensor_bridge shipped beside this code. The
# firmware tests keep the two equal.
GIGA_FIRMWARE_VERSION = "2.0.0"
PROTOCOL_V1 = "motionmodule-sensor-v1"
PROTOCOL_V2 = "motionmodule-sensor-v2"
MAX_GIGA_IMUS = 2
MAX_GIGA_READINGS = 20
FLASH_COMMAND = "motionmodule giga flash"

# chip name -> (firmware driver, default address, address with the jumper set)
IMU_CHIPS = {
    "bno055": ("BNO055", 0x28, 0x29),
    "ism330dhcx": ("LSM6", 0x6A, 0x6B),
    "lsm6dsox": ("LSM6", 0x6A, 0x6B),
    "lsm6dso": ("LSM6", 0x6A, 0x6B),
    "lsm6ds3trc": ("LSM6", 0x6A, 0x6B),
}
# WHO_AM_I values of the 6-axis chips the firmware drives.
LSM6_CHIPS = {0x69: "LSM6DS33", 0x6A: "LSM6DS3TR-C", 0x6B: "ISM330DHCX", 0x6C: "LSM6DSOX"}
IMU_STATES = {"starting", "calibrating", "ok", "missing", "wrong-chip", "failed"}

# Two bridges reading one board would split its stream between them.
_ACTIVE_BRIDGES: "weakref.WeakSet[GigaR1Bridge]" = weakref.WeakSet()
_ACTIVE_LOCK = threading.Lock()


def _finite(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _wrap180(angle: float) -> float:
    return (angle + 180.0) % 360.0 - 180.0


def _version(text: str) -> tuple[int, ...]:
    parts = []
    for piece in str(text).split("."):
        digits = "".join(character for character in piece if character.isdigit())
        parts.append(int(digits) if digits else 0)
    return tuple(parts)


@dataclass(frozen=True, slots=True)
class GigaPin:
    """One Arduino GIGA pin declared by a robot project.

    Digital pins read True (high) or False (low). Analog pins read 0 at 0 V to
    4095 at 3.3 V, then ``scale`` and ``offset`` turn that into your units.
    """

    pin: str
    name: str
    kind: str = "digital"
    pull: str = "none"
    unit: str = ""
    minimum: float | None = None
    maximum: float | None = None
    scale: float = 1.0
    offset: float = 0.0
    detail: str = ""

    def __post_init__(self) -> None:
        pin = self.pin.strip().upper()
        kind = self.kind.strip().casefold()
        pull = self.pull.strip().casefold()
        if kind not in {"analog", "digital"}:
            raise ValueError("GIGA pin kind must be 'analog' or 'digital'")
        allowed = GIGA_ANALOG_PINS if kind == "analog" else GIGA_DIGITAL_PINS
        if pin not in allowed:
            label = "A0-A7" if kind == "analog" else "D0-D75"
            raise ValueError(f"{pin} is not a supported GIGA {kind} input; use {label}")
        if pull not in {"none", "up", "down"} or kind == "analog" and pull != "none":
            raise ValueError("Digital pull must be none, up, or down; analog inputs use none")
        if not self.name.strip():
            raise ValueError("Every GIGA pin needs a sensor name")
        for label, value in (("scale", self.scale), ("offset", self.offset)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
                raise ValueError(f"GIGA pin {label} must be a finite number")
        object.__setattr__(self, "pin", pin)
        object.__setattr__(self, "kind", kind)
        object.__setattr__(self, "pull", pull)

    @property
    def bridge_mode(self) -> str:
        if self.kind == "analog":
            return "A"
        return {"none": "D", "up": "U", "down": "N"}[self.pull]

    def reading(self, raw, *, connected: bool, detail: str = "") -> SensorReading:
        value = None
        if connected and self.kind == "digital":
            value = bool(raw)
        elif connected:
            try:
                number = float(raw)
                value = number * float(self.scale) + float(self.offset)
            except (TypeError, ValueError):
                connected = False
        return SensorReading(
            self.name,
            value,
            kind=self.kind,
            unit=self.unit,
            channel=self.pin,
            connected=connected,
            status="ok" if connected else "offline",
            minimum=self.minimum,
            maximum=self.maximum,
            detail=self.detail or detail,
        )


@dataclass(frozen=True, slots=True)
class GigaIMU:
    """One IMU on the GIGA's I2C pins: SDA 20, SCL 21, 3.3V, and GND.

    ``chip`` is ``"bno055"`` for the 9-axis BNO055, or ``"ism330dhcx"``,
    ``"lsm6dsox"``, ``"lsm6dso"``, or ``"lsm6ds3trc"`` for a 6-axis IMU.
    ``address`` defaults to the board's own (0x28 for the BNO055, 0x6A for
    the 6-axis boards). ``compass=True`` lets a BNO055 use its magnetometer
    for a north-referenced heading, which motors and steel can disturb.
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

    @property
    def bridge_spec(self) -> str:
        return f"{self.driver}@{self.address:02X}" + (":NDOF" if self.compass else "")


class LiveIMU:
    """The newest readings from one GIGA IMU, kept current by its bridge.

    Angles are degrees. Yaw counts up as the robot turns counter-clockwise
    seen from above, which is also the direction a positive ``rotate`` drives
    the robot, so ``target - heading()`` is the way to turn.
    """

    def __init__(self, bridge: "GigaR1Bridge", declaration: GigaIMU) -> None:
        self._bridge = bridge
        self.declaration = declaration
        self.name = declaration.name
        self._offset = 0.0
        self._pending_zero: float | None = None
        self._clear()

    # -- updated by the bridge, with its lock held -------------------------

    def _clear(self, state: str = "waiting") -> None:
        self._state = state
        self._chip_id: int | None = None
        self._yaw: float | None = None
        self._rate: float | None = None
        self._pitch: float | None = None
        self._roll: float | None = None
        self._calibrated = False
        self._levels: tuple[int, ...] | None = None
        self._moving = False
        self._seen: tuple[int, ...] = ()
        self._updated = 0.0

    def _update(self, entry, now: float) -> None:
        declaration = self.declaration
        if (
            not isinstance(entry, dict)
            or entry.get("type") != declaration.driver.casefold()
            or entry.get("addr") != declaration.address
        ):
            self._clear()
            return
        state = entry.get("state")
        self._state = state if state in IMU_STATES else "failed"
        chip_id = entry.get("id")
        self._chip_id = chip_id if isinstance(chip_id, int) and not isinstance(chip_id, bool) else None
        self._moving = bool(entry.get("moving"))
        seen = entry.get("seen")
        self._seen = tuple(
            address for address in (seen if isinstance(seen, list) else ())
            if isinstance(address, int) and not isinstance(address, bool) and 0 <= address < 128
        )[:6]
        self._updated = now
        if self._state != "ok":
            self._calibrated = False
            return
        self._rate = _finite(entry.get("rate"))
        self._pitch = _finite(entry.get("pitch"))
        self._roll = _finite(entry.get("roll"))
        self._calibrated = bool(entry.get("cal"))
        levels = entry.get("levels")
        if isinstance(levels, list) and len(levels) == 4 and all(
            isinstance(level, int) and not isinstance(level, bool) and 0 <= level <= 3 for level in levels
        ):
            self._levels = tuple(levels)
        yaw = _finite(entry.get("yaw"))
        if yaw is not None:
            self._yaw = yaw
            if self._pending_zero is not None:
                self._offset = yaw - self._pending_zero
                self._pending_zero = None

    def _board_restarted(self) -> None:
        # The board counts yaw from zero again, so an old zero means nothing.
        self._offset = 0.0
        self._clear()

    def _usable(self, now: float) -> bool:
        return (
            self._state == "ok"
            and self._yaw is not None
            and self._bridge._streaming(now)
            and now - self._updated <= self._bridge.stale_after
        )

    def _present(self, now: float) -> bool:
        return (
            self._state in {"starting", "calibrating", "ok"}
            and self._bridge._streaming(now)
            and now - self._updated <= self._bridge.stale_after
        )

    # -- read by robot code ------------------------------------------------

    @property
    def state(self) -> str:
        """ok, starting, calibrating, missing, wrong-chip, failed, waiting, or simulated."""

        with self._bridge._lock:
            if self._bridge.simulated:
                return "simulated"
            if self._bridge._legacy_firmware:
                return "update-firmware"
            return self._state if self._present(time.monotonic()) or self._state in {
                "missing", "wrong-chip", "failed"
            } else "waiting"

    @property
    def connected(self) -> bool:
        """True while the IMU is streaming usable angles."""

        with self._bridge._lock:
            return self._usable(time.monotonic())

    @property
    def calibrated(self) -> bool:
        with self._bridge._lock:
            return self._usable(time.monotonic()) and self._calibrated

    @property
    def chip(self) -> str:
        """The chip that answered, such as BNO055 or ISM330DHCX."""

        with self._bridge._lock:
            return self._chip_name()

    def _chip_name(self) -> str:
        if self.declaration.driver == "BNO055":
            return "BNO055"
        return LSM6_CHIPS.get(self._chip_id, self.declaration.chip.upper())

    def heading(self) -> float | None:
        """Degrees from -180 to 180; counter-clockwise (a left turn) is positive.

        0 is where :meth:`zero` was last called, or where the IMU started.
        None while the IMU is missing, starting, calibrating, or not streaming.
        """

        total = self.total_rotation()
        return None if total is None else _wrap180(total)

    def total_rotation(self) -> float | None:
        """Degrees turned since zero, counting whole turns: two left turns read 720."""

        with self._bridge._lock:
            if not self._usable(time.monotonic()):
                return None
            return self._yaw - self._offset

    def rate(self) -> float | None:
        """Degrees per second, counter-clockwise positive."""

        with self._bridge._lock:
            return self._rate if self._usable(time.monotonic()) else None

    def pitch(self) -> float | None:
        """Degrees; positive while the front of the robot is raised."""

        with self._bridge._lock:
            return self._pitch if self._usable(time.monotonic()) else None

    def roll(self) -> float | None:
        """Degrees; positive while the right side of the robot is lower."""

        with self._bridge._lock:
            return self._roll if self._usable(time.monotonic()) else None

    def zero(self, heading: float = 0.0) -> None:
        """Make the direction the robot faces now read ``heading`` degrees.

        Called before the IMU is streaming, it takes effect on the first reading.
        """

        target = _finite(heading)
        if target is None:
            raise ValueError("zero() needs a finite heading in degrees")
        with self._bridge._lock:
            if self._usable(time.monotonic()):
                self._offset = self._yaw - target
                self._pending_zero = None
            else:
                self._pending_zero = target

    def describe(self) -> str:
        """One sentence on what this IMU is doing, for people."""

        with self._bridge._lock:
            return self._describe(time.monotonic())

    def _describe(self, now: float) -> str:
        declaration = self.declaration
        bridge = self._bridge
        where = f"{self._chip_name()} at 0x{declaration.address:02X}"
        if bridge.simulated:
            return "Simulated robot: the GIGA is not opened."
        if bridge._legacy_firmware:
            return f"The GIGA runs the original bridge sketch, which cannot read IMUs. Run {FLASH_COMMAND} on the Pi."
        state = self._state
        if state == "missing":
            text = (
                f"Nothing answers at 0x{declaration.address:02X}. Check 3.3V, GND, SDA 20 and SCL 21."
            )
            if self._seen:
                text += " Answering instead: " + ", ".join(f"0x{address:02X}" for address in self._seen) + "."
            return text
        if state == "wrong-chip":
            found = f" (chip id 0x{self._chip_id:02X})" if self._chip_id is not None else ""
            return f"0x{declaration.address:02X} answered, but not as a {declaration.chip.upper()}{found}."
        if state == "failed":
            return f"{where} stopped answering. Retrying every 2 seconds."
        if not self._present(now):
            return bridge._status_text(now)
        if state == "starting":
            return f"{where} is starting."
        if state == "calibrating":
            if self._moving:
                return f"{where}: calibrating, but the robot is moving. Keep it still."
            return f"{where}: calibrating the gyro. Keep the robot still."
        if declaration.driver == "BNO055" and self._levels is not None:
            system, gyro, accel, magnet = self._levels
            text = f"{where}: calibration gyro {gyro}/3, accelerometer {accel}/3"
            if declaration.compass:
                text += f", magnetometer {magnet}/3, overall {system}/3"
            return text + ("." if self._calibrated else ". Hold still for a few seconds to finish.")
        return f"{where}: streaming."

    def reading(self) -> IMUReading:
        """This IMU for the Driver Station's gyro panel."""

        with self._bridge._lock:
            now = time.monotonic()
            usable = self._usable(now)
            yaw = _wrap180(self._yaw - self._offset) if usable else None
            return IMUReading(
                name=self.name,
                connected=self._present(now),
                calibrated=usable and self._calibrated,
                yaw=yaw,
                pitch=self._pitch if usable else None,
                roll=self._roll if usable else None,
                rate=self._rate if usable else None,
                detail=self._describe(now),
            )

    def _sensor_reading(self, now: float) -> SensorReading:
        usable = self._usable(now)
        present = self._present(now)
        return SensorReading(
            f"{self.name} heading",
            _wrap180(self._yaw - self._offset) if usable else None,
            kind="analog",
            unit="°",
            channel=f"I2C 0x{self.declaration.address:02X}",
            connected=present,
            status="ok" if usable and self._calibrated else "warning" if present else "offline",
            minimum=-180,
            maximum=180,
            detail=self._describe(now),
        )


class GigaR1Bridge:
    """Find one GIGA R1, configure it, and keep its newest readings.

    The board is identified from Arduino's USB VID/PID. The pin and IMU
    declarations are sent after every connection, so one firmware serves any
    robot. A background thread does all of the USB work; robot code only reads
    values it already has. ``simulated=True`` never opens the board.
    """

    def __init__(
        self,
        pins: Iterable[GigaPin] = (),
        *,
        imus: Iterable[GigaIMU] = (),
        serial: str = "",
        baudrate: int = 115200,
        stale_after: float = 1.0,
        discovery: Callable[[], list[dict]] = sensor_controllers,
        serial_factory=None,
        simulated: bool = False,
        autostart: bool = True,
    ) -> None:
        self.pins = tuple(pins)
        self.imus = tuple(imus)
        if not all(isinstance(pin, GigaPin) for pin in self.pins):
            raise ValueError("GIGA pins must be GigaPin(...) declarations")
        if not all(isinstance(imu, GigaIMU) for imu in self.imus):
            raise ValueError("GIGA IMUs must be GigaIMU(...) declarations")
        if not self.pins and not self.imus:
            raise ValueError("Configure at least one GIGA sensor pin or IMU")
        if len(self.imus) > MAX_GIGA_IMUS:
            raise ValueError("The GIGA bridge reads up to two IMUs")
        if len(self.pins) + len(self.imus) > MAX_GIGA_READINGS:
            raise ValueError("A Driver Station USB controller supports up to 20 sensor pins and IMUs")
        if len({pin.pin for pin in self.pins}) != len(self.pins):
            raise ValueError("Each GIGA pin can be configured only once")
        if len({imu.address for imu in self.imus}) != len(self.imus):
            raise ValueError("Two GIGA IMUs cannot share an I2C address")
        names = [pin.name for pin in self.pins] + [imu.name for imu in self.imus]
        if len({name.casefold() for name in names}) != len(names):
            raise ValueError("Every GIGA pin and IMU needs its own name")
        self.serial = serial.strip()
        self.baudrate = int(baudrate)
        self.stale_after = max(0.1, float(stale_after))
        self.simulated = bool(simulated)
        self._autostart = autostart
        self._discovery = discovery
        self._serial_factory = serial_factory

        pin_text = ",".join(f"{pin.pin}:{pin.bridge_mode}" for pin in self.pins) or "-"
        imu_text = ",".join(imu.bridge_spec for imu in self.imus) or "-"
        body = f"{pin_text} {imu_text}"
        self.config_id = zlib.crc32(body.encode("ascii")) & 0x7FFFFFFF
        self._config_line = f"MM2 CONFIG {self.config_id} {body}\n".encode("ascii")
        self._legacy_line = f"MM1 CONFIG {pin_text}\n".encode("ascii") if self.pins else b""

        self._lock = threading.RLock()
        self._io_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._live = {imu.name: LiveIMU(self, imu) for imu in self.imus}

        self._port = None
        self._device: dict | None = None
        self._buffer = bytearray()
        self._last_discovery = 0.0
        self._last_bytes = 0.0
        self._config_sent_at = 0.0
        self._commands: list[bytes] = []
        self._values: dict[str, object] = {}
        self._last_packet = 0.0
        self._configured = False
        self._firmware = ""
        self._legacy_firmware = False
        self._board_error = ""
        self._error = "Waiting for the Arduino GIGA R1 WiFi"

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> "GigaR1Bridge":
        """Start the background reader. Safe to call more than once."""

        with self._lock:
            if self.simulated or self._thread is not None:
                return self
            with _ACTIVE_LOCK:
                for other in _ACTIVE_BRIDGES:
                    if other is not self and (not other.serial or not self.serial or other.serial == self.serial):
                        raise RuntimeError(
                            "The GIGA is already being read by another GigaR1Bridge. Set it up once, "
                            "in sensors.py, and share that object (dashboard.py can use drive.sensors)."
                        )
                _ACTIVE_BRIDGES.add(self)
            self._stop.clear()
            self._thread = threading.Thread(target=self._run, name="motionmodule-giga", daemon=True)
            self._thread.start()
        return self

    def close(self) -> None:
        """Stop reading and release the board's port."""

        with self._lock:
            thread, self._thread = self._thread, None
            self._stop.set()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=1.5)
        with self._io_lock:
            self._disconnect("Closed")
        with _ACTIVE_LOCK:
            _ACTIVE_BRIDGES.discard(self)

    def matches(self, pins: Iterable[GigaPin] = (), imus: Iterable[GigaIMU] = (), serial: str = "") -> bool:
        return (tuple(pins), tuple(imus), serial.strip()) == (self.pins, self.imus, self.serial)

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                connected = self.poll()
            except Exception as error:  # the reader has to outlive any surprise
                with self._io_lock:
                    self._disconnect(f"GIGA bridge error: {error}")
                connected = False
            if not connected:
                self._stop.wait(0.2)

    # -- USB work, on the reader thread ------------------------------------

    def poll(self) -> bool:
        """One round of USB work: find the board, configure it, read what arrived.

        The reader thread calls this over and over; tests call it directly.
        Returns True while the board's port is open.
        """

        if self.simulated:
            return False
        with self._io_lock:
            now = time.monotonic()
            if self._port is None:
                device = self._discover(now)
                if device is None:
                    return False
                self._open(device, now)
                if self._port is None:
                    return False
            self._send_pending(now)
            if self._port is not None:
                self._read(now)
            return self._port is not None

    def _discover(self, now: float) -> dict | None:
        if self._last_discovery and now - self._last_discovery < 1.0:
            return None
        self._last_discovery = now
        try:
            candidates = self._discovery()
        except Exception as error:
            with self._lock:
                self._error = f"Could not list USB devices: {error}"
            return None
        device = next((
            item for item in candidates
            if item.get("board_id") == GIGA_BOARD_ID
            and (not self.serial or item.get("serial") == self.serial)
        ), None)
        with self._lock:
            self._device = device
            if device is None:
                self._error = "Waiting for the Arduino GIGA R1 WiFi. Plug it into one of the Pi's USB ports."
            elif device.get("mode") == "bootloader":
                self._error = (
                    f"The GIGA is waiting for new firmware (its reset button was pressed twice). "
                    f"Run {FLASH_COMMAND}, or press reset once."
                )
                return None
        return device

    def _open(self, device: dict, now: float) -> None:
        port = str(device.get("port", ""))
        if not port:
            with self._lock:
                self._error = "GIGA detected, but its USB serial port is missing"
            return
        try:
            factory = self._serial_factory
            if factory is None:
                from serial import Serial as factory  # type: ignore[no-redef]
            handle = factory(port, self.baudrate, timeout=0.05, write_timeout=0.5)
        except (ImportError, OSError, ValueError) as error:
            message = f"Could not open {port}: {error}"
            # pyserial reports a refused open as its own OSError carrying EACCES.
            if isinstance(error, PermissionError) or getattr(error, "errno", None) == errno.EACCES:
                message += ". The Pi user needs the dialout group: rerun the MotionModule installer, then reboot."
            with self._lock:
                self._error = message
            return
        self._port = handle
        self._buffer.clear()
        self._last_bytes = now
        with self._lock:
            self._configured = False
            self._legacy_firmware = False
            self._error = "Connected. Waiting for the MotionModule firmware to answer."
        self._write(self._config_line)
        self._config_sent_at = now

    def _write(self, data: bytes) -> None:
        if self._port is None or not data:
            return
        try:
            self._port.write(data)
        except (OSError, ValueError) as error:  # pyserial's errors are OSErrors
            self._disconnect(f"Could not write to the GIGA: {error}")

    def _send_pending(self, now: float) -> None:
        with self._lock:
            commands, self._commands = self._commands, []
            configured = self._configured
            legacy = self._legacy_firmware
        for command in commands:
            self._write(command)
        if self._port is not None and not configured and now - self._config_sent_at >= 1.0:
            self._write(self._legacy_line if legacy else self._config_line)
            self._config_sent_at = now

    def _read(self, now: float) -> None:
        port = self._port
        try:
            waiting = int(getattr(port, "in_waiting", 0) or 0)
            data = port.read(waiting if waiting > 0 else 1)
        except (OSError, ValueError) as error:
            self._disconnect(f"Lost the GIGA's USB connection: {error}")
            return
        if not data:
            if now - self._last_bytes > 3.0:
                self._disconnect(
                    f"The GIGA is not sending anything. If it runs another sketch, run {FLASH_COMMAND}."
                )
            return
        self._last_bytes = now
        self._buffer += data
        while True:
            end = self._buffer.find(b"\n")
            if end < 0:
                break
            line = bytes(self._buffer[:end])
            del self._buffer[:end + 1]
            self._handle_line(line, now)
        if len(self._buffer) > 16384:  # a runaway line without an end
            self._buffer.clear()

    def _disconnect(self, message: str) -> None:
        port, self._port = self._port, None
        with self._lock:
            self._error = message
            self._values = {}
            self._last_packet = 0.0
            self._configured = False
            for live in self._live.values():
                live._clear()
        if port is not None:
            try:
                port.close()
            except (OSError, ValueError):
                pass

    def _handle_line(self, line: bytes, now: float) -> None:
        text = line.decode("utf-8", errors="replace").strip()
        if not text.startswith("{"):
            return
        try:
            payload = json.loads(text)
        except ValueError:
            return
        if not isinstance(payload, dict):
            return
        protocol = payload.get("protocol")
        if protocol == PROTOCOL_V2:
            self._handle_current(payload, now)
        elif protocol == PROTOCOL_V1:
            self._handle_original(payload, now)

    def _handle_current(self, payload: dict, now: float) -> None:
        firmware = payload.get("firmware")
        with self._lock:
            self._legacy_firmware = False
            if isinstance(firmware, str) and firmware:
                self._firmware = firmware[:16]
            event = payload.get("event")
            if event == "hello":
                # A hello after readings means the board started over.
                if self._configured:
                    self._configured = False
                    self._config_sent_at = 0.0
                    for live in self._live.values():
                        live._board_restarted()
                return
            if event == "error":
                message = payload.get("message")
                self._board_error = str(message)[:120] if message else "unknown error"
                return
            if event is not None:
                return
            if payload.get("config") != self.config_id:
                # Readings for some other set of sensors: send ours again.
                if self._configured:
                    self._config_sent_at = 0.0
                self._configured = False
                return
            values = payload.get("values")
            if not isinstance(values, dict):
                return
            self._configured = True
            self._board_error = ""
            self._values = {str(key).upper(): value for key, value in values.items()}
            self._last_packet = now
            imus = payload.get("imus")
            imus = imus if isinstance(imus, list) else []
            for index, declaration in enumerate(self.imus):
                self._live[declaration.name]._update(imus[index] if index < len(imus) else None, now)
            self._error = "Streaming"

    def _handle_original(self, payload: dict, now: float) -> None:
        with self._lock:
            if payload.get("firmware"):
                # Current firmware left in the old mode by older MotionModule
                # software. Sending the current configuration switches it back.
                self._legacy_firmware = False
                self._firmware = str(payload["firmware"])[:16]
                if self._configured:
                    self._config_sent_at = 0.0
                self._configured = False
                return
            if not self._legacy_firmware:
                self._legacy_firmware = True
                self._firmware = "1"
                self._configured = False
                self._config_sent_at = 0.0
            values = payload.get("values")
            if payload.get("event") is not None or not isinstance(values, dict):
                return
            self._values = {str(key).upper(): value for key, value in values.items()}
            self._last_packet = now
            self._configured = all(pin.pin in self._values for pin in self.pins) and bool(self.pins)
            self._error = "Streaming pins from the original bridge sketch"

    # -- reading, from any thread ------------------------------------------

    def _streaming(self, now: float) -> bool:
        return bool(self._last_packet and now - self._last_packet <= self.stale_after)

    def _status_text(self, now: float) -> str:
        if self.simulated:
            return "Simulated robot: the GIGA is not opened."
        text = self._error
        if self._streaming(now):
            if self._legacy_firmware:
                text = (
                    "Streaming pins from the original bridge sketch. It cannot read IMUs; "
                    f"run {FLASH_COMMAND} to update it."
                )
            elif self._firmware and _version(self._firmware) < _version(GIGA_FIRMWARE_VERSION):
                text = (
                    f"Streaming, firmware {self._firmware}. MotionModule ships {GIGA_FIRMWARE_VERSION}: "
                    f"run {FLASH_COMMAND}."
                )
            else:
                text = f"Streaming, firmware {self._firmware or 'unknown'}."
        elif self._last_packet:
            text = f"No readings for {now - self._last_packet:.1f} s. {self._error}"
        if self._board_error:
            text += f" The GIGA rejected the configuration: {self._board_error}."
        return text

    @property
    def streaming(self) -> bool:
        with self._lock:
            return self._streaming(time.monotonic())

    @property
    def firmware(self) -> str:
        """The firmware version the GIGA reported, "1" for the original sketch, or ""."""

        with self._lock:
            return self._firmware

    @property
    def status(self) -> str:
        with self._lock:
            return self._status_text(time.monotonic())

    def _pin(self, name: str) -> GigaPin:
        wanted = str(name).strip()
        for pin in self.pins:
            if pin.name == wanted or pin.pin == wanted.upper():
                return pin
        declared = ", ".join(repr(pin.name) for pin in self.pins) or "none"
        raise ValueError(f"No GIGA pin is named {wanted!r}. Declared pins: {declared}")

    def value(self, name: str):
        """The newest reading of one declared pin, by its name or pin label.

        Digital pins give True or False, analog pins their scaled number, and
        None means there is no fresh reading.
        """

        pin = self._pin(name)
        with self._lock:
            if not self._streaming(time.monotonic()) or pin.pin not in self._values:
                return None
            reading = pin.reading(self._values[pin.pin], connected=True)
        return reading.value if reading.connected else None

    def imu(self, name: str | None = None) -> LiveIMU:
        """One declared IMU. The name may be left out when there is only one."""

        if name is None:
            if len(self.imus) != 1:
                raise ValueError("Name the IMU: this GIGA declares " + (
                    ", ".join(repr(imu.name) for imu in self.imus) or "no IMUs"
                ))
            return self._live[self.imus[0].name]
        try:
            return self._live[str(name).strip()]
        except KeyError:
            declared = ", ".join(repr(imu.name) for imu in self.imus) or "none"
            raise ValueError(f"No GIGA IMU is named {name!r}. Declared IMUs: {declared}") from None

    def calibrate(self) -> None:
        """Measure the 6-axis gyro bias again. Keep the robot still for a second."""

        with self._lock:
            self._commands.append(b"MM2 CALIBRATE\n")

    def snapshot(self) -> USBController:
        if self._autostart:
            self.start()  # dashboard.py files written before start() only call snapshot()
        with self._lock:
            now = time.monotonic()
            streaming = self._streaming(now)
            detail = self._status_text(now)
            readings = [
                pin.reading(
                    self._values.get(pin.pin),
                    connected=streaming and pin.pin in self._values,
                    detail=detail,
                )
                for pin in self.pins
            ]
            readings.extend(self._live[imu.name]._sensor_reading(now) for imu in self.imus)
            device = None if self.simulated else self._device
            if device is None:
                bridge = "simulated" if self.simulated else "offline"
            else:
                bridge = "streaming" if streaming else "waiting-for-bridge"
            return USBController(
                name="Arduino GIGA R1 WiFi",
                board_id=GIGA_BOARD_ID,
                connected=device is not None,
                serial=str((device or {}).get("serial", "")),
                port=str((device or {}).get("port", "")),
                bridge=bridge,
                pins=tuple(readings),
                detail=detail,
            )

    # -- for firmware updates ----------------------------------------------

    def release(self) -> bool:
        """Stop reading and free the port, returning whether it was running."""

        with self._lock:
            running = self._thread is not None
        self.close()
        return running


def active_bridges() -> list[GigaR1Bridge]:
    """Bridges currently reading a GIGA in this program."""

    with _ACTIVE_LOCK:
        return list(_ACTIVE_BRIDGES)
