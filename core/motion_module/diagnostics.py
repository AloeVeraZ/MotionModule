"""Non-moving checks shared by the dashboard and command-line doctor."""

from __future__ import annotations

from pathlib import Path
import re
import subprocess

from .config import load_config
from .errors import MotionModuleError
from .pinout import motor_rows


def pi_power_check(hardware: bool) -> dict:
    """Read firmware flags only; never change outputs or infer battery current.

    Bit definitions: Raspberry Pi's official vcgencmd get_throttled docs.
    This runs on demand in diagnostics, not in the motor command loop.
    """

    check = {"id": "pi-power", "title": "Pi undervoltage / throttling", "level": "info"}
    if not hardware:
        return {**check, "detail": "Simulation: Pi power flags are unavailable; no battery voltage or motor current is measured."}
    try:
        result = subprocess.run(
            ["vcgencmd", "get_throttled"], capture_output=True, text=True,
            timeout=1, check=False,
        )
        match = re.fullmatch(r"throttled=(0x[0-9a-fA-F]+)", result.stdout.strip())
        if result.returncode != 0 or match is None:
            return {**check, "detail": "Firmware power flags unavailable (vcgencmd failed or returned an unsupported response). This is not a clean power report."}
    except (OSError, subprocess.TimeoutExpired):
        return {**check, "detail": "Firmware power flags unavailable (vcgencmd missing, inaccessible, or timed out). This is not a clean power report."}

    flags = int(match.group(1), 16)
    descriptions = {
        0: "undervoltage NOW", 1: "CPU frequency capped NOW",
        2: "throttling NOW", 3: "soft temperature limit NOW",
        16: "undervoltage recorded this boot", 17: "CPU frequency capping recorded this boot",
        18: "throttling recorded this boot", 19: "soft temperature limit recorded this boot",
    }
    events = [description for bit, description in descriptions.items() if flags & (1 << bit)]
    summary = "; ".join(events) if events else (
        "Unrecognized firmware flags" if flags else "No firmware undervoltage or throttling flags reported this boot"
    )
    if flags & ((1 << 0) | (1 << 16)):
        summary += ". Avoid high-power tests until the battery, connections, and Pi supply are checked"
    return {
        **check, "level": "warn" if flags else "info", "raw_flags": hex(flags),
        "detail": (
            f"{summary} ({hex(flags)}). These flags are not battery-voltage or motor-current measurements. "
            "History resets on reboot; a clean report cannot rule out abrupt power loss. "
            "This check does not limit motor power or prevent a brownout."
        ),
    }


def _pin_map_conflicts(module) -> list[dict]:
    """Compare what the robot is running against the map installed on the Pi.

    A deployed project may legitimately bring its own hardware.py. Saying so
    explicitly is what makes a surprise — an output that will not move, or a
    name that disappeared — easy to spot instead of mysterious.
    """

    try:
        installed = load_config(project="")
    except MotionModuleError as error:
        return [{
            "id": "pin-map",
            "level": "warn",
            "title": "Installed hardware map",
            "detail": f"The map installed on this Pi could not be read: {error}",
        }]

    active = module.config
    if active == installed:
        return [{
            "id": "pin-map",
            "level": "pass",
            "title": "Pin map source",
            "detail": "The running robot uses the hardware map installed on this Pi. The bench tests and your code agree.",
        }]

    installed_by_channel = {item.channel: item for item in installed.motors}
    moved, renamed = [], []
    for item in active.motors:
        reference = installed_by_channel.get(item.channel)
        if reference is None:
            moved.append(f"channel {item.channel} is not on the installed map")
        elif (item.forward_gpio, item.reverse_gpio) != (reference.forward_gpio, reference.reverse_gpio):
            moved.append(
                f"channel {item.channel} moved to GPIO{item.forward_gpio}/{item.reverse_gpio}"
            )
        elif item.name != reference.name:
            renamed.append(f"{reference.name} is called {item.name}")

    missing = sorted(set(installed_by_channel) - {item.channel for item in active.motors})
    parts = []
    if moved:
        parts.append("moved pins: " + "; ".join(moved))
    if missing:
        parts.append("channels the project drops: " + ", ".join(str(c) for c in missing))
    if renamed:
        parts.append("renamed: " + "; ".join(renamed))

    return [{
        "id": "pin-map",
        "level": "warn" if moved or missing else "info",
        "title": "Project overrides the installed pin map",
        "detail": (
            "The active project ships its own hardware.py. "
            + (". ".join(parts) if parts else "Settings differ from the installed map.")
            + ". Test outputs and Drive both use this active hardware map."
        ),
    }]


def dashboard_checks(module) -> list[dict]:
    snapshot = module.snapshot()
    checks = [
        {
            "id": "configuration",
            "level": "pass",
            "title": "Hardware configuration",
            "detail": f"{len(module.config.motors)} motor channels passed pin-conflict validation.",
        },
        {
            "id": "gpio",
            "level": "pass" if snapshot.get("hardware") else "info",
            "title": "GPIO backend",
            "detail": "Raspberry Pi GPIO is active." if snapshot.get("hardware") else "Simulation mode is active; no physical outputs are being driven.",
        },
        {
            "id": "watchdog",
            "level": "warn" if snapshot.get("watchdog_tripped") else "pass",
            "title": "Motor safety watchdog",
            "detail": (
                "The watchdog stopped stale motor output. This is safe; inspect control/network logs if unexpected."
                if snapshot.get("watchdog_tripped")
                else f"Armed only while moving; stale commands stop in {module.config.watchdog_ms} ms."
            ),
        },
        {
            "id": "motor-map",
            "level": "pass",
            "title": "Motor signal map",
            "detail": f"{len(motor_rows(module.config))} channels use unique GPIO pairs across four drivers.",
        },
    ]
    checks.extend(_pin_map_conflicts(module))
    checks.append(pi_power_check(bool(snapshot.get("hardware"))))
    spi_active = any(Path("/dev").glob("spidev*"))
    checks.append(
        {
            "id": "spi",
            "level": "warn" if spi_active else "pass",
            "title": "SPI pin conflict",
            "detail": (
                "SPI is active and conflicts with Driver 3/4 GPIO7, GPIO8, GPIO9, and GPIO11. Disable SPI before motor power."
                if spi_active
                else "No active SPI device conflicts with Drivers 3 and 4."
            ),
        }
    )
    if not module.config.servos.enabled:
        checks.append({"id": "servos", "level": "info", "title": "Servo boards", "detail": "Servo support is disabled in the active hardware configuration."})
    else:
        for board in snapshot.get("servo_boards", []):
            # Three outcomes, not two: answering, answering but refusing writes,
            # and silent. The middle one is what a half-connected board looks
            # like, and it is the one that is hardest to guess from a wire.
            if not board.get("available"):
                level = "warn"
                detail = (
                    "Not connected. Nothing answered at this address, so no servo on this "
                    "board can move. Check SDA on pin 3, SCL on pin 5, VCC on pin 1 and GND "
                    f"on pin 9. I2C reported: {board.get('error') or 'board not detected'}"
                )
            elif board.get("fault"):
                level = "warn"
                detail = (
                    "Answering on I2C but the last command was rejected: "
                    f"{board['fault']}. Usually a loose SDA or SCL wire, or the board "
                    "browning out when a servo pulls current."
                )
            else:
                level = "pass"
                detail = "Responding on the I2C bus."
            checks.append(
                {
                    "id": f"servo-{board['index']}",
                    "level": level,
                    "title": f"PCA9685 board {board['index']} · {board['address']}",
                    "detail": detail,
                }
            )
    return checks
