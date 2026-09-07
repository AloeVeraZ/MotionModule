"""Safe Raspberry Pi digital inputs for robot projects."""

from __future__ import annotations

from dataclasses import dataclass

from .config import I2C_GPIOS, RESERVED_ID_GPIOS, VALID_BCM_GPIOS, ModuleConfig


# MotionModule deliberately leaves the serial console pair alone.
UART_GPIOS = {14, 15}


def available_input_gpios(config: ModuleConfig) -> tuple[int, ...]:
    used = {
        gpio
        for motor in config.motors
        for gpio in (motor.forward_gpio, motor.reverse_gpio)
    }
    # The servo board's OE pin is an output MotionModule already drives.
    if config.servos.output_enable_gpio is not None:
        used.add(config.servos.output_enable_gpio)
    unavailable = used | RESERVED_ID_GPIOS | I2C_GPIOS | UART_GPIOS
    return tuple(sorted(VALID_BCM_GPIOS - unavailable))


@dataclass(frozen=True, slots=True)
class DigitalInput:
    """One claimed BCM GPIO input."""

    backend: object
    gpio: int
    pull: str = "none"

    @property
    def value(self) -> bool:
        return bool(self.backend.read(self.gpio))

    @property
    def connected(self) -> bool:
        return bool(getattr(self.backend, "is_hardware", False))

