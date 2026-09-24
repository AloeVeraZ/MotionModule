"""Experimental Arduino GIGA R1 WiFi USB GPIO expansion.

The GIGA only moves bytes. It reads the pins and I2C registers this side asks
for and sends the numbers up its USB cable; the Pi decides what is wired
where, sets the sensors up, and works out what the readings mean. A robot says
what is connected, normally in ``sensors.py``::

    pins = []  # Declare only additional inputs actually wired to the board.
    giga = module.giga(pins=pins)
    # giga.value(name) reads a declared input, or None when not streaming.

The reference Mecanum robot uses a Pi-connected MPU9255 and does not start
this extension. The bridge discovers a supported board, not its attached
sensors. Its bundled firmware targets GIGA R1 WiFi, not Uno or Mega.

MotionModule finds the board by its USB ID, sends those declarations after
every connection, and keeps the newest readings from a background thread, so
robot code reads them instantly and never touches the serial port. The sensor
drivers themselves live in :mod:`motion_module.imu`.
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

from .imu import IMU_CHIPS, LSM6_CHIPS, GigaIMU, Read, Write, driver_for, wrap180
from .telemetry import IMUReading, SensorReading, USBController
from .usb import sensor_controllers


GIGA_BOARD_ID = "arduino_giga_r1_wifi"
GIGA_DIGITAL_PINS = frozenset(f"D{number}" for number in range(76))
GIGA_ANALOG_PINS = frozenset(f"A{number}" for number in range(8))
# The version of firmware/giga_sensor_bridge shipped beside this code. The
# firmware tests keep the two equal.
GIGA_FIRMWARE_VERSION = "3.0.0"
PROTOCOL_V1 = "motionmodule-sensor-v1"
PROTOCOL = "motionmodule-sensor-v3"
MAX_GIGA_IMUS = 2
MAX_GIGA_READINGS = 20
MAX_GIGA_STREAMS = 6
DEFAULT_INTERVAL_MS = 20
FLASH_COMMAND = "motionmodule giga flash"
SILENT_SECONDS = 3.0

__all__ = [
    "FLASH_COMMAND", "GIGA_BOARD_ID", "GIGA_FIRMWARE_VERSION", "IMU_CHIPS", "LSM6_CHIPS",
    "PROTOCOL", "PROTOCOL_V1", "GigaIMU", "GigaPin", "GigaR1Bridge", "LiveIMU", "active_bridges",
]

# Two bridges reading one board would split its stream between them.
_ACTIVE_BRIDGES: "weakref.WeakSet[GigaR1Bridge]" = weakref.WeakSet()
_ACTIVE_LOCK = threading.Lock()


def _finite(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


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


class LiveIMU:
    """The newest readings from one IMU, kept current by its bridge.

    Angles are degrees. Yaw counts up as the robot turns counter-clockwise
    seen from above, which is also the direction a positive ``rotate`` drives
    the robot, so ``target - heading()`` is the way to turn.
    """

    def __init__(self, bridge: "GigaR1Bridge", driver) -> None:
        self._bridge = bridge
        self.driver = driver
        self.declaration = driver.declaration
        self.name = driver.declaration.name
        self._offset = 0.0
        self._pending_zero: float | None = None

    # -- state, with the bridge's lock held --------------------------------

    def _usable(self, now: float) -> bool:
        driver = self.driver
        return (
            driver.state == "ok"
            and driver.yaw is not None
            and self._bridge._streaming(now)
            and now - driver.updated <= self._bridge.stale_after
        )

    def _present(self, now: float) -> bool:
        driver = self.driver
        if driver.state not in {"starting", "calibrating", "ok"} or not self._bridge._streaming(now):
            return False
        # A sensor still being set up has no readings of its own yet.
        return driver.state == "starting" or now - driver.updated <= self._bridge.stale_after

    def _board_restarted(self) -> None:
        # The board counts from zero again, so an old zero means nothing.
        self._offset = 0.0

    def _apply_pending_zero(self) -> None:
        if self._pending_zero is not None and self.driver.state == "ok" and self.driver.yaw is not None:
            self._offset = self.driver.yaw - self._pending_zero
            self._pending_zero = None

    # -- read by robot code ------------------------------------------------

    @property
    def state(self) -> str:
        """ok, starting, calibrating, missing, wrong-chip, failed, waiting, or simulated."""

        with self._bridge._lock:
            if self._bridge.simulated:
                return "simulated"
            if self._bridge._unusable_firmware:
                return "update-firmware"
            if self._present(self._bridge._clock()) or self.driver.state in {"missing", "wrong-chip", "failed"}:
                return self.driver.state
            return "waiting"

    @property
    def connected(self) -> bool:
        """True while the IMU is streaming usable angles."""

        with self._bridge._lock:
            return self._usable(self._bridge._clock())

    @property
    def calibrated(self) -> bool:
        with self._bridge._lock:
            return self._usable(self._bridge._clock()) and self.driver.calibrated

    @property
    def chip(self) -> str:
        """The chip that answered, such as MPU9255 or ISM330DHCX."""

        with self._bridge._lock:
            return self.driver.chip

    def heading(self) -> float | None:
        """Degrees from -180 to 180; counter-clockwise (a left turn) is positive.

        0 is where :meth:`zero` was last called, or where the IMU started.
        None while the IMU is missing, starting, calibrating, or not streaming.
        """

        total = self.total_rotation()
        return None if total is None else wrap180(total)

    def total_rotation(self) -> float | None:
        """Degrees turned since zero, counting whole turns: two left turns read 720."""

        with self._bridge._lock:
            if not self._usable(self._bridge._clock()):
                return None
            return self.driver.yaw - self._offset

    def rate(self) -> float | None:
        """Degrees per second, counter-clockwise positive."""

        with self._bridge._lock:
            return self.driver.rate if self._usable(self._bridge._clock()) else None

    def pitch(self) -> float | None:
        """Degrees; positive while the front of the robot is raised."""

        with self._bridge._lock:
            return self.driver.pitch if self._usable(self._bridge._clock()) else None

    def roll(self) -> float | None:
        """Degrees; positive while the right side of the robot is lower."""

        with self._bridge._lock:
            return self.driver.roll if self._usable(self._bridge._clock()) else None

    def zero(self, heading: float = 0.0) -> None:
        """Make the direction the robot faces now read ``heading`` degrees.

        Called before the IMU is streaming, it takes effect on the first reading.
        """

        target = _finite(heading)
        if target is None:
            raise ValueError("zero() needs a finite heading in degrees")
        with self._bridge._lock:
            if self._usable(self._bridge._clock()):
                self._offset = self.driver.yaw - target
                self._pending_zero = None
            else:
                self._pending_zero = target

    def describe(self) -> str:
        """One sentence on what this IMU is doing, for people."""

        with self._bridge._lock:
            return self._describe(self._bridge._clock())

    def _describe(self, now: float) -> str:
        driver = self.driver
        bridge = self._bridge
        where = f"{driver.chip} at 0x{self.declaration.address:02X}"
        if bridge.simulated:
            return "Simulated robot: the GIGA is not opened."
        if bridge._unusable_firmware:
            return (
                "The GIGA runs firmware that cannot read IMUs. "
                f"Run {FLASH_COMMAND} on the Pi."
            )
        state = driver.state
        if state == "missing":
            text = f"Nothing answers at 0x{self.declaration.address:02X}. Check the configured sensor connection and address."
            if driver.seen:
                text += " Answering instead: " + ", ".join(f"0x{address:02X}" for address in driver.seen) + "."
            return text
        if state == "wrong-chip":
            return f"0x{self.declaration.address:02X} answered, but {driver.message}."
        if state == "failed":
            return f"{where} {driver.message or 'could not be set up'}. Retrying every 2 seconds."
        if not self._present(now):
            return bridge._status_text(now)
        if state == "starting":
            return f"{where} is starting."
        described = driver.describe()
        if state == "calibrating":
            return f"{where}: {described or 'calibrating'}. Keep the robot still."
        return f"{where}: {described or 'streaming'}."

    def reading(self) -> IMUReading:
        """This IMU for the Driver Station's gyro panel."""

        with self._bridge._lock:
            now = self._bridge._clock()
            usable = self._usable(now)
            driver = self.driver
            return IMUReading(
                name=self.name,
                connected=self._present(now),
                calibrated=usable and driver.calibrated,
                yaw=wrap180(driver.yaw - self._offset) if usable else None,
                pitch=driver.pitch if usable else None,
                roll=driver.roll if usable else None,
                rate=driver.rate if usable else None,
                detail=self._describe(now),
            )

    def _sensor_reading(self, now: float) -> SensorReading:
        usable = self._usable(now)
        present = self._present(now)
        return SensorReading(
            f"{self.name} heading",
            wrap180(self.driver.yaw - self._offset) if usable else None,
            kind="analog",
            unit="°",
            channel=f"I2C 0x{self.declaration.address:02X}",
            connected=present,
            status="ok" if usable and self.driver.calibrated else "warning" if present else "offline",
            minimum=-180,
            maximum=180,
            detail=self._describe(now),
        )


class GigaR1Bridge:
    """Find one GIGA R1, tell it what to read, and keep its newest readings.

    The board is identified from Arduino's USB VID/PID. The pin list and the
    I2C reads this robot's sensor drivers need are sent after every
    connection, so one firmware serves any robot. A background thread does all
    of the USB work; robot code only reads values it already has.
    ``simulated=True`` never opens the board.
    """

    def __init__(
        self,
        pins: Iterable[GigaPin] = (),
        *,
        imus: Iterable[GigaIMU] = (),
        serial: str = "",
        baudrate: int = 115200,
        stale_after: float = 1.0,
        interval_ms: int = DEFAULT_INTERVAL_MS,
        discovery: Callable[[], list[dict]] = sensor_controllers,
        serial_factory=None,
        clock: Callable[[], float] = time.monotonic,
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
        self.interval_ms = max(5, min(1000, int(interval_ms)))
        self.simulated = bool(simulated)
        self._autostart = autostart
        self._discovery = discovery
        self._serial_factory = serial_factory
        self._clock = clock

        self._drivers = [driver_for(imu) for imu in self.imus]
        self._live = {imu.name: LiveIMU(self, driver) for imu, driver in zip(self.imus, self._drivers)}
        streams = [
            (driver.address, register, length)
            for driver in self._drivers
            for register, length in driver.streams
        ]
        if len(streams) > MAX_GIGA_STREAMS:
            raise ValueError("The GIGA firmware repeats up to six I2C reads")

        pin_text = ",".join(f"{pin.pin}:{pin.bridge_mode}" for pin in self.pins) or "-"
        stream_text = ",".join(
            f"{address:02X}:{register:02X}:{length}" for address, register, length in streams
        ) or "-"
        body = f"{self.interval_ms} {pin_text} {stream_text}"
        self.config_id = zlib.crc32(body.encode("ascii")) & 0x7FFFFFFF
        self._config_line = f"MM3 CONFIG {self.config_id} {body}\n".encode("ascii")
        self._legacy_line = f"MM1 CONFIG {pin_text}\n".encode("ascii") if self.pins else b""

        self._lock = threading.RLock()
        self._io_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

        self._port = None
        self._device: dict | None = None
        self._buffer = bytearray()
        self._last_discovery = 0.0
        self._last_bytes = 0.0
        self._config_sent_at = 0.0
        self._commands: list[bytes] = []
        self._requests: dict[int, object] = {}
        self._next_request = 1
        self._values: dict[str, object] = {}
        self._last_packet = 0.0
        self._configured = False
        self._firmware = ""
        # The original pins-only sketch, which is still worth talking to.
        self._legacy_sketch = False
        # Firmware from another MotionModule: only flashing fixes that.
        self._unusable_protocol = ""
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

    def release(self) -> bool:
        """Stop reading and free the port, returning whether it was running."""

        with self._lock:
            running = self._thread is not None
        self.close()
        return running

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
        """One round of USB work: find the board, tell it what to read, read it.

        The reader thread calls this over and over; tests call it directly.
        Returns True while the board's port is open.
        """

        if self.simulated:
            return False
        with self._io_lock:
            now = self._clock()
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
            if self._port is not None:
                self._step_drivers(now)
            return self._port is not None

    @property
    def _unusable_firmware(self) -> bool:
        """Firmware that cannot read this robot's sensors, whichever kind."""

        return self._legacy_sketch or bool(self._unusable_protocol)

    def _step_drivers(self, now: float) -> None:
        """Let each sensor driver send its next set-up step."""

        with self._lock:
            if not self._configured or self._unusable_firmware:
                return
            for driver in self._drivers:
                driver.step(self, now)

    def request(self, driver, request) -> None:
        """Send one I2C read or write for a driver. Called by that driver."""

        if isinstance(request, Read):
            body = f"R {request.register:02X} {request.length}"
        elif isinstance(request, Write):
            body = f"W {request.register:02X} {request.data.hex()}"
        else:
            return
        with self._lock:
            seq = self._next_request
            self._next_request = seq % 1000000 + 1
            self._requests[seq] = driver
            for old in sorted(self._requests)[:-16]:  # answers that never came
                self._requests.pop(old, None)
        self._write(f"MM3 I2C {seq} {driver.address:02X} {body}\n".encode("ascii"))

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
            self._legacy_sketch = False
            self._unusable_protocol = ""
            self._requests.clear()
            self._error = "Connected. Waiting for the MotionModule firmware to answer."
            for driver in self._drivers:
                driver.stop()
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
            legacy = self._legacy_sketch
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
            if now - self._last_bytes > SILENT_SECONDS:
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
            self._requests.clear()
            for driver in self._drivers:
                driver.stop()
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
        if protocol == PROTOCOL:
            self._handle_current(payload, now)
        elif protocol == PROTOCOL_V1:
            self._handle_original(payload, now)
        elif isinstance(protocol, str) and protocol.startswith("motionmodule-sensor-"):
            # Firmware from a different MotionModule: it cannot serve this one.
            with self._lock:
                self._unusable_protocol = protocol
                self._firmware = str(payload.get("firmware", ""))[:16] or protocol.rsplit("-", 1)[-1]

    def _handle_current(self, payload: dict, now: float) -> None:
        firmware = payload.get("firmware")
        with self._lock:
            self._legacy_sketch = False
            self._unusable_protocol = ""
            if isinstance(firmware, str) and firmware:
                self._firmware = firmware[:16]
            event = payload.get("event")
            if event is not None:
                self._handle_event(event, payload, now)
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
            first = not self._configured
            self._configured = True
            self._board_error = ""
            self._values = {str(key).upper(): value for key, value in values.items()}
            self._last_packet = now
            self._error = "Streaming"
            if first:  # the board is ours: start setting the sensors up
                for driver in self._drivers:
                    driver.begin(now)
                return
            board_ms = payload.get("ms")
            board_ms = int(board_ms) if isinstance(board_ms, int) and not isinstance(board_ms, bool) else 0
            streams = self._decode_streams(payload.get("i2c"))
            for driver in self._drivers:
                driver.on_readings(streams, board_ms, now)
            for live in self._live.values():
                live._apply_pending_zero()

    def _handle_event(self, event, payload: dict, now: float) -> None:
        if event == "hello":
            # A hello after readings means the board started over.
            if self._configured:
                self._configured = False
                self._config_sent_at = 0.0
                for live in self._live.values():
                    live._board_restarted()
                for driver in self._drivers:
                    driver.stop()
            return
        if event == "error":
            message = payload.get("message")
            self._board_error = str(message)[:120] if message else "unknown error"
            return
        if event == "i2c":
            driver = self._requests.pop(payload.get("seq"), None)
            if driver is None:
                return
            data = None
            if payload.get("ok"):
                text = payload.get("data")
                try:
                    data = bytes.fromhex(text) if isinstance(text, str) else b""
                except ValueError:
                    data = None
            driver.on_answer(data, now)
            return
        if event == "scan":
            found = payload.get("found")
            addresses = tuple(
                address for address in (found if isinstance(found, list) else ())
                if isinstance(address, int) and not isinstance(address, bool) and 0 <= address < 128
            )
            for driver in self._drivers:
                driver.seen = addresses

    @staticmethod
    def _decode_streams(raw) -> dict[str, bytes | None]:
        streams: dict[str, bytes | None] = {}
        for key, value in (raw if isinstance(raw, dict) else {}).items():
            try:
                streams[str(key).casefold()] = bytes.fromhex(value) if isinstance(value, str) else None
            except ValueError:
                streams[str(key).casefold()] = None
        return streams

    def _handle_original(self, payload: dict, now: float) -> None:
        with self._lock:
            if payload.get("firmware"):
                # Current firmware left in the old mode by older MotionModule
                # software. Sending the current configuration switches it back.
                self._legacy_sketch = False
                self._firmware = str(payload["firmware"])[:16]
                if self._configured:
                    self._config_sent_at = 0.0
                self._configured = False
                return
            if not self._legacy_sketch:
                self._legacy_sketch = True
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
        if self._unusable_protocol:
            return (
                f"The GIGA runs firmware this MotionModule cannot use ({self._unusable_protocol}). "
                f"Run {FLASH_COMMAND}."
            )
        if self._streaming(now):
            if self._legacy_sketch:
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
            return self._streaming(self._clock())

    @property
    def firmware(self) -> str:
        """The firmware version the GIGA reported, "1" for the original sketch, or ""."""

        with self._lock:
            return self._firmware

    @property
    def status(self) -> str:
        with self._lock:
            return self._status_text(self._clock())

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
            if not self._streaming(self._clock()) or pin.pin not in self._values:
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
        """Measure what a 6-axis gyro reads at rest again. Keep the robot still."""

        with self._lock:
            for driver in self._drivers:
                driver.recalibrate()

    def scan(self) -> None:
        """Ask which I2C addresses answer. The result reaches a missing IMU's detail."""

        with self._lock:
            self._commands.append(f"MM3 SCAN {self._next_request}\n".encode("ascii"))

    def snapshot(self) -> USBController:
        if self._autostart:
            self.start()  # dashboard.py files written before start() only call snapshot()
        with self._lock:
            now = self._clock()
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


def active_bridges() -> list[GigaR1Bridge]:
    """Bridges currently reading a GIGA in this program."""

    with _ACTIVE_LOCK:
        return list(_ACTIVE_BRIDGES)
