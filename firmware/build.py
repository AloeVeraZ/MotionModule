"""Rebuild giga_sensor_bridge.bin from the sketch beside it.

The Pi never compiles firmware: it flashes this committed binary. After
changing the sketch, rebuild on any computer that has arduino-cli (the Arduino
IDE 2 includes one) with the "Arduino Mbed OS Giga Boards" core installed:

    python firmware/build.py
    python firmware/build.py --cli PATH/TO/arduino-cli --config-file PATH/TO/arduino-cli.yaml

It writes giga_sensor_bridge.bin and giga_sensor_bridge.json, the manifest
MotionModule checks before flashing. The tests fail until both match the sketch.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


HERE = Path(__file__).resolve().parent
SKETCH = HERE / "giga_sensor_bridge"
FQBN = "arduino:mbed_giga:giga"
CORE = "arduino:mbed_giga"


def source_hash(text: str) -> str:
    return hashlib.sha256(text.replace("\r\n", "\n").encode("utf-8")).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--cli", default=shutil.which("arduino-cli") or "arduino-cli", help="arduino-cli to use")
    parser.add_argument("--config-file", help="arduino-cli configuration file, if not the default")
    args = parser.parse_args(argv)

    source = (SKETCH / "giga_sensor_bridge.ino").read_text(encoding="utf-8")
    match = re.search(r'const char BRIDGE_VERSION\[\] = "([0-9.]+)";', source)
    if not match:
        parser.error("BRIDGE_VERSION was not found in the sketch")
    base = [args.cli] + (["--config-file", args.config_file] if args.config_file else [])

    platforms = json.loads(subprocess.run(
        base + ["core", "list", "--json"], check=True, capture_output=True, text=True,
    ).stdout)
    platforms = platforms.get("platforms", platforms) if isinstance(platforms, dict) else platforms
    core = next((item for item in platforms if item.get("id") == CORE), None)
    if core is None:
        parser.error(f"Install the {CORE} core first: arduino-cli core install {CORE}")
    core_version = core.get("installed_version") or core.get("installed") or ""

    with tempfile.TemporaryDirectory() as directory:
        subprocess.run(
            base + ["compile", "--fqbn", FQBN, "--warnings", "all", "--output-dir", directory, str(SKETCH)],
            check=True,
        )
        data = (Path(directory) / "giga_sensor_bridge.ino.bin").read_bytes()

    (HERE / "giga_sensor_bridge.bin").write_bytes(data)
    manifest = {
        "board": "arduino_giga_r1_wifi",
        "fqbn": FQBN,
        "core": f"{CORE}@{core_version}",
        "version": match.group(1),
        "flash_address": "0x08040000",
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
        "source_sha256": source_hash(source),
    }
    (HERE / "giga_sensor_bridge.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Built firmware {manifest['version']}: {len(data)} bytes, sha256 {manifest['sha256'][:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
