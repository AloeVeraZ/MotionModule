"""Install the sensor bridge firmware on an Arduino GIGA R1 WiFi, from the Pi.

No Arduino IDE is involved. This does what the IDE's upload button does: it
asks the running sketch to restart into the GIGA's bootloader (opening its USB
serial port at 1200 baud and closing it again), writes the prebuilt
firmware/giga_sensor_bridge.bin with dfu-util, the same tool the IDE uses,
and waits for the board to come back running it.

    motionmodule giga flash      pauses the MotionModule service while it runs
    motionmodule giga status

The dashboard's Debug page runs the same steps from its Install firmware
button, pausing its own connection to the board.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable

from .errors import MotionModuleError
from .usb import usb_devices


FIRMWARE_DIRECTORY = Path(__file__).resolve().parents[2] / "firmware"
FIRMWARE_NAME = "giga_sensor_bridge"
GIGA_VENDOR_ID = "2341"
SKETCH_PRODUCT_ID = "0266"
BOOTLOADER_PRODUCT_ID = "0366"
# Where the GIGA's main (M7) core runs a sketch from, as the IDE uploads it.
FLASH_ADDRESS = "0x08040000"
MAX_FIRMWARE_BYTES = 1966080


def bundled_firmware(directory: Path = FIRMWARE_DIRECTORY) -> dict:
    """The prebuilt firmware shipped with this MotionModule, checked against its manifest."""

    manifest_path = directory / f"{FIRMWARE_NAME}.json"
    binary_path = directory / f"{FIRMWARE_NAME}.bin"
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        data = binary_path.read_bytes()
    except (OSError, ValueError) as error:
        raise MotionModuleError(f"The bundled GIGA firmware is missing or unreadable: {error}") from error
    if not 0 < len(data) <= MAX_FIRMWARE_BYTES or len(data) != manifest.get("bytes"):
        raise MotionModuleError("The bundled GIGA firmware has the wrong size; reinstall MotionModule")
    if hashlib.sha256(data).hexdigest() != manifest.get("sha256"):
        raise MotionModuleError("The bundled GIGA firmware does not match its checksum; reinstall MotionModule")
    return {
        "version": str(manifest.get("version", "")),
        "bytes": len(data),
        "sha256": manifest["sha256"],
        "path": str(binary_path),
        "flash_address": str(manifest.get("flash_address", FLASH_ADDRESS)),
    }


def find_boards(inventory: dict | None = None) -> list[dict]:
    """GIGA boards on the Pi's USB bus, whether running a sketch or in their bootloader."""

    source = inventory if inventory is not None else usb_devices()
    boards = []
    for device in source.get("devices", ()):
        if device.get("vendor_id") != GIGA_VENDOR_ID:
            continue
        product = device.get("product_id")
        if product not in {SKETCH_PRODUCT_ID, BOOTLOADER_PRODUCT_ID}:
            continue
        node = str(device.get("device_node", ""))
        boards.append({
            "mode": "bootloader" if product == BOOTLOADER_PRODUCT_ID else "sketch",
            "path": str(device.get("path", "")),
            "serial": str(device.get("serial", "")),
            "port": str(device.get("serial_port", "")),
            "device_node": node,
            "writable": bool(node) and os.access(node, os.R_OK | os.W_OK),
        })
    return boards


def enter_bootloader(port: str, serial_factory=None) -> None:
    """The Arduino 1200-baud touch: open the port at 1200 baud, then close it."""

    factory = serial_factory
    if factory is None:
        from serial import Serial as factory  # type: ignore[no-redef]
    handle = factory(port, 1200)
    handle.close()


def read_firmware_version(port: str, serial_factory=None, timeout: float = 4.0, clock=time.monotonic) -> str:
    """Ask the board which bridge firmware it runs. "" if it does not say."""

    factory = serial_factory
    if factory is None:
        from serial import Serial as factory  # type: ignore[no-redef]
    handle = factory(port, 115200, timeout=0.1, write_timeout=0.5)
    try:
        handle.write(b"MM2 HELLO\n")
        buffer = b""
        deadline = clock() + timeout
        while clock() < deadline:
            buffer += handle.read(256)
            *lines, buffer = buffer.split(b"\n")
            for line in lines:
                try:
                    payload = json.loads(line.decode("utf-8", errors="replace"))
                except ValueError:
                    continue
                if isinstance(payload, dict) and payload.get("firmware"):
                    return str(payload["firmware"])[:16]
    finally:
        handle.close()
    return ""


def _wait_for(predicate: Callable[[], dict | None], timeout: float, sleep, clock) -> dict | None:
    deadline = clock() + timeout
    while True:
        found = predicate()
        if found is not None or clock() >= deadline:
            return found
        sleep(0.25)


def flash_giga(
    *,
    log: Callable[[str], None] = print,
    inventory: Callable[[], dict] = usb_devices,
    run=subprocess.run,
    which: Callable[[str], str | None] = shutil.which,
    serial_factory=None,
    sleep=time.sleep,
    clock=time.monotonic,
    firmware_directory: Path = FIRMWARE_DIRECTORY,
) -> dict:
    """Write the bundled firmware to the one GIGA plugged into the Pi."""

    firmware = bundled_firmware(firmware_directory)
    tool = which("dfu-util")
    if not tool:
        raise MotionModuleError(
            "dfu-util is not installed. Rerun the MotionModule installer, or run: sudo apt install dfu-util"
        )
    boards = find_boards(inventory())
    if not boards:
        raise MotionModuleError(
            "No Arduino GIGA R1 WiFi is plugged into the Pi. Connect its USB-C port to a Pi USB port."
        )
    if len(boards) > 1:
        raise MotionModuleError("More than one GIGA is plugged in. Leave only the one to flash connected.")
    board = boards[0]

    if board["mode"] == "sketch":
        if not board["port"]:
            raise MotionModuleError(
                "The GIGA has no serial port to restart it through. Press its RESET button twice "
                "quickly, then run this again."
            )
        log(f"Restarting the GIGA on {board['port']} into its bootloader...")
        try:
            enter_bootloader(board["port"], serial_factory)
        except (ImportError, OSError, ValueError) as error:
            raise MotionModuleError(
                f"Could not open {board['port']} ({error}). If MotionModule is running, use "
                "motionmodule giga flash, which pauses it; otherwise press RESET twice and retry."
            ) from error

        def bootloader():
            return next((item for item in find_boards(inventory()) if item["mode"] == "bootloader"), None)

        board = _wait_for(bootloader, 10.0, sleep, clock)
        if board is None:
            raise MotionModuleError(
                "The GIGA did not enter its bootloader. Press its RESET button twice quickly "
                "(the green light pulses), then run this again."
            )
    else:
        log("The GIGA is already in its bootloader.")

    if board["device_node"] and not board["writable"]:
        raise MotionModuleError(
            f"No permission to write to the GIGA over USB ({board['device_node']}). The MotionModule "
            "installer adds a rule for this: rerun it, then unplug and replug the GIGA."
        )

    log(f"Writing firmware {firmware['version']} ({firmware['bytes'] // 1024} KB)...")
    command = [
        tool,
        "--device", f"0x{GIGA_VENDOR_ID}:0x{BOOTLOADER_PRODUCT_ID}",
        "-D", firmware["path"],
        "-a0",
        f"--dfuse-address={firmware['flash_address']}:leave",
    ]
    try:
        result = run(command, capture_output=True, text=True, timeout=180)
    except (OSError, subprocess.SubprocessError) as error:
        raise MotionModuleError(f"dfu-util could not run: {error}") from error
    output = f"{result.stdout or ''}\n{result.stderr or ''}"
    written = "Download done" in output or "File downloaded successfully" in output
    # The bootloader resets as it leaves, so dfu-util can report an error
    # after the write has finished. The written marker is what counts.
    if not written:
        tail = " ".join(line.strip() for line in output.strip().splitlines()[-4:])
        raise MotionModuleError(f"dfu-util did not write the firmware: {tail or 'no output'}")

    log("Written. Waiting for the GIGA to start it...")

    def running():
        return next((item for item in find_boards(inventory()) if item["mode"] == "sketch" and item["port"]), None)

    board = _wait_for(running, 15.0, sleep, clock)
    if board is None:
        raise MotionModuleError(
            "The firmware was written, but the GIGA did not come back. Press its RESET button once."
        )
    sleep(1.5)  # the serial port appears a moment before udev finishes its permissions
    version = ""
    try:
        version = read_firmware_version(board["port"], serial_factory, clock=clock)
    except (ImportError, OSError, ValueError):
        pass
    if version:
        log(f"The GIGA is running MotionModule sensor firmware {version}.")
    else:
        log("The GIGA restarted. Its firmware version will show in the Driver Station once MotionModule connects.")
    return {"version": version or firmware["version"], "verified": version == firmware["version"], "port": board["port"]}


def firmware_status(inventory: Callable[[], dict] = usb_devices, which=shutil.which) -> dict:
    try:
        bundled = bundled_firmware()
        problem = ""
    except MotionModuleError as error:
        bundled, problem = None, str(error)
    return {
        "bundled": bundled,
        "problem": problem,
        "dfu_util": bool(which("dfu-util")),
        "boards": find_boards(inventory()),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install MotionModule's sensor firmware on an Arduino GIGA R1 WiFi")
    parser.add_argument("command", nargs="?", default="status", choices=("status", "flash"))
    args = parser.parse_args(argv)
    if args.command == "status":
        status = firmware_status()
        bundled = status["bundled"]
        print(f"Bundled firmware: {bundled['version'] + ' (' + str(bundled['bytes'] // 1024) + ' KB)' if bundled else status['problem']}")
        print(f"dfu-util: {'installed' if status['dfu_util'] else 'missing (rerun the MotionModule installer)'}")
        if not status["boards"]:
            print("GIGA: not plugged in")
        for board in status["boards"]:
            where = board["port"] or board["device_node"] or board["path"]
            print(f"GIGA: {'bootloader, waiting for firmware' if board['mode'] == 'bootloader' else 'running'} at {where}")
        return 0
    try:
        result = flash_giga(log=print)
    except MotionModuleError as error:
        parser.exit(1, f"[MotionModule ERROR] {error}\n")
    print("Done." if result["verified"] else "Done. Replug the GIGA if MotionModule does not see it.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
