"""Coordinated motor, servo, deadtime, and watchdog management."""

from __future__ import annotations

import math
import threading
import time

from .config import ModuleConfig, load_config
from .gpio import MockGPIO, create_gpio_backend
from .motor import HBridgeMotor, Motor
from .servo import MockServoController, PCA9685Controller, Servo


class MotionModule:
    """Main API passed into robot projects.

    Motor channels are numbered 1-8. PCA9685 servo boards are numbered from 0,
    and each board provides channels 0-15.
    """

    def __init__(self, config: ModuleConfig | None = None, gpio=None, servo_controller=None) -> None:
        self.config = config or load_config()
        self.gpio = gpio or create_gpio_backend()
        self._lock = threading.RLock()
        self._closed = False
        self._watchdog_tripped = False
        self._watchdog_armed = False
        self._last_feed = time.monotonic()
        self._stop_event = threading.Event()
        self._motors = {
            item.channel: HBridgeMotor(self.gpio, item, self.config.pwm_hz)
            for item in self.config.motors
        }
        self.motor_values = {channel: 0.0 for channel in self._motors}
        if servo_controller is not None:
            self._servos = servo_controller
        elif isinstance(self.gpio, MockGPIO):
            self._servos = MockServoController(self.config.servos)
        else:
            self._servos = PCA9685Controller(self.config.servos)
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop, name="motionmodule-watchdog", daemon=True
        )
        self._watchdog_thread.start()

    def motor(self, channel: int) -> Motor:
        if channel not in self._motors:
            raise ValueError(f"Motor channel {channel} is not configured")
        return Motor(self, channel)

    def servo(self, channel: int, board: int = 0) -> Servo:
        if not self.config.servos.enabled:
            raise ValueError("Servo support is disabled in the configuration")
        if not 0 <= board < len(self.config.servos.addresses):
            raise ValueError(f"Servo board {board} is not configured")
        if not 0 <= channel <= 15:
            raise ValueError("Servo channel must be from 0 through 15")
        return Servo(self._servos, board, channel)

    def set_motors(self, outputs: dict[int, float]) -> None:
        if not outputs:
            return
        clean: dict[int, float] = {}
        for channel, value in outputs.items():
            if channel not in self._motors:
                raise ValueError(f"Motor channel {channel} is not configured")
            if isinstance(value, bool) or not isinstance(value, (int, float)):
                raise ValueError("Motor values must be numbers")
            value = float(value)
            if not math.isfinite(value):
                raise ValueError("Motor values must be finite")
            clean[channel] = max(-1.0, min(1.0, value))

        with self._lock:
            if self._closed:
                return
            if any(self._motors[channel].would_reverse(value) for channel, value in clean.items()):
                self._apply_all_zero()
                time.sleep(self.config.deadtime_ms / 1000.0)
            for channel, value in clean.items():
                self._motors[channel].set(value)
                self.motor_values[channel] = value
            self._last_feed = time.monotonic()
            self._watchdog_armed = any(value != 0 for value in self.motor_values.values())
            self._watchdog_tripped = False

    def feed_watchdog(self) -> None:
        with self._lock:
            self._last_feed = time.monotonic()

    def stop_all(self) -> None:
        with self._lock:
            self._apply_all_zero()
            self._watchdog_armed = False

    def _apply_all_zero(self) -> None:
        for channel, motor in self._motors.items():
            motor.set(0)
            self.motor_values[channel] = 0.0

    def _watchdog_loop(self) -> None:
        interval = max(0.01, self.config.watchdog_ms / 4000.0)
        timeout = self.config.watchdog_ms / 1000.0
        while not self._stop_event.wait(interval):
            with self._lock:
                if self._watchdog_armed and time.monotonic() - self._last_feed > timeout:
                    self._apply_all_zero()
                    self._watchdog_armed = False
                    self._watchdog_tripped = True

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "hardware": bool(getattr(self.gpio, "is_hardware", False)),
                "motors": dict(self.motor_values),
                "watchdog_ms": self.config.watchdog_ms,
                "watchdog_armed": self._watchdog_armed,
                "watchdog_tripped": self._watchdog_tripped,
                "servos": {
                    f"{board}:{channel}": angle
                    for (board, channel), angle in self._servos.angles.items()
                },
                "servo_outputs": {
                    f"{board}:{channel}": {"pulse_us": pulse_us}
                    for (board, channel), pulse_us in getattr(self._servos, "pulses", {}).items()
                },
                "servo_boards": [
                    {
                        "index": index,
                        "address": f"0x{address:02x}",
                        "available": address in self._servos.available,
                        "error": self._servos.errors.get(address),
                    }
                    for index, address in enumerate(self.config.servos.addresses)
                ],
            }

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._watchdog_armed = False
            self._apply_all_zero()
            self._servos.close()
            self.gpio.close()
        self._stop_event.set()
        self._watchdog_thread.join(timeout=1)

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback):
        self.close()
