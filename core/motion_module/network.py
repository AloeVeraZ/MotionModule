"""Unprivileged client for the constrained MotionModule network helper."""

from __future__ import annotations

import json
import os
import subprocess

from .errors import MotionModuleError


class NetworkClient:
    def __init__(self, helper: str | None = None, runner=None) -> None:
        self.helper = helper or os.environ.get(
            "MOTIONMODULE_NETWORK_HELPER", "/usr/local/sbin/motionmodule-network"
        )
        self._runner = runner or subprocess.run

    def _call(self, command: str, payload: dict | None = None, timeout: int = 50) -> dict:
        try:
            result = self._runner(
                ["sudo", "-n", self.helper, command],
                input=json.dumps(payload) if payload is not None else None,
                capture_output=True,
                text=True,
                timeout=timeout,
                check=False,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise MotionModuleError(f"Network helper is unavailable: {error}") from error
        output = (result.stdout or "").strip().splitlines()
        try:
            response = json.loads(output[-1]) if output else {}
        except json.JSONDecodeError as error:
            detail = (result.stderr or result.stdout or "invalid helper response").strip()
            raise MotionModuleError(f"Network helper failed: {detail[:300]}") from error
        if result.returncode != 0 or not response.get("ok"):
            raise MotionModuleError(str(response.get("error") or "Network operation failed"))
        return response

    def status(self) -> dict:
        return self._call("status", timeout=10)

    def scan(self) -> list[dict]:
        return self._call("scan", timeout=30).get("networks", [])

    def start_hotspot(self, payload: dict) -> dict:
        return self._call("hotspot", payload, timeout=40)

    def connect(self, payload: dict) -> dict:
        return self._call("connect", payload, timeout=55)

    def activate_preferred(self) -> dict:
        return self._call("preferred", timeout=55)

    def change_hostname(self, payload: dict) -> dict:
        return self._call("hostname", payload, timeout=20)
