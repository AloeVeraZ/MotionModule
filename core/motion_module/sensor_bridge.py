"""Experimental Arduino GIGA R1 WiFi USB GPIO expansion.

The GIGA reads declared analog and digital inputs and sends their values
over USB. Robot code supplies each input's name, scale and units. A robot says
what is connected, normally in ``sensors.py``::

    pins = []  # Declare only additional inputs actually wired to the board.
    giga = module.giga(pins=pins)
    # giga.value(name) reads a declared input, or None when not streaming.

The reference Mecanum robot uses a Pi-connected MPU6500 and does not start
this extension. The bridge discovers a supported board, not its attached
sensors. Its bundled firmware targets GIGA R1 WiFi, not Uno or Mega.

MotionModule finds the board by its USB ID, sends those declarations after
every connection, and keeps the newest readings from a background thread, so
robot code reads them instantly and never touches the serial port.
The MPU6500 reader is independent of this optional GPIO bridge.
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

from .telemetry import SensorReading, USBController
from .usb import sensor_controllers


GIGA_BOARD_ID = "arduino_giga_r1_wifi"
GIGA_DIGITAL_PINS = frozenset(f"D{number}" for number in range(76))
GIGA_ANALOG_PINS = frozenset(f"A{number}" for number in range(8))
# The version of firmware/giga_sensor_bridge shipped beside this code. The
# firmware tests keep the two equal.
GIGA_FIRMWARE_VERSION = "3.0.0"
PROTOCOL_V1 = "motionmodule-sensor-v1"
PROTOCOL = "motionmodule-sensor-v3"
MAX_GIGA_READINGS = 20
DEFAULT_INTERVAL_MS = 20
FLASH_COMMAND = "motionmodule giga flash"
SILENT_SECONDS = 3.0

__all__ = [
    "FLASH_COMMAND", "GIGA_BOARD_ID", "GIGA_FIRMWARE_VERSION",
    "PROTOCOL", "PROTOCOL_V1", "GigaPin", "GigaR1Bridge", "active_bridges",
]

# Two bridges reading one board would split its stream between them.
_ACTIVE_BRIDGES: "weakref.WeakSet[GigaR1Bridge]" = weakref.WeakSet()
_ACTIVE_LOCK = threading.Lock()


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


class GigaR1Bridge:
    """Find one GIGA R1, tell it what to read, and keep its newest readings.

    The board is identified from Arduino's USB VID/PID. The input pin list is sent after every
    connection, so one firmware serves any robot. A background thread does all
    of the USB work; robot code only reads values it already has.
    ``simulated=True`` never opens the board.
    """

    def __init__(
        self,
        pins: Iterable[GigaPin] = (),
        *,
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
        if not all(isinstance(pin, GigaPin) for pin in self.pins):
            raise ValueError("GIGA pins must be GigaPin(...) declarations")
        if not self.pins:
            raise ValueError("Configure at least one GIGA sensor pin")
        if len(self.pins) > MAX_GIGA_READINGS:
            raise ValueError("A Driver Station USB controller supports up to 20 sensor pins")
        if len({pin.pin for pin in self.pins}) != len(self.pins):
            raise ValueError("Each GIGA pin can be configured only once")
        names = [pin.name for pin in self.pins]
        if len({name.casefold() for name in names}) != len(names):
            raise ValueError("Every GIGA pin needs its own name")
        self.serial = serial.strip()
        self.baudrate = int(baudrate)
        self.stale_after = max(0.1, float(stale_after))
        self.interval_ms = max(5, min(1000, int(interval_ms)))
        self.simulated = bool(simulated)
        self._autostart = autostart
        self._discovery = discovery
        self._serial_factory = serial_factory
        self._clock = clock

        pin_text = ",".join(f"{pin.pin}:{pin.bridge_mode}" for pin in self.pins) or "-"
        # Firmware retains its generic I2C protocol; this bridge declares inputs only.
        body = f"{self.interval_ms} {pin_text} -"
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

    def matches(self, pins: Iterable[GigaPin] = (), serial: str = "") -> bool:
        return (tuple(pins), serial.strip()) == (self.pins, self.serial)

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
            self._legacy_sketch = False
            self._unusable_protocol = ""
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
            configured = self._configured
            legacy = self._legacy_sketch
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
            self._configured = True
            self._board_error = ""
            self._values = {str(key).upper(): value for key, value in values.items()}
            self._last_packet = now
            self._error = "Streaming"

    def _handle_event(self, event, payload: dict, now: float) -> None:
        if event == "hello":
            # A hello after readings means the board started over.
            if self._configured:
                self._configured = False
                self._config_sent_at = 0.0
            return
        if event == "error":
            message = payload.get("message")
            self._board_error = str(message)[:120] if message else "unknown error"
            return

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
                    "Streaming pins from the original bridge sketch; "
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
