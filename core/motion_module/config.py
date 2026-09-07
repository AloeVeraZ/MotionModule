"""Typed configuration, friendly names, and pin-safety validation.

Everything MotionModule knows about a robot's wiring comes from one
``hardware.py`` file. The packaged default lives next to this module; a robot
project may ship its own copy to rename outputs or change pins.
"""

from __future__ import annotations

import ast
import os
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path
from pprint import pformat

from .errors import ConfigurationError


DEFAULT_HARDWARE_PATH = Path(__file__).with_name("hardware.py")
RESERVED_ID_GPIOS = {0, 1}
I2C_GPIOS = {2, 3}
VALID_BCM_GPIOS = set(range(28))
PROJECT_CONFIG_NAME = "hardware.py"
NAME_PATTERN = re.compile(r"[A-Za-z][A-Za-z0-9_]{0,31}")
SERVO_CHANNELS_PER_BOARD = 16


@dataclass(frozen=True)
class MotorConfig:
    channel: int
    name: str
    forward_gpio: int
    reverse_gpio: int
    inverted: bool = False


@dataclass(frozen=True)
class ServoSlot:
    """One named PCA9685 output: ``claw`` instead of ``board 0, channel 3``."""

    name: str
    board: int
    channel: int


@dataclass(frozen=True)
class ServoConfig:
    enabled: bool
    i2c_bus: int
    frequency_hz: int
    addresses: tuple[int, ...]
    minimum_pulse_us: int
    maximum_pulse_us: int
    channels: tuple[ServoSlot, ...] = ()


@dataclass(frozen=True)
class ModuleConfig:
    pwm_hz: int
    deadtime_ms: int
    watchdog_ms: int
    motors: tuple[MotorConfig, ...]
    servos: ServoConfig

    def motor(self, channel: int) -> MotorConfig:
        try:
            return next(item for item in self.motors if item.channel == channel)
        except StopIteration as error:
            raise ConfigurationError(f"Motor channel {channel} is not configured") from error

    def motor_channel(self, reference: int | str) -> int:
        """Accept either a channel number or a name from ``hardware.py``."""

        if isinstance(reference, str):
            wanted = reference.strip().casefold()
            for item in self.motors:
                if item.name.casefold() == wanted:
                    return item.channel
            raise ConfigurationError(
                f"No motor is named {reference!r} in hardware.py. "
                f"Configured names: {', '.join(item.name for item in self.motors)}"
            )
        if isinstance(reference, bool) or not isinstance(reference, int):
            raise ConfigurationError("Use a motor name or a channel number from 1 through 8")
        return self.motor(reference).channel

    def servo_slot(self, reference: int | str, board: int | None = None) -> ServoSlot:
        """Accept either a servo name or a board/channel pair."""

        if isinstance(reference, str):
            wanted = reference.strip().casefold()
            for slot in self.servos.channels:
                if slot.name.casefold() == wanted:
                    return slot
            raise ConfigurationError(
                f"No servo is named {reference!r} in hardware.py. "
                f"Configured names: {', '.join(slot.name for slot in self.servos.channels)}"
            )
        if isinstance(reference, bool) or not isinstance(reference, int):
            raise ConfigurationError("Use a servo name or a channel number from 0 through 15")
        index = 0 if board is None else board
        if isinstance(index, bool) or not isinstance(index, int):
            raise ConfigurationError("Servo board must be an integer starting at 0")
        if not 0 <= index < len(self.servos.addresses):
            raise ConfigurationError(f"Servo board {index} is not configured")
        if not 0 <= reference < SERVO_CHANNELS_PER_BOARD:
            raise ConfigurationError("Servo channel must be from 0 through 15")
        for slot in self.servos.channels:
            if slot.board == index and slot.channel == reference:
                return slot
        return ServoSlot(name=f"servo_{index * SERVO_CHANNELS_PER_BOARD + reference}",
                         board=index, channel=reference)

    @property
    def motor_names(self) -> tuple[str, ...]:
        return tuple(item.name for item in self.motors)

    @property
    def servo_names(self) -> tuple[str, ...]:
        return tuple(slot.name for slot in self.servos.channels)


def _as_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigurationError(f"{label} must be an integer")
    return value


def _as_bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigurationError(f"{label} must be true or false")
    return value


def _channel_key(value: object, label: str) -> int:
    """Python uses integer keys; legacy TOML represents those keys as strings."""

    if isinstance(value, str) and value.isascii() and value.isdecimal():
        return int(value)
    return _as_int(value, label)


def _as_name(value: object, label: str) -> str:
    if not isinstance(value, str) or not NAME_PATTERN.fullmatch(value):
        raise ConfigurationError(
            f"{label} must start with a letter and use only letters, numbers, "
            "and underscores (for example front_left)"
        )
    return value


def _validate(config: ModuleConfig) -> ModuleConfig:
    if not 1 <= config.pwm_hz <= 2000:
        raise ConfigurationError("module.pwm_hz must be between 1 and 2000 for this driver")
    if not 0 <= config.deadtime_ms <= 1000:
        raise ConfigurationError("module.deadtime_ms must be between 0 and 1000")
    if not 50 <= config.watchdog_ms <= 10000:
        raise ConfigurationError("module.watchdog_ms must be between 50 and 10000")
    if not 1 <= len(config.motors) <= 8:
        raise ConfigurationError("Configure between one and eight motors")

    channels = [motor.channel for motor in config.motors]
    if len(channels) != len(set(channels)) or any(not 1 <= channel <= 8 for channel in channels):
        raise ConfigurationError("Motor channels must be unique numbers from 1 through 8")

    used: dict[int, str] = {}
    for motor in config.motors:
        if motor.forward_gpio == motor.reverse_gpio:
            raise ConfigurationError(f"Motor {motor.channel} uses the same GPIO for both directions")
        for role, gpio in (("forward", motor.forward_gpio), ("reverse", motor.reverse_gpio)):
            if gpio not in VALID_BCM_GPIOS:
                raise ConfigurationError(f"Motor {motor.channel} {role} GPIO{gpio} is not a Pi header GPIO")
            if gpio in RESERVED_ID_GPIOS:
                raise ConfigurationError(f"GPIO{gpio} is reserved for the Raspberry Pi ID EEPROM bus")
            if gpio in I2C_GPIOS:
                raise ConfigurationError(f"GPIO{gpio} is reserved for the PCA9685 I2C bus")
            if gpio in used:
                raise ConfigurationError(
                    f"GPIO{gpio} is shared by motor {motor.channel} and {used[gpio]}"
                )
            used[gpio] = f"motor {motor.channel}"

    servo = config.servos
    if servo.i2c_bus < 0:
        raise ConfigurationError("servos.i2c_bus must be zero or greater")
    if not 40 <= servo.frequency_hz <= 100:
        raise ConfigurationError("servos.frequency_hz must be between 40 and 100 Hz")
    if not 400 <= servo.minimum_pulse_us < servo.maximum_pulse_us <= 3000:
        raise ConfigurationError("Servo pulse range must stay within 400-3000 microseconds")
    if not servo.addresses:
        raise ConfigurationError("At least one PCA9685 address is required")
    if len(servo.addresses) != len(set(servo.addresses)):
        raise ConfigurationError("PCA9685 addresses must be unique")
    if any(not 0x40 <= address <= 0x7F for address in servo.addresses):
        raise ConfigurationError("PCA9685 addresses must be in the 0x40-0x7f range")

    taken: dict[tuple[int, int], str] = {}
    names: dict[str, str] = {motor.name.casefold(): f"motor {motor.channel}" for motor in config.motors}
    if len(names) != len(config.motors):
        raise ConfigurationError("Every motor in hardware.py needs its own unique name")
    for slot in servo.channels:
        if not 0 <= slot.board < len(servo.addresses):
            raise ConfigurationError(
                f"Servo {slot.name} uses board {slot.board}, which is not in servos.addresses"
            )
        if not 0 <= slot.channel < SERVO_CHANNELS_PER_BOARD:
            raise ConfigurationError(
                f"Servo {slot.name} must use a channel from 0 through {SERVO_CHANNELS_PER_BOARD - 1}"
            )
        position = (slot.board, slot.channel)
        if position in taken:
            raise ConfigurationError(
                f"Board {slot.board} channel {slot.channel} is used by both "
                f"{taken[position]} and {slot.name}"
            )
        taken[position] = slot.name
        key = slot.name.casefold()
        if key in names:
            raise ConfigurationError(
                f"The name {slot.name!r} is used twice in hardware.py "
                f"(already used by {names[key]})"
            )
        names[key] = f"servo {slot.name}"
    return config


def _servo_slots(data: object, addresses: tuple[int, ...]) -> tuple[ServoSlot, ...]:
    """Read named servo outputs, or name every channel on every board."""

    if data is None:
        return tuple(
            ServoSlot(
                name=f"servo_{board * SERVO_CHANNELS_PER_BOARD + channel}",
                board=board,
                channel=channel,
            )
            for board in range(len(addresses))
            for channel in range(SERVO_CHANNELS_PER_BOARD)
        )
    if not isinstance(data, dict):
        raise ConfigurationError("servos.channels must be a dictionary of channel numbers")
    slots = []
    for key, values in sorted(data.items(), key=lambda item: _channel_key(item[0], "servo channel key")):
        if not isinstance(values, dict):
            raise ConfigurationError(f"servos.channels.{key} must be a dictionary")
        board = _as_int(values.get("board", 0), f"servos.channels.{key}.board")
        channel = _as_int(
            values.get("channel", _channel_key(key, "servo channel key")),
            f"servos.channels.{key}.channel",
        )
        position = board * SERVO_CHANNELS_PER_BOARD + channel
        slots.append(
            ServoSlot(
                name=_as_name(
                    values.get("name", f"servo_{position}"), f"servos.channels.{key}.name"
                ),
                board=board,
                channel=channel,
            )
        )
    return tuple(slots)


def _config_from_mapping(data: object, source: Path) -> ModuleConfig:
    if not isinstance(data, dict):
        raise ConfigurationError(f"Hardware configuration in {source} must be a dictionary")
    try:
        module_data = data["module"]
        motor_data = data["motors"]
        servo_data = data["servos"]
        motors = tuple(
            MotorConfig(
                channel=_channel_key(channel, "motor channel key"),
                name=_as_name(values.get("name", f"motor_{channel}"), f"motors.{channel}.name"),
                forward_gpio=_as_int(values["forward_gpio"], f"motors.{channel}.forward_gpio"),
                reverse_gpio=_as_int(values["reverse_gpio"], f"motors.{channel}.reverse_gpio"),
                inverted=_as_bool(values.get("inverted", False), f"motors.{channel}.inverted"),
            )
            for channel, values in sorted(
                motor_data.items(), key=lambda item: _channel_key(item[0], "motor channel key")
            )
        )
        addresses = tuple(_as_int(item, "servos.addresses") for item in servo_data["addresses"])
        config = ModuleConfig(
            pwm_hz=_as_int(module_data["pwm_hz"], "module.pwm_hz"),
            deadtime_ms=_as_int(module_data["deadtime_ms"], "module.deadtime_ms"),
            watchdog_ms=_as_int(module_data["watchdog_ms"], "module.watchdog_ms"),
            motors=motors,
            servos=ServoConfig(
                enabled=_as_bool(servo_data.get("enabled", True), "servos.enabled"),
                i2c_bus=_as_int(servo_data["i2c_bus"], "servos.i2c_bus"),
                frequency_hz=_as_int(servo_data["frequency_hz"], "servos.frequency_hz"),
                addresses=addresses,
                minimum_pulse_us=_as_int(
                    servo_data["minimum_pulse_us"], "servos.minimum_pulse_us"
                ),
                maximum_pulse_us=_as_int(
                    servo_data["maximum_pulse_us"], "servos.maximum_pulse_us"
                ),
                channels=_servo_slots(servo_data.get("channels"), addresses),
            ),
        )
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise ConfigurationError(f"Missing or invalid configuration value in {source}: {error}") from error
    return _validate(config)


def _literal_hardware(selected: Path) -> object:
    """Read ``HARDWARE`` out of a hardware.py file without executing it."""

    try:
        source = selected.read_text(encoding="utf-8-sig")
        tree = ast.parse(source, filename=str(selected))
    except FileNotFoundError as error:
        raise ConfigurationError(f"Hardware file not found: {selected}") from error
    except (OSError, SyntaxError, UnicodeError) as error:
        raise ConfigurationError(f"Invalid Python in {selected}: {error}") from error

    hardware_node: ast.AST | None = None
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(
            node.value.value, str
        ):
            continue
        if isinstance(node, ast.Assign) and len(node.targets) == 1:
            target = node.targets[0]
        elif isinstance(node, ast.AnnAssign):
            target = node.target
        else:
            raise ConfigurationError(
                f"{selected} may contain only comments, a docstring, and plain "
                "value assignments such as HARDWARE = {...}"
            )
        if not isinstance(target, ast.Name):
            raise ConfigurationError(f"{selected} may only assign to simple names")
        try:
            ast.literal_eval(node.value)
        except (ValueError, TypeError, SyntaxError) as error:
            raise ConfigurationError(
                f"{target.id} in {selected} must contain plain values only: no imports, "
                "calculations, or function calls"
            ) from error
        for mapping in ast.walk(node.value):
            if not isinstance(mapping, ast.Dict):
                continue
            seen = set()
            for key_node in mapping.keys:
                key = ast.literal_eval(key_node)
                if key in seen:
                    raise ConfigurationError(
                        f"Duplicate dictionary key {key!r} in {selected} at line {key_node.lineno}; "
                        "give each motor or servo its own channel entry"
                    )
                seen.add(key)
        if target.id == "HARDWARE":
            if hardware_node is not None:
                raise ConfigurationError(f"{selected} must assign HARDWARE exactly once")
            hardware_node = node.value
    if hardware_node is None:
        raise ConfigurationError(f"{selected} must define HARDWARE = {{...}}")
    return ast.literal_eval(hardware_node)


def load_hardware_file(path: str | os.PathLike[str]) -> ModuleConfig:
    """Load one ``hardware.py`` definition file."""

    selected = Path(path).expanduser()
    return _config_from_mapping(_literal_hardware(selected), selected)


def load_project_config(project: str | os.PathLike[str]) -> ModuleConfig:
    """Load a robot folder's data-only ``hardware.py`` without running its code."""

    selected = Path(project).expanduser() / PROJECT_CONFIG_NAME
    if not selected.is_file():
        raise ConfigurationError(f"Project hardware file not found: {selected}")
    return load_hardware_file(selected)


def default_config() -> ModuleConfig:
    """The pin map that ships with MotionModule."""

    return load_hardware_file(DEFAULT_HARDWARE_PATH)


def resolve_config_path(
    path: str | os.PathLike[str] | None = None,
    *,
    project: str | os.PathLike[str] | None = None,
) -> Path:
    """Select the same hardware file for robot execution, diagnostics, and downloads.

    An explicit file wins. Otherwise use the selected robot's hardware.py,
    the installed configuration, then the default shipped in the package.
    Passing ``project`` selects that folder instead of the active-project
    environment variable, including when the folder has no hardware.py.
    """

    if path is not None:
        return Path(path).expanduser()
    selected_project = project if project is not None else os.environ.get("MOTIONMODULE_ACTIVE_PROJECT", "")
    if selected_project:
        candidate = Path(selected_project).expanduser() / PROJECT_CONFIG_NAME
        if candidate.is_file():
            return candidate
    configured = os.environ.get("MOTIONMODULE_CONFIG", "")
    if configured:
        # A missing explicitly selected file is an error when loaded: silently
        # switching a customized robot back to other GPIOs is unsafe.
        return Path(configured).expanduser()
    config_dir = Path(os.environ.get("MOTIONMODULE_CONFIG_DIR", "~/.config/motionmodule")).expanduser()
    for name in (PROJECT_CONFIG_NAME, "config.toml"):
        candidate = config_dir / name
        if candidate.is_file():
            return candidate
    return DEFAULT_HARDWARE_PATH


def load_config(
    path: str | os.PathLike[str] | None = None,
    *,
    project: str | os.PathLike[str] | None = None,
) -> ModuleConfig:
    """Read the selected project's hardware, installed configuration, or default."""

    selected = resolve_config_path(path, project=project)
    if selected.suffix.casefold() == ".py":
        return load_hardware_file(selected)
    try:
        data = tomllib.loads(selected.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ConfigurationError(f"Configuration file not found: {selected}") from error
    except tomllib.TOMLDecodeError as error:
        raise ConfigurationError(f"Invalid TOML in {selected}: {error}") from error
    except (OSError, UnicodeError) as error:
        raise ConfigurationError(f"Cannot read configuration file {selected}: {error}") from error
    return _config_from_mapping(data, selected)


def hardware_source(config: ModuleConfig) -> str:
    """Export the active configuration as one editable, data-only Python file."""

    data = {
        "module": {
            "pwm_hz": config.pwm_hz,
            "deadtime_ms": config.deadtime_ms,
            "watchdog_ms": config.watchdog_ms,
        },
        "motors": {
            motor.channel: {
                "name": motor.name,
                "forward_gpio": motor.forward_gpio,
                "reverse_gpio": motor.reverse_gpio,
                "inverted": motor.inverted,
            }
            for motor in config.motors
        },
        "servos": {
            "enabled": config.servos.enabled,
            "i2c_bus": config.servos.i2c_bus,
            "frequency_hz": config.servos.frequency_hz,
            "addresses": list(config.servos.addresses),
            "minimum_pulse_us": config.servos.minimum_pulse_us,
            "maximum_pulse_us": config.servos.maximum_pulse_us,
            "channels": {
                index: {"name": slot.name, "board": slot.board, "channel": slot.channel}
                for index, slot in enumerate(config.servos.channels)
            },
        },
    }
    return (
        '"""MotionModule hardware definitions.\n\n'
        'Keep this file next to robot.py to customize that robot.\n'
        'Use module.motor("name").set(0.25) or module.servo("name").set_angle(90).\n'
        'forward_gpio and reverse_gpio are BCM GPIO numbers, not physical header pins.\n'
        'Motor inversion changes direction without changing the wiring.\n'
        'Servo board is the index in addresses; channel is the board output (0-15).\n'
        'Edit plain values only; this file is read without executing Python code.\n'
        'See Debug > Wiring in the dashboard for physical connections and driver labels.\n'
        '"""\n\nHARDWARE = '
        + pformat(data, sort_dicts=False, width=100)
        + "\n"
    )
