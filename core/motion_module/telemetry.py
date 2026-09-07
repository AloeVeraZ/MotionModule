"""Small, optional telemetry contract for the browser Driver Station.

A robot project can place ``dashboard.py`` beside ``robot.py`` and return a
``TelemetryDashboard`` (or any object with a compatible ``snapshot()``
method).  The normalizers in this module keep malformed student telemetry
from breaking the dashboard and put firm limits on browser-facing data.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, is_dataclass
from typing import Any, Mapping
from urllib.parse import urlsplit


MAX_CAMERAS = 2
MAX_SENSORS = 20
SENSOR_KINDS = {"analog", "digital", "text"}
STATUSES = {"ok", "warning", "fault", "offline", "unknown"}


@dataclass(frozen=True, slots=True)
class CameraFeed:
    """One browser-readable MJPEG, snapshot, or video camera URL."""

    name: str
    url: str = ""
    connected: bool = True
    detail: str = ""


@dataclass(frozen=True, slots=True)
class IMUReading:
    """Orientation values in degrees and yaw rate in degrees per second."""

    name: str = "IMU"
    connected: bool = True
    calibrated: bool = True
    yaw: float | None = None
    pitch: float | None = None
    roll: float | None = None
    rate: float | None = None
    detail: str = ""


@dataclass(frozen=True, slots=True)
class SensorReading:
    """One analog, digital, or text sensor value shown in the sensor tray."""

    name: str
    value: float | bool | str | None
    kind: str = "analog"
    unit: str = ""
    channel: str = ""
    connected: bool = True
    status: str = "ok"
    minimum: float | None = None
    maximum: float | None = None
    detail: str = ""


class TelemetryDashboard:
    """Override only the telemetry groups a robot actually has.

    Values are read on demand, so subclasses can query live sensor objects in
    these methods.  Returning dataclasses is convenient but plain dictionaries
    are accepted too.
    """

    def cameras(self):
        return ()

    def imu(self):
        return None

    def sensors(self):
        return ()

    def snapshot(self) -> dict[str, Any]:
        return {
            "cameras": self.cameras(),
            "imu": self.imu(),
            "sensors": self.sensors(),
        }


def empty_snapshot() -> dict[str, Any]:
    return {"cameras": [], "imu": None, "sensors": []}


def _mapping(value: Any) -> Mapping[str, Any] | None:
    if isinstance(value, Mapping):
        return value
    if is_dataclass(value) and not isinstance(value, type):
        return asdict(value)
    return None


def _text(value: Any, limit: int) -> str:
    return str(value if value is not None else "").strip()[:limit]


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _status(value: Any, connected: bool) -> str:
    if not connected:
        return "offline"
    status = _text(value, 16).casefold()
    return status if status in STATUSES else "unknown"


def _camera(value: Any, index: int) -> dict[str, Any] | None:
    item = _mapping(value)
    if item is None:
        return None
    name = _text(item.get("name"), 60) or f"Camera {index + 1}"
    url = _text(item.get("url"), 500)
    connected = bool(item.get("connected", True))
    if url:
        parsed = urlsplit(url)
        if not (url.startswith("/") or parsed.scheme in {"http", "https"}):
            url = ""
            connected = False
    else:
        connected = False
    return {
        "id": f"camera-{index + 1}",
        "name": name,
        "url": url,
        "connected": connected,
        "detail": _text(item.get("detail"), 160),
    }


def _imu(value: Any) -> dict[str, Any] | None:
    item = _mapping(value)
    if item is None:
        return None
    return {
        "name": _text(item.get("name"), 60) or "IMU",
        "connected": bool(item.get("connected", True)),
        "calibrated": bool(item.get("calibrated", False)),
        "yaw": _number(item.get("yaw")),
        "pitch": _number(item.get("pitch")),
        "roll": _number(item.get("roll")),
        "rate": _number(item.get("rate")),
        "detail": _text(item.get("detail"), 160),
    }


def _digital(value: Any) -> bool | None:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)) and math.isfinite(float(value)):
        return bool(value)
    if isinstance(value, str):
        normalized = value.strip().casefold()
        if normalized in {"true", "on", "high", "1", "yes"}:
            return True
        if normalized in {"false", "off", "low", "0", "no"}:
            return False
    return None


def _sensor(value: Any) -> dict[str, Any] | None:
    item = _mapping(value)
    if item is None:
        return None
    name = _text(item.get("name"), 60)
    if not name:
        return None
    kind = _text(item.get("kind", "analog"), 16).casefold()
    if kind not in SENSOR_KINDS:
        kind = "text"
    connected = bool(item.get("connected", True))
    raw = item.get("value")
    if kind == "analog":
        reading: float | bool | str | None = _number(raw)
    elif kind == "digital":
        reading = _digital(raw)
    else:
        reading = None if raw is None else _text(raw, 80)
    minimum = _number(item.get("minimum")) if kind == "analog" else None
    maximum = _number(item.get("maximum")) if kind == "analog" else None
    if minimum is not None and maximum is not None and minimum >= maximum:
        minimum = maximum = None
    return {
        "name": name,
        "value": reading,
        "kind": kind,
        "unit": _text(item.get("unit"), 16),
        "channel": _text(item.get("channel"), 32),
        "connected": connected,
        "status": _status(item.get("status", "ok"), connected),
        "minimum": minimum,
        "maximum": maximum,
        "detail": _text(item.get("detail"), 160),
    }


def normalize_snapshot(value: Any) -> dict[str, Any]:
    """Return a bounded, JSON-safe Driver Station snapshot."""

    item = _mapping(value)
    if item is None:
        return empty_snapshot()
    raw_cameras = item.get("cameras", ())
    raw_sensors = item.get("sensors", ())
    cameras = []
    for candidate in raw_cameras if isinstance(raw_cameras, (list, tuple)) else ():
        normalized = _camera(candidate, len(cameras))
        if normalized is not None:
            cameras.append(normalized)
        if len(cameras) >= MAX_CAMERAS:
            break
    sensors = []
    for candidate in raw_sensors if isinstance(raw_sensors, (list, tuple)) else ():
        normalized = _sensor(candidate)
        if normalized is not None:
            sensors.append(normalized)
        if len(sensors) >= MAX_SENSORS:
            break
    return {"cameras": cameras, "imu": _imu(item.get("imu")), "sensors": sensors}
