"""Safe two-input H-bridge motor channel."""

from __future__ import annotations

from .config import MotorConfig


class HBridgeMotor:
    def __init__(self, gpio, config: MotorConfig, frequency: int) -> None:
        self.gpio = gpio
        self.config = config
        self.frequency = frequency
        self.value = 0.0
        self._electrical_direction = 0
        gpio.claim_output(config.forward_gpio)
        gpio.claim_output(config.reverse_gpio)
        self._off()

    def electrical_value(self, logical_value: float) -> float:
        value = max(-1.0, min(1.0, float(logical_value)))
        return -value if self.config.inverted else value

    def would_reverse(self, logical_value: float) -> bool:
        value = self.electrical_value(logical_value)
        direction = 1 if value > 0 else -1 if value < 0 else 0
        return bool(direction and self._electrical_direction and direction != self._electrical_direction)

    def set(self, logical_value: float) -> None:
        value = self.electrical_value(logical_value)
        duty = abs(value) * 100.0
        if value > 0:
            self.gpio.pwm(self.config.reverse_gpio, self.frequency, 0)
            self.gpio.write(self.config.reverse_gpio, False)
            self.gpio.pwm(self.config.forward_gpio, self.frequency, duty)
            self._electrical_direction = 1
        elif value < 0:
            self.gpio.pwm(self.config.forward_gpio, self.frequency, 0)
            self.gpio.write(self.config.forward_gpio, False)
            self.gpio.pwm(self.config.reverse_gpio, self.frequency, duty)
            self._electrical_direction = -1
        else:
            self._off()
            self._electrical_direction = 0
        self.value = max(-1.0, min(1.0, float(logical_value)))

    def _off(self) -> None:
        for gpio in (self.config.forward_gpio, self.config.reverse_gpio):
            self.gpio.pwm(gpio, self.frequency, 0)
            self.gpio.write(gpio, False)

    def close(self) -> None:
        self.set(0)


class Motor:
    """Student-facing handle that routes changes through the shared safety controller."""

    def __init__(self, controller, channel: int) -> None:
        self._controller = controller
        self.channel = channel

    @property
    def value(self) -> float:
        return self._controller.motor_values[self.channel]

    def set(self, value: float) -> None:
        self._controller.set_motors({self.channel: value})

    def stop(self) -> None:
        self.set(0)

