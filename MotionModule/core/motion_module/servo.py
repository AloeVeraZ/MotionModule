"""PCA9685 servo boards sharing the Raspberry Pi I2C bus."""

from __future__ import annotations

import math
import time
from threading import RLock

from .config import ServoConfig
from .errors import HardwareUnavailable


MODE1 = 0x00
MODE2 = 0x01
LED0_ON_L = 0x06
PRESCALE = 0xFE
RESTART = 0x80
SLEEP = 0x10
OUTDRV = 0x04


class PCA9685Controller:
    """Initialize and control one or more independently addressed PCA9685 boards."""

    is_hardware = True

    def __init__(self, config: ServoConfig, bus=None) -> None:
        self.config = config
        self._lock = RLock()
        self._owns_bus = bus is None
        self._bus = bus
        self.available: set[int] = set()
        self.errors: dict[int, str] = {}
        self.angles: dict[tuple[int, int], float] = {}
        if not config.enabled:
            return
        try:
            if self._bus is None:
                from smbus2 import SMBus

                self._bus = SMBus(config.i2c_bus)
        except (ImportError, OSError) as error:
            self.errors = {address: str(error) for address in config.addresses}
            return
        for address in config.addresses:
            try:
                self._initialize(address)
                self.available.add(address)
            except OSError as error:
                self.errors[address] = str(error)

    def _initialize(self, address: int) -> None:
        self._bus.write_byte_data(address, MODE1, 0x00)
        self._bus.write_byte_data(address, MODE2, OUTDRV)
        old_mode = self._bus.read_byte_data(address, MODE1)
        sleep_mode = (old_mode & 0x7F) | SLEEP
        prescale = round(25_000_000 / (4096 * self.config.frequency_hz) - 1)
        self._bus.write_byte_data(address, MODE1, sleep_mode)
        self._bus.write_byte_data(address, PRESCALE, prescale)
        self._bus.write_byte_data(address, MODE1, old_mode)
        time.sleep(0.005)
        self._bus.write_byte_data(address, MODE1, old_mode | RESTART)
        for channel in range(16):
            self._write_counts(address, channel, 0, 0, full_off=True)

    def _address(self, board: int) -> int:
        if not 0 <= board < len(self.config.addresses):
            raise ValueError(f"Servo board {board} is not configured")
        address = self.config.addresses[board]
        if address not in self.available:
            reason = self.errors.get(address, "no I2C response")
            raise HardwareUnavailable(f"PCA9685 board {board} at 0x{address:02x} is unavailable: {reason}")
        return address

    def _write_counts(
        self, address: int, channel: int, on: int, off: int, *, full_off: bool = False
    ) -> None:
        register = LED0_ON_L + 4 * channel
        off_high = ((off >> 8) & 0x0F) | (0x10 if full_off else 0)
        payload = [on & 0xFF, (on >> 8) & 0x0F, off & 0xFF, off_high]
        self._bus.write_i2c_block_data(address, register, payload)

    def set_angle(self, board: int, channel: int, angle: float) -> None:
        if not 0 <= channel <= 15:
            raise ValueError("Servo channel must be from 0 through 15")
        angle = float(angle)
        if not math.isfinite(angle) or not 0 <= angle <= 180:
            raise ValueError("Servo angle must be a finite value from 0 through 180")
        address = self._address(board)
        pulse_us = self.config.minimum_pulse_us + (
            self.config.maximum_pulse_us - self.config.minimum_pulse_us
        ) * angle / 180.0
        counts = round(pulse_us * self.config.frequency_hz * 4096 / 1_000_000)
        with self._lock:
            self._write_counts(address, channel, 0, min(4095, counts))
            self.angles[(board, channel)] = angle

    def release(self, board: int, channel: int) -> None:
        if not 0 <= channel <= 15:
            raise ValueError("Servo channel must be from 0 through 15")
        address = self._address(board)
        with self._lock:
            self._write_counts(address, channel, 0, 0, full_off=True)
            self.angles.pop((board, channel), None)

    def close(self) -> None:
        if self._bus is None:
            return
        for address in self.available:
            for channel in range(16):
                try:
                    self._write_counts(address, channel, 0, 0, full_off=True)
                except OSError:
                    break
        if self._owns_bus:
            try:
                self._bus.close()
            except OSError:
                pass


class MockServoController:
    is_hardware = False

    def __init__(self, config: ServoConfig) -> None:
        self.config = config
        self.available = set(config.addresses) if config.enabled else set()
        self.errors: dict[int, str] = {}
        self.angles: dict[tuple[int, int], float] = {}

    def set_angle(self, board: int, channel: int, angle: float) -> None:
        if not 0 <= board < len(self.config.addresses):
            raise ValueError(f"Servo board {board} is not configured")
        if not 0 <= channel <= 15:
            raise ValueError("Servo channel must be from 0 through 15")
        angle = float(angle)
        if not math.isfinite(angle) or not 0 <= angle <= 180:
            raise ValueError("Servo angle must be a finite value from 0 through 180")
        self.angles[(board, channel)] = angle

    def release(self, board: int, channel: int) -> None:
        self.angles.pop((board, channel), None)

    def close(self) -> None:
        self.angles.clear()


class Servo:
    def __init__(self, controller, board: int, channel: int) -> None:
        self._controller = controller
        self.board = board
        self.channel = channel

    @property
    def angle(self) -> float | None:
        return self._controller.angles.get((self.board, self.channel))

    def set_angle(self, angle: float) -> None:
        self._controller.set_angle(self.board, self.channel, angle)

    def release(self) -> None:
        self._controller.release(self.board, self.channel)

