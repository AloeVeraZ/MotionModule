"""Raspberry Pi 5 active-cooler settings and read-only cooling status.

The Pi 5's fan plugs into its own four-pin FAN connector, not the 40-pin GPIO
header, and the Pi's firmware and kernel drive it: the ``cooling_fan`` base
device-tree parameter hands the fan to the kernel's thermal governor, which
switches its speed at the ``fan_temp*`` thresholds. MotionModule only writes
those settings into config.txt. It never runs the fan itself, so cooling keeps
working when MotionModule, the dashboard or the robot project is stopped or
broken. (Official reference: the ``cooling_fan`` and ``fan_temp*`` parameters
in the firmware's boot/overlays/README, and "Cooling Raspberry Pi 5" in the
Raspberry Pi documentation.)

    python3 cooling.py configure /boot/firmware/config.txt

adds, or brings up to date, one marked ``[pi5]`` block and keeps a backup of
the file it changed. This file uses only the standard library so the installer
can run it with the system Python before any release is built.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import time
from pathlib import Path


# (threshold, hysteresis) in millidegrees C and a fan PWM value from 0-255.
# The thresholds are the firmware's documented defaults; the hysteresis keeps
# each level on until the CPU is 5 C below where it started, so the fan starts
# at 50 C and stops again below 45 C. The speeds rise level by level.
COOLING_LEVELS = (
    (50000, 5000, 75),
    (60000, 5000, 125),
    (67500, 5000, 175),
    (75000, 5000, 250),
)
BEGIN = "# >>> MotionModule: Raspberry Pi 5 fan cooling (managed block) >>>"
END = "# <<< MotionModule: Raspberry Pi 5 fan cooling <<<"
# A setting of the Pi 5 fan that someone put in config.txt themselves.
FAN_SETTING = re.compile(r"^\s*dtparam\s*=.*\b(cooling_fan|fan_temp[0-3](_hyst|_speed)?)\b")


def managed_block() -> str:
    lines = [
        BEGIN,
        "# The Pi 5 fan on its own FAN connector (not the GPIO header), run by the",
        "# Pi's firmware and kernel, so it keeps cooling even when MotionModule is",
        "# stopped. On at 50 C, off again below 45 C, faster at 60, 67.5 and 75 C.",
        "# The MotionModule installer rewrites this block; delete the whole block",
        "# and set these lines yourself to use other values.",
        "[pi5]",
        "dtparam=cooling_fan=on",
    ]
    for level, (temperature, hysteresis, speed) in enumerate(COOLING_LEVELS):
        lines += [
            f"dtparam=fan_temp{level}={temperature}",
            f"dtparam=fan_temp{level}_hyst={hysteresis}",
            f"dtparam=fan_temp{level}_speed={speed}",
        ]
    lines += ["[all]", END]
    return "\n".join(lines) + "\n"


def _without_block(text: str) -> tuple[str, bool]:
    """The config with every managed block removed, and whether there was one."""

    kept: list[str] = []
    inside = found = just_ended = False
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped == BEGIN:
            inside = found = True
            continue
        if inside:
            if stripped == END:
                inside, just_ended = False, True
            continue
        if just_ended and not stripped:
            just_ended = False  # the blank line configured_text puts after the block
            continue
        just_ended = False
        kept.append(line)
    if inside:
        # A block whose end marker was deleted: keep the text rather than
        # guess how much of the rest of the file was ours.
        return text, False
    return "".join(kept), found


def _insertion_point(lines: list[str]) -> int:
    """Before the first setting and the comment right above it.

    Base parameters must come before the first dtoverlay line, or config.txt
    can treat them as that overlay's parameters.
    """

    for index, line in enumerate(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            while index > 0 and lines[index - 1].strip().startswith("#"):
                index -= 1
            return index
    return len(lines)


def configured_text(text: str) -> tuple[str, str]:
    """The config.txt contents with the managed block, and what changed.

    Nothing else in the file changes. If the file already sets the Pi 5 fan
    outside the block, those settings are the owner's and are left in charge.
    """

    rest, had_block = _without_block(text)
    foreign = [line.strip() for line in rest.splitlines() if FAN_SETTING.match(line)]
    if foreign:
        message = (
            "Kept the Pi 5 fan settings already in config.txt ("
            + "; ".join(foreign[:4]) + ("; ..." if len(foreign) > 4 else "")
            + "). Delete them and reinstall to use MotionModule's 50 C / 45 C settings."
        )
        return rest, message + (" Removed MotionModule's older fan block." if had_block else "")
    lines = rest.splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
    at = _insertion_point(lines)
    block = managed_block()
    if at < len(lines):
        block += "\n"
    new = "".join(lines[:at]) + block + "".join(lines[at:])
    if new == text:
        return text, "Pi 5 fan cooling is already configured (on at 50 C, off below 45 C)."
    verb = "Updated" if had_block else "Enabled"
    return new, f"{verb} Pi 5 fan cooling for the next reboot: on at 50 C, off below 45 C, faster at 60, 67.5 and 75 C."


def configure(path: str | os.PathLike[str]) -> str:
    """Write the managed block into config.txt, keeping a backup of the old file."""

    target = Path(path)
    original = target.read_text(encoding="utf-8")
    updated, message = configured_text(original)
    if updated == original:
        return message
    backup = target.with_name(f"{target.name}.motionmodule-{time.strftime('%Y%m%d-%H%M%S')}.bak")
    shutil.copy2(target, backup)
    staging = target.with_name(f".{target.name}.motionmodule-new")
    staging.write_text(updated, encoding="utf-8", newline="")
    shutil.copymode(target, staging)
    os.replace(staging, target)
    return f"{message} The previous file is kept at {backup}."


# -- read-only status -------------------------------------------------------

def _read(path: Path) -> str | None:
    try:
        return path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return None


def _number(path: Path) -> int | None:
    text = _read(path)
    try:
        return int(text) if text is not None else None
    except ValueError:
        return None


def cooling_status(root: str | os.PathLike[str] = "/") -> dict:
    """CPU temperature and what the Pi's own fan control reports, read-only.

    A reading the kernel does not offer is None, never 0: a missing tachometer
    is not a stopped fan. ``state`` is the fan level the kernel has chosen
    (0 = off, 1-4 = the COOLING_LEVELS above) and ``rpm`` the measured speed
    when the kernel exposes the fan's tachometer.
    """

    base = Path(root)
    millidegrees = _number(base / "sys/class/thermal/thermal_zone0/temp")
    temperature = None if millidegrees is None else round(millidegrees / 1000, 1)
    status = {
        "temperature_c": temperature,
        "fan_found": False,
        "state": None,
        "max_state": None,
        "rpm": None,
        "pwm": None,
    }
    thermal = base / "sys/class/thermal"
    try:
        devices = sorted(thermal.glob("cooling_device*"))
    except OSError:
        devices = []
    for device in devices:
        if (_read(device / "type") or "").casefold() in {"pwm-fan", "pwmfan"}:
            status.update(
                fan_found=True,
                state=_number(device / "cur_state"),
                max_state=_number(device / "max_state"),
            )
            break
    try:
        monitors = sorted((base / "sys/class/hwmon").glob("hwmon*"))
    except OSError:
        monitors = []
    for monitor in monitors:
        if (_read(monitor / "name") or "").casefold() in {"pwmfan", "pwm_fan", "pwm-fan"}:
            status["fan_found"] = True
            status["rpm"] = _number(monitor / "fan1_input")
            status["pwm"] = _number(monitor / "pwm1")
            break
    status["summary"], status["level"] = _summary(status)
    return status


def _summary(status: dict) -> tuple[str, str]:
    """One plain sentence and ok / warn / unknown for the dashboard."""

    temperature = status["temperature_c"]
    heat = "CPU temperature unavailable" if temperature is None else f"CPU {temperature} °C"
    if not status["fan_found"]:
        return f"{heat}; the Pi reports no fan control (fan setting not active yet, or not a Pi 5).", "unknown"
    state, rpm = status["state"], status["rpm"]
    speed = "" if rpm is None else f", {rpm} RPM"
    if state is None:
        return f"{heat}; fan level unavailable{speed}.", "unknown"
    if state == 0:
        # Off below the start temperature is normal, not a fault.
        if temperature is not None and temperature >= COOLING_LEVELS[0][0] / 1000:
            return f"{heat}; the fan has not been asked to run yet{speed}.", "warn"
        return f"{heat}; fan off, as expected below 50 °C{speed}.", "ok"
    if rpm == 0:
        return (
            f"{heat}; fan asked to run (level {state}) but its speed sensor reads 0 RPM. "
            "With the Pi switched off, check the fan's plug in the FAN connector.",
            "warn",
        )
    level = f"level {state} of {status['max_state'] or len(COOLING_LEVELS)}"
    if rpm is None:
        return f"{heat}; fan set to {level} (no speed reading from the Pi).", "ok"
    return f"{heat}; fan running at {level}{speed}.", "ok"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Raspberry Pi 5 fan cooling for MotionModule")
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("configure", help="add or update the fan block in config.txt")
    setup.add_argument("config_txt", type=Path)
    commands.add_parser("status", help="show the CPU temperature and fan state")
    args = parser.parse_args(argv)
    if args.command == "configure":
        print(configure(args.config_txt))
    else:
        print(cooling_status()["summary"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
