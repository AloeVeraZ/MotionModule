"""Non-moving checks shared by the dashboard and command-line doctor."""

from __future__ import annotations

from pathlib import Path

from .pinout import motor_rows


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
            checks.append(
                {
                    "id": f"servo-{board['index']}",
                    "level": "pass" if board.get("available") else "warn",
                    "title": f"PCA9685 board {board['index']} · {board['address']}",
                    "detail": "Responding on the I2C bus." if board.get("available") else f"No response: {board.get('error') or 'board not detected'}",
                }
            )
    return checks
