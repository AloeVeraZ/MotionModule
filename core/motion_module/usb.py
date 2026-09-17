"""Read-only USB discovery shared by Debug and the Driver Station.

USB descriptors can identify a controller and its serial port.  They cannot
identify a sensor wired to one of that controller's pins, so sensor names and
pin modes stay in the robot project's ``sensors.py``.
"""

from __future__ import annotations

import os
from pathlib import Path


_GIGA = {
    "board_id": "arduino_giga_r1_wifi",
    "name": "Arduino GIGA R1 WiFi",
    "digital_pins": [f"D{number}" for number in range(76)],
    "analog_pins": [f"A{number}" for number in range(8)],
    "dac_pins": ["A12", "A13"],
    "adc_bits": 12,
}

USB_CONTROLLER_PROFILES = {
    # Arduino's GIGA variant declares 2341:0266 in pins_arduino.h. After a
    # 1200-baud touch, or two presses of reset, its bootloader answers as
    # 2341:0366 and waits for firmware.
    ("2341", "0266"): {**_GIGA, "transport": "USB CDC serial", "mode": "sketch"},
    ("2341", "0366"): {**_GIGA, "transport": "USB DFU bootloader", "mode": "bootloader"},
}


def _read(path: Path, *, maximum: int = 256) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:maximum].strip()
    except OSError:
        return ""


def _serial_ports(root: Path, device_name: str, dev_root: Path) -> list[str]:
    """Find tty devices exposed by every interface of one USB device."""

    names: set[str] = set()
    # The underscore form exists only to make a faithful fixture possible on
    # Windows, whose filesystem rejects the colon used by Linux USB sysfs.
    for pattern in (f"{device_name}:*/tty", f"{device_name}_*/tty"):
        for tty_root in root.glob(pattern):
            try:
                names.update(path.name for path in tty_root.iterdir() if path.name.startswith("tty"))
            except OSError:
                pass
    return [str(dev_root / name) for name in sorted(names)]


def _controller_profile(vendor: str, product: str) -> dict | None:
    profile = USB_CONTROLLER_PROFILES.get((vendor, product))
    return dict(profile) if profile else None


def usb_devices(
    sysfs_root: str | os.PathLike[str] = "/sys/bus/usb/devices",
    dev_root: str | os.PathLike[str] = "/dev/bus/usb",
    tty_root: str | os.PathLike[str] = "/dev",
) -> dict:
    """Return connected USB devices using Linux sysfs without probing or changing them."""

    root = Path(sysfs_root)
    device_root = Path(dev_root)
    serial_root = Path(tty_root)
    if not root.is_dir():
        return {"available": False, "devices": [], "error": "Linux USB inventory is unavailable"}

    devices: list[dict] = []
    try:
        candidates = sorted(root.iterdir(), key=lambda path: path.name)
    except OSError as error:
        return {"available": False, "devices": [], "error": str(error)}
    for candidate in candidates:
        vendor = _read(candidate / "idVendor").casefold()
        product_id = _read(candidate / "idProduct").casefold()
        if not vendor or not product_id:
            continue
        bus = _read(candidate / "busnum")
        device_number = _read(candidate / "devnum")
        node = device_root / bus.zfill(3) / device_number.zfill(3) if bus and device_number else None
        drivers: set[str] = set()
        for driver_link in [candidate / "driver", *root.glob(f"{candidate.name}:*/driver")]:
            try:
                drivers.add(driver_link.resolve(strict=True).name)
            except OSError:
                pass
        driver = ", ".join(sorted(drivers))
        device_class = _read(candidate / "bDeviceClass").casefold()
        if device_class == "09":
            kind = "USB hub"
        elif driver:
            kind = driver.replace("_", " ")
        else:
            kind = "USB device"
        if node and node.exists():
            permission = "ready" if os.access(node, os.R_OK | os.W_OK) else "limited"
        else:
            permission = "unknown"
        serial_ports = _serial_ports(root, candidate.name, serial_root)
        profile = _controller_profile(vendor.zfill(4), product_id.zfill(4))
        item = {
                "path": candidate.name,
                "vendor_id": vendor.zfill(4),
                "product_id": product_id.zfill(4),
                "manufacturer": _read(candidate / "manufacturer"),
                "product": _read(candidate / "product") or kind,
                "serial": _read(candidate / "serial"),
                "driver": driver,
                "kind": kind,
                "speed_mbps": _read(candidate / "speed"),
                "bus": int(bus) if bus.isdigit() else None,
                "device": int(device_number) if device_number.isdigit() else None,
                "device_node": str(node) if node else "",
                "permission": permission,
                "serial_ports": serial_ports,
                "serial_port": serial_ports[0] if serial_ports else "",
                "controller": profile,
            }
        devices.append(item)
    return {"available": True, "devices": devices, "error": ""}


def sensor_controllers(inventory: dict | None = None) -> list[dict]:
    """Return supported USB sensor controllers from an inventory snapshot."""

    source = inventory if inventory is not None else usb_devices()
    controllers: list[dict] = []
    for device in source.get("devices", ()):
        profile = device.get("controller")
        if not isinstance(profile, dict):
            continue
        port = str(device.get("serial_port", ""))
        permission = "unknown"
        if port:
            serial_node = Path(port)
            permission = "ready" if serial_node.exists() and os.access(
                serial_node, os.R_OK | os.W_OK
            ) else "limited"
        if profile.get("mode") == "bootloader":
            bridge = "bootloader"
            detail = (
                "The GIGA is in its bootloader, waiting for firmware. Run motionmodule giga flash, "
                "or press its reset button once to go back to the installed firmware."
            )
        else:
            bridge = "detected" if port else "serial-port-missing"
            detail = (
                "Board detected. Readings appear once the MotionModule firmware is installed "
                "(motionmodule giga flash) and the robot's sensors.py declares what is wired to it."
            )
        controllers.append({
            **profile,
            "id": f"{profile['board_id']}:{device.get('serial') or device.get('path')}",
            "connected": True,
            "vendor_id": device.get("vendor_id", ""),
            "product_id": device.get("product_id", ""),
            "serial": device.get("serial", ""),
            "port": port,
            "permission": permission,
            "bridge": bridge,
            "pins": [],
            "detail": detail,
        })
    return controllers
