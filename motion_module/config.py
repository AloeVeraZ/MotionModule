"""Typed configuration and pin-safety validation."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass
from pathlib import Path

from .errors import ConfigurationError


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "config" / "default.toml"
RESERVED_ID_GPIOS = {0, 1}
I2C_GPIOS = {2, 3}
VALID_BCM_GPIOS = set(range(28))


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


def load_config(path: str | os.PathLike[str] | None = None) -> ModuleConfig:
    """Load TOML config, using MOTIONMODULE_CONFIG or the repository default."""

    selected = Path(path or os.environ.get("MOTIONMODULE_CONFIG", DEFAULT_CONFIG_PATH)).expanduser()
    try:
        data = tomllib.loads(selected.read_text(encoding="utf-8"))
    except FileNotFoundError as error:
        raise ConfigurationError(f"Configuration file not found: {selected}") from error
    except tomllib.TOMLDecodeError as error:
        raise ConfigurationError(f"Invalid TOML in {selected}: {error}") from error

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
                inverted=bool(values.get("inverted", False)),
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
                enabled=bool(servo_data.get("enabled", True)),
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
    except (KeyError, TypeError, ValueError) as error:
        raise ConfigurationError(f"Missing or invalid configuration value in {selected}: {error}") from error
    return _validate(config)

