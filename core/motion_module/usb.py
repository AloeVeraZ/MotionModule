"""Read-only USB device discovery for the Debug dashboard."""

from __future__ import annotations

import os
from pathlib import Path


def _read(path: Path, *, maximum: int = 256) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")[:maximum].strip()
    except OSError:
        return ""


def usb_devices(
    sysfs_root: str | os.PathLike[str] = "/sys/bus/usb/devices",
    dev_root: str | os.PathLike[str] = "/dev/bus/usb",
) -> dict:
    """Return connected USB devices using Linux sysfs without probing or changing them."""

    root = Path(sysfs_root)
    device_root = Path(dev_root)
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
        devices.append(
            {
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
            }
        )
    return {"available": True, "devices": devices, "error": ""}
