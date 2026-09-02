"""Typed configuration and pin-safety validation."""

from __future__ import annotations

import ast
import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigurationError


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "default.toml"
RESERVED_ID_GPIOS = {0, 1}
I2C_GPIOS = {2, 3}
VALID_BCM_GPIOS = set(range(28))
PROJECT_CONFIG_NAME = "hardware.py"


@dataclass(frozen=True)
class MotorConfig:
    channel: int
    name: str
    forward_gpio: int
    reverse_gpio: int
    inverted: bool = False


@dataclass(frozen=True)
class ServoConfig:
    enabled: bool
    i2c_bus: int
    frequency_hz: int
    addresses: tuple[int, ...]
    minimum_pulse_us: int
    maximum_pulse_us: int


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


def _as_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ConfigurationError(f"{label} must be an integer")
    return value


def _as_bool(value: object, label: str) -> bool:
    if not isinstance(value, bool):
        raise ConfigurationError(f"{label} must be true or false")
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
    return config


def _config_from_mapping(data: object, source: Path) -> ModuleConfig:
    if not isinstance(data, dict):
        raise ConfigurationError(f"Hardware configuration in {source} must be a dictionary")
    try:
        module_data = data["module"]
        motor_data = data["motors"]
        servo_data = data["servos"]
        motors = tuple(
            MotorConfig(
                channel=int(channel),
                name=str(values.get("name", f"motor_{channel}")),
                forward_gpio=_as_int(values["forward_gpio"], f"motors.{channel}.forward_gpio"),
                reverse_gpio=_as_int(values["reverse_gpio"], f"motors.{channel}.reverse_gpio"),
                inverted=_as_bool(values.get("inverted", False), f"motors.{channel}.inverted"),
            )
            for channel, values in sorted(motor_data.items(), key=lambda item: int(item[0]))
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
            ),
        )
    except (AttributeError, KeyError, TypeError, ValueError) as error:
        raise ConfigurationError(f"Missing or invalid configuration value in {source}: {error}") from error
    return _validate(config)


def load_project_config(project: str | os.PathLike[str]) -> ModuleConfig:
    """Load a project's data-only ``hardware.py`` without executing student code."""

    selected = Path(project).expanduser() / PROJECT_CONFIG_NAME
    try:
        source = selected.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(selected))
    except FileNotFoundError as error:
        raise ConfigurationError(f"Project hardware file not found: {selected}") from error
    except (OSError, SyntaxError, UnicodeError) as error:
        raise ConfigurationError(f"Invalid Python in {selected}: {error}") from error

    hardware_node: ast.AST | None = None
    for node in tree.body:
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant) and isinstance(
            node.value.value, str
        ):
            continue
        valid_assignment = (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "HARDWARE"
        ) or (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "HARDWARE"
        )
        if valid_assignment:
            if hardware_node is not None:
                raise ConfigurationError(f"{selected} must assign HARDWARE exactly once")
            hardware_node = node.value
            continue
        raise ConfigurationError(
            f"{selected} may contain only a docstring and one literal HARDWARE assignment"
        )
    if hardware_node is None:
        raise ConfigurationError(f"{selected} must define HARDWARE = {{...}}")
    try:
        data = ast.literal_eval(hardware_node)
    except (ValueError, TypeError, SyntaxError) as error:
        raise ConfigurationError(f"HARDWARE in {selected} must contain literal data only") from error
    return _config_from_mapping(data, selected)


def load_config(path: str | os.PathLike[str] | None = None) -> ModuleConfig:
    """Load project hardware when active, otherwise use the persistent TOML config."""

    if path is None:
        project = os.environ.get("MOTIONMODULE_ACTIVE_PROJECT", "")
        if project and (Path(project).expanduser() / PROJECT_CONFIG_NAME).is_file():
            return load_project_config(project)
    selected = Path(path or os.environ.get("MOTIONMODULE_CONFIG", DEFAULT_CONFIG_PATH)).expanduser()
    try:
        data = tomllib.loads(selected.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ConfigurationError(f"Configuration file not found: {selected}") from error
    except tomllib.TOMLDecodeError as error:
        raise ConfigurationError(f"Invalid TOML in {selected}: {error}") from error
    return _config_from_mapping(data, selected)
