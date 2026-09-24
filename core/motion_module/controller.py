"""Coordinated motor, servo, deadtime, and watchdog management."""

from __future__ import annotations

import logging
import math
import threading
import time

from .config import ModuleConfig, load_config
from .errors import ConfigurationError, MotionModuleError
from .gpio import MockGPIO, create_gpio_backend
from .input import DigitalInput, available_input_gpios
from .motor import HBridgeMotor, Motor
from .servo import MockServoController, PCA9685Controller, Servo


class MotionModule:
    """Main API passed into robot projects.

    Outputs are addressed by the names in ``hardware.py``::

        module.motor("front_left").set(0.5)
        module.servo("claw").set_angle(90)

    The underlying numbers still work: motor channels are 1-8, PCA9685 boards
    are numbered from 0, and each board provides channels 0-15.
    """

    def __init__(self, config: ModuleConfig | None = None, gpio=None, servo_controller=None) -> None:
        self.config = config or load_config()
        self.gpio = gpio or create_gpio_backend()
        self._lock = threading.RLock()
        self._closed = False
        self._watchdog_tripped = False
        self._watchdog_armed = False
        self._last_feed = time.monotonic()
        self._last_servo_probe = time.monotonic()
        self._stop_event = threading.Event()
        self._giga = None
        self._local_imu = None
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
        # OE is a plain Pi output, so MotionModule owns it rather than the I2C
        # class: cutting the outputs has to keep working when the bus does not.
        self._oe_gpio = self.config.servos.output_enable_gpio
        self._servo_outputs_enabled = True
        if self._oe_gpio is not None:
            self.gpio.claim_output(self._oe_gpio)
            self._write_output_enable(True)
        self._watchdog_thread = threading.Thread(
            target=self._watchdog_loop, name="motionmodule-watchdog", daemon=True
        )
        self._watchdog_thread.start()

    def motor(self, channel: int | str) -> Motor:
        """Return one motor by its hardware.py name or by channel number."""

        number = self._resolve_motor(channel)
        return Motor(self, number, self.config.motor(number).name)

    def servo(self, channel: int | str, board: int = 0) -> Servo:
        """Return one servo by its hardware.py name or by board and channel."""

        if not self.config.servos.enabled:
            raise ValueError("Servo support is disabled in hardware.py")
        try:
            slot = self.config.servo_slot(channel, board)
        except ConfigurationError as error:
            raise ValueError(str(error)) from error
        if not 0 <= slot.board < len(self.config.servos.addresses):
            raise ValueError(f"Servo board {slot.board} is not configured")
        if not 0 <= slot.channel <= 15:
            raise ValueError("Servo channel must be from 0 through 15")
        return Servo(self._servos, slot.board, slot.channel, slot.name)

    def digital_input(self, gpio: int, *, pull: str = "none") -> DigitalInput:
        """Claim an unused Raspberry Pi BCM GPIO as a digital sensor input."""

        if isinstance(gpio, bool) or not isinstance(gpio, int):
            raise ValueError("Digital input GPIO must be a BCM pin number")
        if gpio not in available_input_gpios(self.config):
            available = ", ".join(f"GPIO{pin}" for pin in available_input_gpios(self.config))
            raise ValueError(
                f"GPIO{gpio} is used or reserved by the active hardware map. "
                f"Available inputs: {available or 'none'}"
            )
        pull = str(pull).strip().casefold()
        if pull not in {"none", "up", "down"}:
            raise ValueError("Digital input pull must be 'none', 'up', or 'down'")
        self.gpio.claim_input(gpio, pull)
        return DigitalInput(self.gpio, gpio, pull)

    @property
    def hardware(self) -> bool:
        """True on a Raspberry Pi driving real pins, False in simulation."""

        return bool(getattr(self.gpio, "is_hardware", False))

    def local_imu(self, declaration):
        """Read the reference Pi IMU on the independent i2c-gpio bus.

        Returns None in simulation or if the bus overlay is missing. The
        module owns the reader and closes it during shutdown.
        """
        from .pi_imu import LocalIMU, find_i2c_gpio_bus

        with self._lock:
            if self._closed:
                raise RuntimeError("MotionModule is closed")
            if self._local_imu is not None:
                if self._local_imu.declaration != declaration:
                    raise ValueError("The Pi IMU is already configured differently")
                return self._local_imu
            if not self.hardware:
                return None
            bus = find_i2c_gpio_bus()
            if bus is None:
                return None
            self._local_imu = LocalIMU(declaration, bus=bus, auto_address=True)
            return self._local_imu

    def giga(self, pins=(), imus=(), *, serial: str = ""):
        """Optional USB GPIO expansion through an Arduino GIGA R1 WiFi.

        Declare every pin and IMU wired to the GIGA in one call, normally in
        sensors.py; calling again with the same declarations returns the same
        bridge. In simulation the board is never opened, so a laptop demo or a
        test cannot take the port from a running robot.
        """

        from .sensor_bridge import GigaR1Bridge

        with self._lock:
            if self._closed:
                raise RuntimeError("MotionModule is closed")
            bridge = self._giga
            if bridge is None:
                bridge = self._giga = GigaR1Bridge(pins, imus=imus, serial=serial, simulated=not self.hardware)
                return bridge.start()
            if bridge.matches(pins, imus, serial):
                return bridge
        raise ValueError(
            "The GIGA is already set up with other sensors. Declare all of its pins and IMUs "
            "once, in sensors.py, and share that object."
        )

    @property
    def servo_outputs_enabled(self) -> bool:
        """Whether the servo board's outputs are currently enabled at OE."""

        return self._servo_outputs_enabled

    def set_servo_outputs_enabled(self, enabled: bool) -> None:
        """Enable or disable all 16 servo outputs at the board's OE pin.

        OE is active low and cuts the outputs in hardware, so it works even if
        the I2C bus has stopped answering. It is an enable line, not a power
        cutoff: the servo rail stays live, and a board with OE unconnected
        pulls it low and stays enabled.
        """

        enabled = bool(enabled)
        with self._lock:
            if self._closed:
                return
            if self._oe_gpio is None:
                if not enabled:
                    raise ConfigurationError(
                        "No servos.output_enable_gpio is set in hardware.py, so the servo "
                        "board's OE pin is not wired to the Pi and cannot disable the outputs"
                    )
                return
            self._write_output_enable(enabled)

    def _write_output_enable(self, enabled: bool) -> None:
        """OE low enables the outputs; OE high disables them."""

        self.gpio.write(self._oe_gpio, not enabled)
        self._servo_outputs_enabled = enabled

    def _resolve_motor(self, reference: int | str) -> int:
        try:
            number = self.config.motor_channel(reference)
        except ConfigurationError as error:
            raise ValueError(str(error)) from error
        if number not in self._motors:
            raise ValueError(f"Motor channel {number} is not configured")
        return number

    def set_motors(self, outputs: dict[int | str, float]) -> None:
        """Set several motors at once, by name or by channel number."""

        if not outputs:
            return
        clean: dict[int, float] = {}
        for reference, value in outputs.items():
            channel = self._resolve_motor(reference)
            if channel in clean:
                raise ValueError(f"Motor channel {channel} was specified more than once; use its name or number once")
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

    def refresh_servo_boards(self, *, interval: float = 2.0) -> None:
        """Ask the servo boards whether they are still there.

        Boards are detected once at startup, which cannot tell the difference
        between a board that was never connected and one whose I2C wire fell
        off ten minutes ago. Re-probing keeps the dashboard honest in both
        directions. Rate limited so a fast status poll cannot flood the bus.
        """

        probe = getattr(self._servos, "probe", None)
        if not callable(probe):
            return
        with self._lock:
            if self._closed:
                return
            now = time.monotonic()
            if now - self._last_servo_probe < interval:
                return
            self._last_servo_probe = now
        try:
            probe()
        except OSError:
            pass

    def feed_watchdog(self) -> None:
        with self._lock:
            self._last_feed = time.monotonic()

    def stop_all(self) -> None:
        """Coast every motor immediately. Servos keep holding until released."""

        with self._lock:
            if self._closed:
                return
            self._apply_all_zero()
            self._watchdog_armed = False

    def release_all_servos(self) -> None:
        """Stop driving every servo output.

        A released servo stops holding its position, so a loaded mechanism can
        fall. This deliberately leaves the OE line alone: the dashboard sends a
        stop on every page hide, and cutting the outputs there would leave them
        disabled after an ordinary navigation. Use
        ``set_servo_outputs_enabled(False)`` when you mean to cut them.
        ``stop_all`` deliberately does not release servos; the dashboard STOP
        button does, so that what the page shows matches what the wires carry.
        """

        with self._lock:
            if self._closed:
                return
            held = {*self._servos.angles, *getattr(self._servos, "pulses", {})}
            for board, channel in sorted(held):
                try:
                    self._servos.release(board, channel)
                except (MotionModuleError, ValueError, OSError):
                    continue

    def _apply_all_zero(self) -> None:
        failures = []
        for channel, motor in self._motors.items():
            try:
                motor.set(0)
            except Exception as error:
                failures.append(error)
            else:
                self.motor_values[channel] = 0.0
        if failures:
            raise ExceptionGroup("Could not stop every motor", failures)

    def _watchdog_loop(self) -> None:
        interval = max(0.01, self.config.watchdog_ms / 4000.0)
        timeout = self.config.watchdog_ms / 1000.0
        while not self._stop_event.wait(interval):
            with self._lock:
                if self._watchdog_armed and time.monotonic() - self._last_feed > timeout:
                    try:
                        self._apply_all_zero()
                    except Exception:
                        if not self._watchdog_tripped:
                            logging.getLogger(__name__).exception("Motor stop failed; watchdog will retry")
                    else:
                        self._watchdog_armed = False
                    finally:
                        self._watchdog_tripped = True

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "hardware": bool(getattr(self.gpio, "is_hardware", False)),
                "motors": dict(self.motor_values),
                "motor_names": {
                    str(item.channel): item.name for item in self.config.motors
                },
                "servo_names": {
                    f"{slot.board}:{slot.channel}": slot.name
                    for slot in self.config.servos.channels
                },
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
                "servo_output_enable": {
                    "gpio": self._oe_gpio,
                    "wired": self._oe_gpio is not None,
                    "enabled": self._servo_outputs_enabled,
                },
                "servo_boards": [
                    {
                        "index": index,
                        "address": f"0x{address:02x}",
                        "available": address in self._servos.available,
                        "error": self._servos.errors.get(address),
                        "fault": getattr(self._servos, "faults", {}).get(address),
                    }
                    for index, address in enumerate(self.config.servos.addresses)
                ],
            }

    def close(self) -> None:
        failures = []

        def attempt(action, *args):
            try:
                action(*args)
            except Exception as error:
                failures.append(error)

        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._watchdog_armed = False
            self._stop_event.set()
            # A failed output must not prevent stopping the remaining ones
            # or closing the bus, GPIO handle and sensor threads.
            attempt(self._apply_all_zero)
            if self._oe_gpio is not None:
                attempt(self._write_output_enable, False)
            attempt(self._servos.close)
            attempt(self.gpio.close)
            giga, self._giga = self._giga, None
            local_imu, self._local_imu = self._local_imu, None
        self._watchdog_thread.join(timeout=1)
        if giga is not None:
            attempt(giga.close)
        if local_imu is not None:
            attempt(local_imu.close)
        if failures:
            raise ExceptionGroup("Errors while shutting down MotionModule", failures)

    def __enter__(self):
        return self

    def __exit__(self, _type, _value, _traceback):
        self.close()
