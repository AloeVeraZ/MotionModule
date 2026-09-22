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
MAX_USB_CONTROLLERS = 4

# The Driver Station's keyboard layout. These seven actions are fixed because
# drive() takes exactly three axes plus a stop; a project chooses which key
# sits on each of them, not what the actions are.
DRIVER_ACTIONS = ("forward", "back", "left", "right", "turn_left", "turn_right", "stop")
DEFAULT_DRIVER_BINDINGS = {
    "forward": "w",
    "back": "s",
    "left": "a",
    "right": "d",
    "turn_left": "q",
    "turn_right": "e",
    "stop": " ",
}

# The Driver Station's sticks: a game controller's, and the on-screen pair a
# phone or tablet drives with. Both use these four axis names, and each of
# drive()'s three motions takes one of them. Pushing a stick up or right
# drives forward, strafes right or turns right.
STICK_AXES = ("left_x", "left_y", "right_x", "right_y")
STICK_MOTIONS = ("forward", "strafe", "rotate")
DEFAULT_GAMEPAD_STICKS = {
    "forward": "left_y",
    "strafe": "left_x",
    "rotate": "right_x",
    "deadzone": 0.12,
    "curve": 1.0,
}
DEFAULT_TOUCH_STICKS = {
    "forward": "left_y",
    "strafe": "left_x",
    "rotate": "right_x",
    "deadzone": 0.1,
    "curve": 1.0,
}
# A touchscreen always shows robot control, the sticks and the cameras. These
# are the panels a project can add to that.
TOUCH_PANELS = ("status", "mechanisms", "imu", "pi_inputs", "usb_controllers")
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


@dataclass(frozen=True, slots=True)
class USBController:
    """One USB-connected sensor controller and its configured pin readings."""

    name: str
    board_id: str
    connected: bool = True
    serial: str = ""
    port: str = ""
    bridge: str = "unknown"
    pins: tuple[SensorReading, ...] = ()
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
        """Legacy alias for Raspberry Pi inputs."""

        return ()

    def pi_inputs(self):
        # A dashboard that keeps its robot's sensor object in self.sensors,
        # as the Mecanum sample does, hides the legacy sensors() method. It
        # has no Raspberry Pi inputs of its own then, and must not fail.
        legacy = self.sensors
        return legacy() if callable(legacy) else ()

    def usb_controllers(self):
        return ()

    def driver_bindings(self):
        """Keys the Driver Station listens for, as {action: key}.

        Return only the actions you want to move; anything you leave out keeps
        its default (WASD to drive and strafe, Q/E to turn, space to stop).
        This is the competition console's own layout and has nothing to do with
        the fixed bindings in Debug's Mecanum Test.
        """

        return {}

    def gamepad_sticks(self):
        """Which game-controller stick drives, strafes and turns.

        Give a motion one of "left_x", "left_y", "right_x" or "right_y".
        Pushing that stick up or right drives forward, strafes right or turns
        right; a "-" in front flips it, and None switches the motion off.
        "deadzone" (0 to 0.5) ignores wobble near the middle, and a "curve"
        above 1 (up to 3) gives finer control there. Anything left out keeps
        its default: left stick drives and strafes, right stick turns.
        """

        return {}

    def touch_sticks(self):
        """The on-screen sticks a phone or tablet drives with.

        The same form as gamepad_sticks(). A stick with two motions moves all
        the way round and a stick with one moves only that way, so by default
        the right stick only goes left and right. "rotate": "buttons" gives
        Turn left and Turn right buttons instead of a turning stick.
        """

        return {}

    def touch_panels(self):
        """Extra panels a touchscreen shows.

        A phone or tablet shows robot control, the sticks and the cameras.
        List any of "status", "mechanisms", "imu", "pi_inputs" and
        "usb_controllers" to show those as well.
        """

        return ()

    def snapshot(self) -> dict[str, Any]:
        pi_inputs = self.pi_inputs()
        return {
            "cameras": self.cameras(),
            "imu": self.imu(),
            "pi_inputs": pi_inputs,
            "usb_controllers": self.usb_controllers(),
            "driver_bindings": self.driver_bindings(),
            "gamepad_sticks": self.gamepad_sticks(),
            "touch_sticks": self.touch_sticks(),
            "touch_panels": self.touch_panels(),
            # Kept for projects and clients written for MotionModule 0.10.
            "sensors": pi_inputs,
        }


def empty_snapshot() -> dict[str, Any]:
    return {
        "cameras": [],
        "imu": None,
        "pi_inputs": [],
        "usb_controllers": [],
        "driver_bindings": dict(DEFAULT_DRIVER_BINDINGS),
        "gamepad_sticks": dict(DEFAULT_GAMEPAD_STICKS),
        "touch_sticks": dict(DEFAULT_TOUCH_STICKS),
        "touch_panels": [],
        "sensors": [],
    }


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


def _pin_names(value: Any, maximum: int = 128) -> list[str]:
    if not isinstance(value, (list, tuple)):
        return []
    names = []
    for candidate in value:
        name = _text(candidate, 12)
        if name and name not in names:
            names.append(name)
        if len(names) >= maximum:
            break
    return names


def _usb_controller(value: Any, index: int) -> dict[str, Any] | None:
    item = _mapping(value)
    if item is None:
        return None
    board_id = _text(item.get("board_id"), 64) or "usb_sensor_controller"
    name = _text(item.get("name"), 60) or f"USB controller {index + 1}"
    connected = bool(item.get("connected", False))
    pins = []
    raw_pins = item.get("pins", ())
    for candidate in raw_pins if isinstance(raw_pins, (list, tuple)) else ():
        normalized = _sensor(candidate)
        if normalized is not None:
            pins.append(normalized)
        if len(pins) >= MAX_SENSORS:
            break
    return {
        "id": _text(item.get("id"), 120) or f"{board_id}:{index + 1}",
        "name": name,
        "board_id": board_id,
        "connected": connected,
        "vendor_id": _text(item.get("vendor_id"), 8),
        "product_id": _text(item.get("product_id"), 8),
        "serial": _text(item.get("serial"), 100),
        "port": _text(item.get("port"), 160),
        "permission": _text(item.get("permission"), 16) or "unknown",
        "transport": _text(item.get("transport"), 40),
        "bridge": _text(item.get("bridge"), 40) or "unknown",
        "digital_pins": _pin_names(item.get("digital_pins")),
        "analog_pins": _pin_names(item.get("analog_pins"), 32),
        "dac_pins": _pin_names(item.get("dac_pins"), 16),
        "adc_bits": int(item["adc_bits"]) if isinstance(item.get("adc_bits"), int) else None,
        "pins": pins,
        "detail": _text(item.get("detail"), 240),
    }


def _driver_bindings(value: Any) -> dict[str, str]:
    """Fill in the defaults around whatever the project chose to change.

    Two passes, because one key must never mean two things: what the project
    asked for is placed first, then each remaining action takes its default if
    that key is still free. An action whose default was claimed by someone
    else is left out entirely rather than silently sharing a key - the Driver
    Station shows it as unassigned, which is at least true.
    """

    chosen = _mapping(value) or {}
    bindings: dict[str, str] = {}
    taken: set[str] = set()
    for action in DRIVER_ACTIONS:
        if action not in chosen:
            continue
        key = _text(chosen.get(action), 20)
        # A single character is compared case-insensitively; a named key such
        # as "Space" or "ArrowUp" is passed through as the browser reports it.
        # Anything else is not a key the browser will ever send.
        if len(key) == 1:
            key = key.casefold()
        elif not key.isalpha():
            continue
        if key in taken:
            continue
        taken.add(key)
        bindings[action] = key
    for action in DRIVER_ACTIONS:
        if action in bindings:
            continue
        key = DEFAULT_DRIVER_BINDINGS[action]
        if key in taken:
            continue
        taken.add(key)
        bindings[action] = key
    return bindings


def _sticks(value: Any, defaults: Mapping[str, Any], *, turn_buttons: bool = False) -> dict[str, Any]:
    """Fill in the defaults around the stick axes a project chose.

    The same two passes as the keys, because one axis must never move the
    robot two ways: what the project asked for is placed first, then each
    remaining motion takes its default axis if nobody claimed it, and is
    switched off if somebody did. None, False or "off" switches a motion off
    on purpose. Only the on-screen sticks can turn with "buttons".
    """

    chosen = _mapping(value) or {}
    sticks: dict[str, Any] = {}
    taken: set[str] = set()
    for motion in STICK_MOTIONS:
        if motion not in chosen:
            continue
        raw = chosen.get(motion)
        axis = "" if raw is None or raw is False else _text(raw, 16).casefold().replace(" ", "")
        if axis in {"", "none", "off"}:
            sticks[motion] = None
            continue
        if turn_buttons and motion == "rotate" and axis == "buttons":
            sticks[motion] = axis
            continue
        name = axis[1:] if axis.startswith("-") else axis
        if name not in STICK_AXES or name in taken:
            continue
        taken.add(name)
        sticks[motion] = axis
    for motion in STICK_MOTIONS:
        if motion in sticks:
            continue
        axis = defaults[motion]
        if axis in taken:
            sticks[motion] = None
            continue
        taken.add(axis)
        sticks[motion] = axis
    deadzone = _number(chosen.get("deadzone"))
    curve = _number(chosen.get("curve"))
    sticks["deadzone"] = defaults["deadzone"] if deadzone is None else min(max(deadzone, 0.0), 0.5)
    sticks["curve"] = defaults["curve"] if curve is None else min(max(curve, 1.0), 3.0)
    return sticks


def _touch_panels(value: Any) -> list[str]:
    """The panels a project added to the touchscreen layout, each once."""

    if isinstance(value, str):
        value = (value,)
    if not isinstance(value, (list, tuple, set, frozenset)):
        return []
    named = {_text(candidate, 24).casefold() for candidate in value}
    return [panel for panel in TOUCH_PANELS if panel in named]


def normalize_snapshot(value: Any) -> dict[str, Any]:
    """Return a bounded, JSON-safe Driver Station snapshot."""

    item = _mapping(value)
    if item is None:
        return empty_snapshot()
    raw_cameras = item.get("cameras", ())
    raw_sensors = item.get("pi_inputs", item.get("sensors", ()))
    raw_controllers = item.get("usb_controllers", ())
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
    controllers = []
    for candidate in raw_controllers if isinstance(raw_controllers, (list, tuple)) else ():
        normalized = _usb_controller(candidate, len(controllers))
        if normalized is not None:
            controllers.append(normalized)
        if len(controllers) >= MAX_USB_CONTROLLERS:
            break
    return {
        "cameras": cameras,
        "imu": _imu(item.get("imu")),
        "pi_inputs": sensors,
        "usb_controllers": controllers,
        "driver_bindings": _driver_bindings(item.get("driver_bindings")),
        "gamepad_sticks": _sticks(item.get("gamepad_sticks"), DEFAULT_GAMEPAD_STICKS),
        "touch_sticks": _sticks(item.get("touch_sticks"), DEFAULT_TOUCH_STICKS, turn_buttons=True),
        "touch_panels": _touch_panels(item.get("touch_panels")),
        "sensors": sensors,
    }


def merge_usb_controllers(configured: list[dict], discovered: list[dict]) -> list[dict]:
    """Combine project pin telemetry with read-only USB board discovery."""

    normalized_discovered = []
    for item in discovered:
        normalized = _usb_controller(item, len(normalized_discovered))
        if normalized is not None:
            normalized_discovered.append(normalized)

    merged: list[dict] = []
    used: set[int] = set()
    for project in configured:
        match = None
        for index, device in enumerate(normalized_discovered):
            if index in used or device["board_id"] != project["board_id"]:
                continue
            if project.get("serial") and device.get("serial") != project.get("serial"):
                continue
            match = (index, device)
            break
        if match is None:
            merged.append(project)
            continue
        index, device = match
        used.add(index)
        combined = dict(device)
        for key, value in project.items():
            if value not in (None, "", [], ()) or key in {"pins", "connected", "bridge"}:
                combined[key] = value
        combined["connected"] = True
        merged.append(combined)

    merged.extend(
        device for index, device in enumerate(normalized_discovered) if index not in used
    )
    return merged[:MAX_USB_CONTROLLERS]
