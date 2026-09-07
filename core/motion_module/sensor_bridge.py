"""Optional USB sensor bridge support for robot ``dashboard.py`` files."""

from __future__ import annotations

import json
import math
import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterable

from .telemetry import SensorReading, USBController
from .usb import sensor_controllers


GIGA_BOARD_ID = "arduino_giga_r1_wifi"
GIGA_DIGITAL_PINS = frozenset(f"D{number}" for number in range(76))
GIGA_ANALOG_PINS = frozenset(f"A{number}" for number in range(8))


@dataclass(frozen=True, slots=True)
class GigaPin:
    """One Arduino GIGA pin declared by a robot project."""

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
    """Auto-discover one GIGA R1 and read MotionModule bridge telemetry.

    The board is identified from Arduino's USB VID/PID.  Pin modes are sent
    from this project's ``GigaPin`` declarations after every reconnect, so the
    same bridge sketch can be reused without hard-coding a robot's sensors.
    """

    def __init__(
        self,
        pins: Iterable[GigaPin],
        *,
        serial: str = "",
        baudrate: int = 115200,
        stale_after: float = 1.0,
        discovery: Callable[[], list[dict]] = sensor_controllers,
        serial_factory=None,
    ) -> None:
        self.pins = tuple(pins)
        if not self.pins:
            raise ValueError("Configure at least one GIGA sensor pin")
        if len(self.pins) > 20:
            raise ValueError("A Driver Station USB controller supports up to 20 sensor pins")
        if len({pin.pin for pin in self.pins}) != len(self.pins):
            raise ValueError("Each GIGA pin can be configured only once")
        self.serial = serial.strip()
        self.baudrate = int(baudrate)
        self.stale_after = max(0.1, float(stale_after))
        self._discovery = discovery
        self._serial_factory = serial_factory
        self._port = None
        self._device: dict | None = None
        self._values: dict[str, object] = {}
        self._last_packet = 0.0
        self._last_discovery = 0.0
        self._error = "Waiting for the Arduino GIGA R1 WiFi"
        self._lock = threading.Lock()

    def _discover(self) -> dict | None:
        now = time.monotonic()
        if self._device is not None and now - self._last_discovery < 1.0:
            return self._device
        self._last_discovery = now
        self._device = next((
            item for item in self._discovery()
            if item.get("board_id") == GIGA_BOARD_ID
            and (not self.serial or item.get("serial") == self.serial)
        ), None)
        return self._device

    def _open(self, device: dict) -> None:
        port = str(device.get("port", ""))
        if not port:
            self._error = "GIGA detected, but its USB CDC serial port is unavailable"
            return
        try:
            factory = self._serial_factory
            if factory is None:
                from serial import Serial as factory  # type: ignore[no-redef]
            self._port = factory(port, self.baudrate, timeout=0.02, write_timeout=0.1)
            declaration = ",".join(f"{pin.pin}:{pin.bridge_mode}" for pin in self.pins)
            self._port.write(f"MM1 CONFIG {declaration}\n".encode("ascii"))
            self._error = "Waiting for the MotionModule bridge sketch"
        except (ImportError, OSError, ValueError) as error:
            self._port = None
            self._error = f"Could not open {port}: {error}"

    def _read(self) -> None:
        if self._port is None:
            return
        try:
            for _ in range(32):
                waiting = int(getattr(self._port, "in_waiting", 0))
                if waiting <= 0:
                    break
                line = self._port.readline(32768)
                if not line:
                    break
                payload = json.loads(line.decode("utf-8", errors="replace"))
                if payload.get("protocol") != "motionmodule-sensor-v1":
                    continue
                values = payload.get("values")
                if not isinstance(values, dict):
                    continue
                self._values = {str(key).upper(): value for key, value in values.items()}
                self._last_packet = time.monotonic()
                self._error = "MotionModule sensor bridge is streaming"
        except (OSError, ValueError, json.JSONDecodeError) as error:
            self._error = f"GIGA bridge read failed: {error}"
            self.close()

    def snapshot(self) -> USBController:
        with self._lock:
            device = self._discover()
            if device is None:
                self.close()
                self._error = "Waiting for the Arduino GIGA R1 WiFi"
                readings = tuple(pin.reading(None, connected=False, detail=self._error) for pin in self.pins)
                return USBController(
                    "Arduino GIGA R1 WiFi", GIGA_BOARD_ID, connected=False,
                    bridge="offline", pins=readings, detail=self._error,
                )
            if self._port is None:
                self._open(device)
            self._read()
            live = bool(self._last_packet and time.monotonic() - self._last_packet <= self.stale_after)
            readings = tuple(
                pin.reading(self._values.get(pin.pin), connected=live and pin.pin in self._values,
                            detail=self._error)
                for pin in self.pins
            )
            return USBController(
                name="Arduino GIGA R1 WiFi",
                board_id=GIGA_BOARD_ID,
                connected=True,
                serial=str(device.get("serial", "")),
                port=str(device.get("port", "")),
                bridge="streaming" if live else "waiting-for-bridge",
                pins=readings,
                detail=self._error,
            )

    def close(self) -> None:
        port, self._port = self._port, None
        self._last_packet = 0.0
        self._values = {}
        if port is not None:
            try:
                port.close()
            except OSError:
                pass
