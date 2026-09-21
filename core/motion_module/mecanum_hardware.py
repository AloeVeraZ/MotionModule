"""Give legacy Mecanum projects their requested B-output polarity.

Older robot folders have robot.py but no hardware.py, so updating the sample
does not change their installed, separately preserved motor configuration.
Create the missing project file from that configuration, with only channels
2 and 4 inverted. Existing project files and the installed source are never
overwritten. This runs during installation, before the service restarts.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from pathlib import Path

from .config import default_config, hardware_source, load_config


def provision_mecanum_hardware(project: Path, installed_hardware: Path) -> str | None:
    project = project.resolve()
    target = project / "hardware.py"
    if project.name != "Mecanum" or not (project / "robot.py").is_file():
        return None
    if target.exists() or target.is_symlink():
        return None

    original = load_config(installed_hardware)
    # This is only for the shipped reference wiring. A differently wired
    # robot remains entirely under its owner's control.
    def pins(config):
        return {
            motor.channel: (motor.forward_gpio, motor.reverse_gpio)
            for motor in config.motors
        }

    if pins(original) != pins(default_config()):
        return f"Kept {project}: its installed wiring differs from the reference Mecanum map."

    corrected = replace(original, motors=tuple(
        replace(motor, inverted=True) if motor.channel in (2, 4) else motor
        for motor in original.motors
    ))
    content = hardware_source(corrected)
    # Exclusive creation preserves a file another process may have added
    # since the initial check. A later install leaves this file alone.
    with target.open("x", encoding="utf-8", newline="\n") as output:
        output.write(content)
    return (
        f"Created {target} from {installed_hardware}: Driver 1B and 2B use inverted "
        "polarity in Test outputs and Drive. Kept all other settings, motor names, "
        "pins, robot code, and the original installed hardware file."
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("project", type=Path)
    parser.add_argument("installed_hardware", type=Path)
    args = parser.parse_args(argv)
    message = provision_mecanum_hardware(args.project, args.installed_hardware)
    if message:
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
