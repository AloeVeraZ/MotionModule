"""GPIO backends for Linux GPIO character devices and desktop simulation."""

from __future__ import annotations

import os
import platform
from pathlib import Path

from .errors import HardwareUnavailable


def is_raspberry_pi() -> bool:
    try:
        model = Path("/proc/device-tree/model").read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return False
    return "raspberry pi" in model.casefold()


class MockGPIO:
    """In-memory backend used by tests and non-Pi development computers."""

    is_hardware = False

    def __init__(self) -> None:
        self.claimed: set[int] = set()
        self.values: dict[int, float] = {}
        self.events: list[tuple[str, int, float]] = []
        self.closed = False

    def claim_output(self, gpio: int) -> None:
        if gpio in self.claimed:
            raise HardwareUnavailable(f"GPIO{gpio} has already been claimed")
        self.claimed.add(gpio)
        self.values[gpio] = 0.0
        self.events.append(("claim", gpio, 0.0))

    def write(self, gpio: int, value: bool) -> None:
        self._require(gpio)
        self.values[gpio] = 1.0 if value else 0.0
        self.events.append(("write", gpio, self.values[gpio]))

    def pwm(self, gpio: int, frequency: int, duty_percent: float) -> None:
        self._require(gpio)
        duty = max(0.0, min(100.0, float(duty_percent)))
        self.values[gpio] = duty / 100.0
        self.events.append(("pwm", gpio, duty))

    def _require(self, gpio: int) -> None:
        if gpio not in self.claimed or self.closed:
            raise HardwareUnavailable(f"GPIO{gpio} is not available")

    def close(self) -> None:
        if self.closed:
            return
        for gpio in sorted(self.claimed):
            self.values[gpio] = 0.0
            self.events.append(("close", gpio, 0.0))
        self.closed = True


class LgpioBackend:
    """Hardware PWM scheduling through Raspberry Pi OS' lgpio package."""

    is_hardware = True

    def __init__(self, chip: int = 0, lgpio_module=None) -> None:
        try:
            if lgpio_module is None:
                import lgpio as lgpio_module  # type: ignore[no-redef]
            self._lgpio = lgpio_module
            self._handle = self._lgpio.gpiochip_open(chip)
        except (ImportError, OSError) as error:
            raise HardwareUnavailable(
                "lgpio is unavailable; install python3-lgpio and verify /dev/gpiochip0 permissions"
            ) from error
        self.claimed: set[int] = set()
        self.closed = False

    def claim_output(self, gpio: int) -> None:
        try:
            self._lgpio.gpio_claim_output(self._handle, gpio, 0)
        except (OSError, RuntimeError) as error:
            raise HardwareUnavailable(f"Could not claim GPIO{gpio}: {error}") from error
        self.claimed.add(gpio)

    def write(self, gpio: int, value: bool) -> None:
        try:
            self._lgpio.gpio_write(self._handle, gpio, 1 if value else 0)
        except (OSError, RuntimeError) as error:
            raise HardwareUnavailable(f"Could not write GPIO{gpio}: {error}") from error

    def pwm(self, gpio: int, frequency: int, duty_percent: float) -> None:
        duty = max(0.0, min(100.0, float(duty_percent)))
        try:
            self._lgpio.tx_pwm(self._handle, gpio, frequency, duty)
        except (OSError, RuntimeError) as error:
            raise HardwareUnavailable(f"Could not set PWM on GPIO{gpio}: {error}") from error

    def close(self) -> None:
        if self.closed:
            return
        for gpio in sorted(self.claimed):
            try:
                self._lgpio.tx_pwm(self._handle, gpio, 1000, 0)
                self._lgpio.gpio_write(self._handle, gpio, 0)
                self._lgpio.gpio_free(self._handle, gpio)
            except (OSError, RuntimeError):
                pass
        try:
            self._lgpio.gpiochip_close(self._handle)
        except (OSError, RuntimeError):
            pass
        self.closed = True


def create_gpio_backend():
    """Use real GPIO on a Pi and explicit simulation everywhere else."""

    force_mock = os.environ.get("MOTIONMODULE_MOCK", "").casefold() in {"1", "true", "yes", "on"}
    if force_mock or not is_raspberry_pi():
        return MockGPIO()
    if platform.system() != "Linux":
        raise HardwareUnavailable("Raspberry Pi GPIO control requires Linux")
    return LgpioBackend()

