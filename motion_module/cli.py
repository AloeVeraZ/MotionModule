"""Read-only checks plus explicitly confirmed bench tests."""

from __future__ import annotations

import argparse
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path

from . import __version__
from .config import load_config
from .controller import MotionModule
from .errors import MotionModuleError
from .gpio import is_raspberry_pi
from .pinout import motor_rows


def _service_active() -> bool:
    if platform.system() != "Linux":
        return False
    result = subprocess.run(
        ["systemctl", "is-active", "--quiet", "motionmodule.service"],
        check=False,
        capture_output=True,
    )
    return result.returncode == 0


def _scan_i2c(config) -> list[dict]:
    results = []
    if not config.servos.enabled:
        return results
    try:
        from smbus2 import SMBus

        with SMBus(config.servos.i2c_bus) as bus:
            for address in config.servos.addresses:
                try:
                    bus.read_byte_data(address, 0x00)
                    results.append({"address": address, "ok": True, "detail": "responded"})
                except OSError as error:
                    results.append({"address": address, "ok": False, "detail": str(error)})
    except (ImportError, OSError) as error:
        for address in config.servos.addresses:
            results.append({"address": address, "ok": False, "detail": str(error)})
    return results


def doctor(as_json: bool = False) -> int:
    checks: list[dict] = []
    try:
        config = load_config()
        checks.append({"name": "configuration", "status": "pass", "detail": "pin map is valid"})
    except MotionModuleError as error:
        checks.append({"name": "configuration", "status": "fail", "detail": str(error)})
        if as_json:
            print(json.dumps({"checks": checks}, indent=2))
        else:
            print(f"FAIL configuration: {error}")
        return 1

    pi = is_raspberry_pi()
    checks.append(
        {
            "name": "platform",
            "status": "pass" if pi else "info",
            "detail": "Raspberry Pi detected" if pi else "development computer; GPIO will be simulated",
        }
    )
    if pi:
        gpio_ok = Path("/dev/gpiochip0").exists()
        try:
            import lgpio  # noqa: F401
        except ImportError:
            gpio_ok = False
        checks.append(
            {
                "name": "gpio",
                "status": "pass" if gpio_ok else "fail",
                "detail": "lgpio and gpiochip0 are available" if gpio_ok else "lgpio or /dev/gpiochip0 is missing",
            }
        )
        spi_active = any(Path("/dev").glob("spidev*"))
        checks.append(
            {
                "name": "spi-pins",
                "status": "warn" if spi_active else "pass",
                "detail": "SPI is active and conflicts with Drivers 3/4" if spi_active else "SPI device is not active",
            }
        )

    for result in _scan_i2c(config) if pi else []:
        checks.append(
            {
                "name": f"servo-0x{result['address']:02x}",
                "status": "pass" if result["ok"] else "warn",
                "detail": result["detail"],
            }
        )
    checks.append(
        {
            "name": "motor-drivers",
            "status": "info",
            "detail": "four drivers are configured; input-only H-bridges cannot identify themselves electronically",
        }
    )
    checks.append(
        {
            "name": "service",
            "status": "pass" if _service_active() else "info",
            "detail": "motionmodule.service is running" if _service_active() else "service is not running here",
        }
    )
    if as_json:
        print(json.dumps({"version": __version__, "checks": checks}, indent=2))
    else:
        print(f"MotionModule {__version__}")
        for check in checks:
            print(f"{check['status'].upper():4} {check['name']}: {check['detail']}")
    return 1 if any(item["status"] == "fail" for item in checks) else 0


def show_pinout() -> int:
    config = load_config()
    print("Motor driver pinout (IN1/IN2 are direction/PWM inputs)")
    print("Driver Out Motor Name          IN1 physical/BCM  IN2 physical/BCM  Inverted")
    for row in motor_rows(config):
        print(
            f"{row['driver']:>6} {row['output']:>3} {row['motor']:>5} {row['name']:<13} "
            f"pin {row['in1_physical']:>2}/GPIO{row['in1_bcm']:<2}   "
            f"pin {row['in2_physical']:>2}/GPIO{row['in2_bcm']:<2}   "
            f"{'yes' if row['inverted'] else 'no'}"
        )
    print("Grounds: Driver 1 pin 39; Driver 2 pin 34; Driver 3 pin 20; Driver 4 pin 25")
    print("Servo I2C: SDA pin 3/GPIO2; SCL pin 5/GPIO3; logic VCC pin 1/3.3V; GND pin 6")
    return 0


def _require_bench_confirmation(yes: bool) -> None:
    if _service_active():
        raise MotionModuleError("Stop the running service first: sudo systemctl stop motionmodule")
    if yes:
        return
    print("DANGER: raise the robot, clear the mechanism, and keep a physical power switch in reach.")
    answer = input("Type RAISED to continue: ").strip()
    if answer != "RAISED":
        raise MotionModuleError("Bench test cancelled")


def test_motor(channel: int, power: float, seconds: float, yes: bool) -> int:
    _require_bench_confirmation(yes)
    if not 0 < abs(power) <= 0.25:
        raise MotionModuleError("Bench-test power must be above 0 and no more than 0.25")
    if not 0 < seconds <= 2:
        raise MotionModuleError("Bench-test duration must be above 0 and no more than 2 seconds")
    with MotionModule() as controller:
        print(f"Pulsing motor {channel} at {power:+.0%} for {seconds:.2f} seconds")
        controller.motor(channel).set(power)
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            controller.feed_watchdog()
            time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        controller.stop_all()
    print("Motor stopped.")
    return 0


def test_servo(board: int, channel: int, angle: float, yes: bool) -> int:
    _require_bench_confirmation(yes)
    if not 0 <= angle <= 180:
        raise MotionModuleError("Servo angle must be between 0 and 180")
    with MotionModule() as controller:
        servo = controller.servo(channel, board)
        print(f"Moving servo board {board}, channel {channel} to {angle:.1f} degrees")
        servo.set_angle(angle)
        time.sleep(0.5)
        servo.release()
    print("Servo pulse released.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="MotionModule diagnostics and bench tools")
    parser.add_argument("--version", action="version", version=__version__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    doctor_parser = subparsers.add_parser("doctor", help="Run non-moving hardware checks")
    doctor_parser.add_argument("--json", action="store_true")
    subparsers.add_parser("pinout", help="Print the active physical/BCM pin map")
    motor_parser = subparsers.add_parser("test-motor", help="Pulse one raised-wheel motor")
    motor_parser.add_argument("channel", type=int)
    motor_parser.add_argument("--power", type=float, default=0.15)
    motor_parser.add_argument("--seconds", type=float, default=0.5)
    motor_parser.add_argument("--yes", action="store_true")
    servo_parser = subparsers.add_parser("test-servo", help="Move and release one disconnected servo")
    servo_parser.add_argument("channel", type=int)
    servo_parser.add_argument("--board", type=int, default=0)
    servo_parser.add_argument("--angle", type=float, default=90)
    servo_parser.add_argument("--yes", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "doctor":
            return doctor(args.json)
        if args.command == "pinout":
            return show_pinout()
        if args.command == "test-motor":
            return test_motor(args.channel, args.power, args.seconds, args.yes)
        if args.command == "test-servo":
            return test_servo(args.board, args.channel, args.angle, args.yes)
    except (MotionModuleError, OSError, ValueError) as error:
        print(f"MotionModule error: {error}", file=sys.stderr)
        return 1
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

