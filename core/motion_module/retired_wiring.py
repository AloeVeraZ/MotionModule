"""Move pin maps left on the retired wiring onto the robot's locked wiring.

Every pin map MotionModule shipped until 6 September 2026 put the motors on
other pins: front_left on GPIO12 and GPIO6, rear_left on GPIO19 and GPIO16,
and so on. The robot has since been rewired to the locked wiring in AGENTS.md
and docs/PINOUT.md. An install keeps the robot folders and the installed pin
map it finds, though, so a Pi set up before then went on driving, and drawing,
the old pins.

The installer runs this on every install. A hardware.py whose motors sit
exactly on the retired pins is a copy an earlier release left behind, not
wiring anyone chose, so it is replaced with the pin map this release ships for
it and the old file is kept beside it. A pin map with any other pins belongs to
its robot and is never changed.

    python -m motion_module.retired_wiring ROBOTS_DIRECTORY INSTALLED_HARDWARE_FILE
"""

from __future__ import annotations

import argparse
import os
import shutil
import uuid
from pathlib import Path

from .config import DEFAULT_HARDWARE_PATH, PROJECT_CONFIG_NAME, load_hardware_file
from .errors import MotionModuleError


# channel: (forward GPIO, reverse GPIO) in every pin map shipped before the
# robot was rewired. This is only for recognising those copies. Nothing is
# wired this way any more, and no pin map may use these pins again.
RETIRED_MOTOR_GPIOS = {
    1: (12, 6),
    2: (19, 16),
    3: (20, 21),
    4: (26, 13),
    5: (5, 25),
    6: (9, 11),
    7: (8, 7),
    8: (23, 24),
}
EXAMPLES_DIRECTORY = Path(__file__).resolve().parents[2] / "examples"
BACKUP_SUFFIX = ".retired-wiring"


def on_retired_wiring(path: str | os.PathLike[str]) -> bool:
    """True when this hardware.py drives exactly the retired motor pins."""

    config = load_hardware_file(path)
    motors = {motor.channel: (motor.forward_gpio, motor.reverse_gpio) for motor in config.motors}
    return motors == RETIRED_MOTOR_GPIOS


def _replace(path: Path, shipped: Path) -> Path:
    """Put ``shipped`` where ``path`` is and return where the old file was kept."""

    backup = path.with_name(path.name + BACKUP_SUFFIX)
    number = 1
    while backup.exists():
        backup = path.with_name(f"{path.name}{BACKUP_SUFFIX}.{number}")
        number += 1
    shutil.copy2(path, backup)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}")
    try:
        shutil.copyfile(shipped, temporary)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return backup


def replace_retired_pin_maps(
    robots_directory: str | os.PathLike[str],
    installed_hardware: str | os.PathLike[str],
) -> list[str]:
    """Replace every pin map still on the retired wiring and say what changed.

    A robot folder gets the hardware.py of the shipped example it is named
    after; the installed pin map gets the built-in one. A robot folder with no
    matching example is reported instead, because its wheel names could not be
    kept. A pin map that does not load is not a copy an earlier release left,
    so it is skipped.
    """

    robots = Path(robots_directory)
    candidates = [
        (hardware, EXAMPLES_DIRECTORY / hardware.parent.name / PROJECT_CONFIG_NAME)
        for hardware in sorted(robots.glob(f"*/{PROJECT_CONFIG_NAME}"))
        if not hardware.parent.name.startswith(".")
    ]
    candidates.append((Path(installed_hardware), DEFAULT_HARDWARE_PATH))

    messages = []
    for path, shipped in candidates:
        try:
            if not path.is_file() or not on_retired_wiring(path):
                continue
        except (MotionModuleError, OSError):
            continue
        if not shipped.is_file():
            messages.append(
                f"{path} still has the motor pins from before the robot was rewired. "
                "Copy the pins from docs/PINOUT.md into it before driving."
            )
            continue
        try:
            backup = _replace(path, shipped)
        except OSError as error:
            messages.append(f"Could not move {path} onto the robot's wiring: {error}")
            continue
        messages.append(
            f"Moved {path} onto the robot's wiring in docs/PINOUT.md. It still had the "
            f"motor pins from before the robot was rewired; that copy is kept as {backup.name}. "
            "Every motor now starts uninverted: test each wheel with the robot raised before driving."
        )
    return messages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Move pin maps left on the retired wiring onto the robot's locked wiring"
    )
    parser.add_argument("robots_directory", type=Path)
    parser.add_argument("installed_hardware", type=Path)
    args = parser.parse_args(argv)
    for message in replace_retired_pin_maps(args.robots_directory, args.installed_hardware):
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
