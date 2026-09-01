#!/usr/bin/env python3
"""Constrained NetworkManager helper for MotionModule.

This file is installed root-owned at /usr/local/sbin/motionmodule-network. The
web application may invoke only its fixed subcommands through sudo; no shell
commands or caller-provided file paths are accepted.
"""

from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import socket
import subprocess
import sys
import tempfile
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

try:
    import fcntl
except ImportError:  # pragma: no cover - lets validation tests import this Linux helper on Windows
    fcntl = None


CONFIG_PATH = Path(os.environ.get("MOTIONMODULE_NETWORK_CONFIG", "/etc/motionmodule/network.json"))
LOCK_PATH = Path(os.environ.get("MOTIONMODULE_NETWORK_LOCK", "/run/motionmodule-network.lock"))
HOSTS_PATH = Path(os.environ.get("MOTIONMODULE_HOSTS_PATH", "/etc/hosts"))
HOTSPOT_PROFILE = "MotionModule-Hotspot"
DEFAULT_CONFIG = {
    "schema_version": 1,
    "preferred_uuid": "",
    "hotspot_ssid": "MotionModule",
    "hotspot_password": "motionrobot",
    "last_message": "",
    "last_error": "",
}


class NetworkError(RuntimeError):
    pass


def _split_terse(line: str) -> list[str]:
    """Split nmcli -t output while respecting its backslash escaping."""

    fields: list[str] = []
    current: list[str] = []
    escaped = False
    for character in line.rstrip("\n"):
        if escaped:
            current.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(character)
    if escaped:
        current.append("\\")
    fields.append("".join(current))
    return fields


def _clean_text(value: object, label: str, *, maximum: int = 256) -> str:
    text = str(value or "").strip()
    if not text:
        raise NetworkError(f"{label} is required")
    if "\x00" in text or "\n" in text or "\r" in text:
        raise NetworkError(f"{label} contains unsupported characters")
    if len(text) > maximum:
        raise NetworkError(f"{label} is too long")
    return text


def _validate_ssid(value: object) -> str:
    ssid = _clean_text(value, "Wi-Fi name", maximum=128)
    if len(ssid.encode("utf-8")) > 32:
        raise NetworkError("Wi-Fi names may contain at most 32 bytes")
    return ssid


def _validate_password(value: object, label: str = "Wi-Fi password") -> str:
    password = _clean_text(value, label, maximum=63)
    if not 8 <= len(password) <= 63:
        raise NetworkError(f"{label} must contain 8-63 characters")
    return password


def _validate_domain(value: object) -> str:
    domain = _clean_text(value, "Authentication server domain", maximum=253).casefold()
    if not re.fullmatch(r"(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z0-9][a-z0-9-]{0,62}", domain):
        raise NetworkError("Authentication server domain must be a full DNS name")
    return domain


def _validate_hostname(value: object) -> str:
    """Return a safe single-label hostname suitable for Linux and mDNS."""

    hostname = _clean_text(value, "Hostname", maximum=69).casefold()
    if hostname.endswith(".local"):
        hostname = hostname[:-6]
    if hostname == "localhost" or not re.fullmatch(
        r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", hostname
    ):
        raise NetworkError(
            "Hostname must contain 1-63 letters, numbers, or hyphens; it cannot start or end with a hyphen"
        )
    return hostname


class NetworkManager:
    def __init__(self, runner: Callable | None = None, sleep: Callable = time.sleep) -> None:
        self._runner = runner or subprocess.run
        self._sleep = sleep

    def run(self, command: list[str], *, timeout: int = 15, check: bool = True) -> subprocess.CompletedProcess:
        try:
            result = self._runner(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise NetworkError(f"Could not run {command[0]}: {error}") from error
        if check and result.returncode != 0:
            detail = (result.stderr or result.stdout or "command failed").strip()
            raise NetworkError(detail[:500])
        return result

    def nmcli(self, *arguments: str, timeout: int = 15, check: bool = True):
        return self.run(["nmcli", "--terse", "--escape", "yes", *arguments], timeout=timeout, check=check)

    def wifi_interface(self) -> str:
        output = self.nmcli("--fields", "DEVICE,TYPE", "device", "status").stdout
        for line in output.splitlines():
            fields = _split_terse(line)
            if len(fields) >= 2 and fields[1] == "wifi":
                return fields[0]
        raise NetworkError("No managed Wi-Fi interface was found")

    def _device_details(self, interface: str) -> dict:
        output = self.nmcli(
            "--fields",
            "GENERAL.STATE,GENERAL.CONNECTION,GENERAL.CON-UUID",
            "device",
            "show",
            interface,
        ).stdout
        details = {"state": "", "connection": "", "uuid": ""}
        mapping = {
            "GENERAL.STATE": "state",
            "GENERAL.CONNECTION": "connection",
            "GENERAL.CON-UUID": "uuid",
        }
        for line in output.splitlines():
            fields = _split_terse(line)
            if len(fields) >= 2 and fields[0] in mapping:
                details[mapping[fields[0]]] = fields[1]
        return details

    def _connection_mode(self, uuid: str) -> str:
        if not uuid or uuid == "--":
            return ""
        result = self.nmcli(
            "--get-values", "802-11-wireless.mode", "connection", "show", "uuid", uuid, check=False
        )
        return result.stdout.strip() if result.returncode == 0 else ""

    def scan(self, *, rescan: bool = True) -> list[dict]:
        interface = self.wifi_interface()
        output = self.nmcli(
            "--fields",
            "IN-USE,SSID,SIGNAL,SECURITY",
            "device",
            "wifi",
            "list",
            "ifname",
            interface,
            "--rescan",
            "yes" if rescan else "no",
            timeout=25,
        ).stdout
        networks: dict[str, dict] = {}
        for line in output.splitlines():
            fields = _split_terse(line)
            if len(fields) < 4 or not fields[1]:
                continue
            in_use, ssid, signal_text, security = fields[:4]
            try:
                signal = max(0, min(100, int(signal_text)))
            except ValueError:
                signal = 0
            kind = self.security_kind(security)
            candidate = {
                "ssid": ssid,
                "signal": signal,
                "security": security or "Open",
                "security_kind": kind,
                "connected": in_use == "*",
                "supported": kind in {"open", "personal", "enterprise"},
            }
            previous = networks.get(ssid)
            if (
                previous is None
                or (candidate["connected"] and not previous["connected"])
                or (candidate["connected"] == previous["connected"] and candidate["signal"] > previous["signal"])
            ):
                networks[ssid] = candidate
        return sorted(networks.values(), key=lambda item: (not item["connected"], -item["signal"], item["ssid"].casefold()))

    @staticmethod
    def security_kind(security: str) -> str:
        normalized = (security or "").upper()
        if not normalized or normalized in {"--", "OPEN"}:
            return "open"
        if "802.1X" in normalized or "WPA-EAP" in normalized:
            return "enterprise"
        if "WPA3" in normalized and "WPA2" not in normalized:
            return "unsupported"
        if "WPA" in normalized and "PSK" in normalized:
            return "personal"
        if "WPA" in normalized:
            return "personal"
        return "unsupported"

    def addresses(self) -> list[dict]:
        result = self.run(["ip", "-j", "-4", "address", "show", "up"], check=False)
        if result.returncode != 0:
            return []
        try:
            interfaces = json.loads(result.stdout)
        except json.JSONDecodeError:
            return []
        addresses = []
        for interface in interfaces:
            name = interface.get("ifname", "")
            if name == "lo":
                continue
            for info in interface.get("addr_info", []):
                address = info.get("local", "")
                try:
                    parsed = ipaddress.ip_address(address)
                except ValueError:
                    continue
                if parsed.version == 4 and not parsed.is_loopback:
                    addresses.append({"interface": name, "address": address})
        return addresses

    def service_active(self, unit: str) -> bool:
        result = self.run(["systemctl", "is-active", unit], timeout=5, check=False)
        return result.returncode == 0 and result.stdout.strip() == "active"

    def status(self) -> dict:
        config = load_config()
        hostname = socket.gethostname()
        try:
            interface = self.wifi_interface()
            details = self._device_details(interface)
            mode_value = self._connection_mode(details["uuid"])
            if mode_value == "ap" or details["connection"] == HOTSPOT_PROFILE:
                mode = "hotspot"
            elif details["state"].startswith("100") and mode_value in {"", "infrastructure"}:
                mode = "client"
            else:
                mode = "disconnected"
            visible = self.scan(rescan=False)
            active = next((item for item in visible if item["connected"]), None)
            ssid = active["ssid"] if active else (
                config["hotspot_ssid"] if mode == "hotspot" else details["connection"]
            )
            wifi = {
                "available": True,
                "interface": interface,
                "mode": mode,
                "ssid": ssid if ssid != "--" else "",
                "connection": details["connection"] if details["connection"] != "--" else "",
            }
        except NetworkError as error:
            wifi = {
                "available": False,
                "interface": "",
                "mode": "unavailable",
                "ssid": "",
                "connection": "",
                "error": str(error),
            }
        return {
            "wifi": wifi,
            "addresses": self.addresses(),
            "services": {
                "ssh": self.service_active("ssh.service"),
                "mdns": self.service_active("avahi-daemon.service"),
            },
            "hostname": hostname,
            "local_url": f"http://{hostname}.local",
            "hotspot_url": "http://10.42.0.1",
            "hotspot_ssid": config["hotspot_ssid"],
            "last_message": config.get("last_message", ""),
            "last_error": config.get("last_error", ""),
        }

    def initialize(self) -> dict:
        _require_root()
        config = load_config()
        try:
            interface = self.wifi_interface()
            details = self._device_details(interface)
            mode = self._connection_mode(details["uuid"])
            if details["state"].startswith("100") and mode != "ap" and details["uuid"] != "--":
                config["preferred_uuid"] = details["uuid"]
                config["last_message"] = "Saved the current Raspberry Pi Imager Wi-Fi as preferred."
                config["last_error"] = ""
        except NetworkError as error:
            config["last_error"] = f"Initial Wi-Fi capture: {error}"
        save_config(config)
        return self.status()

    def change_hostname(self, payload: dict) -> dict:
        """Change the Pi hostname without accepting arbitrary commands or paths."""

        _require_root()
        hostname = _validate_hostname(payload.get("hostname"))
        old_hostname = socket.gethostname()
        self.run(["hostnamectl", "set-hostname", hostname])
        try:
            self._update_hosts(hostname)
        except OSError as error:
            # Avoid leaving hostnamectl and /etc/hosts disagreeing if the
            # filesystem unexpectedly rejects the atomic hosts update.
            self.run(["hostnamectl", "set-hostname", old_hostname], check=False)
            raise NetworkError(f"Could not update {HOSTS_PATH}: {error}") from error
        self.run(["systemctl", "try-restart", "avahi-daemon.service"], check=False)
        config = load_config()
        config["last_message"] = (
            f"Hostname changed to {hostname}. Use {hostname}.local for the dashboard and SSH."
        )
        config["last_error"] = ""
        save_config(config)
        result = self.status()
        # Test runners and some containers do not update socket.gethostname()
        # immediately even though hostnamectl succeeded.
        result["hostname"] = hostname
        result["local_url"] = f"http://{hostname}.local"
        return result

    @staticmethod
    def _update_hosts(hostname: str) -> None:
        try:
            lines = HOSTS_PATH.read_text(encoding="utf-8").splitlines()
        except FileNotFoundError:
            lines = []
        replacement = f"127.0.1.1\t{hostname}"
        replaced = False
        updated: list[str] = []
        for line in lines:
            fields = line.split()
            if not replaced and fields and fields[0] == "127.0.1.1":
                updated.append(replacement)
                replaced = True
            else:
                updated.append(line)
        if not replaced:
            updated.append(replacement)
        HOSTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        temporary = HOSTS_PATH.with_name(f"{HOSTS_PATH.name}.tmp.{os.getpid()}")
        temporary.write_text("\n".join(updated) + "\n", encoding="utf-8")
        os.chmod(temporary, 0o644)
        os.replace(temporary, HOSTS_PATH)

    def _profile_name(self, ssid: str) -> str:
        digest = hashlib.sha256(ssid.encode("utf-8")).hexdigest()[:10]
        return f"MotionModule-WiFi-{digest}"

    def _delete_profile(self, profile: str) -> None:
        self.nmcli("connection", "delete", "id", profile, check=False)

    @contextmanager
    def _password_file(self, setting: str, secret: str):
        handle = tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", prefix="motionmodule-secret-", dir="/run", delete=False
        )
        try:
            os.chmod(handle.name, 0o600)
            handle.write(f"{setting}:{secret}\n")
            handle.flush()
            handle.close()
            yield handle.name
        finally:
            try:
                os.unlink(handle.name)
            except FileNotFoundError:
                pass

    def start_hotspot(self, payload: dict | None = None) -> dict:
        _require_root()
        config = load_config()
        payload = payload or {}
        ssid = _validate_ssid(payload.get("ssid", config["hotspot_ssid"]))
        password = _validate_password(
            payload.get("password", config["hotspot_password"]), "Hotspot password"
        )
        with network_lock():
            self._start_hotspot_unlocked(config, ssid, password)
        return self.status()

    def _start_hotspot_unlocked(self, config: dict, ssid: str, password: str) -> None:
        interface = self.wifi_interface()
        self._delete_profile(HOTSPOT_PROFILE)
        self.nmcli(
            "connection", "add", "type", "wifi", "ifname", interface,
            "con-name", HOTSPOT_PROFILE, "ssid", ssid,
        )
        try:
            self.nmcli(
                "connection", "modify", "id", HOTSPOT_PROFILE,
                "connection.autoconnect", "no",
                "connection.autoconnect-priority", "-999",
                "802-11-wireless.mode", "ap",
                "802-11-wireless.band", "bg",
                "ipv4.method", "shared",
                "ipv4.addresses", "10.42.0.1/24",
                "ipv6.method", "disabled",
                "802-11-wireless-security.key-mgmt", "wpa-psk",
            )
            with self._password_file("802-11-wireless-security.psk", password) as secret_file:
                self.nmcli(
                    "--wait", "25", "connection", "up", "id", HOTSPOT_PROFILE,
                    "ifname", interface, "passwd-file", secret_file, timeout=30,
                )
        except NetworkError:
            self._delete_profile(HOTSPOT_PROFILE)
            raise
        config["hotspot_ssid"] = ssid
        config["hotspot_password"] = password
        config["last_message"] = f"Hotspot {ssid} is active at 10.42.0.1."
        config["last_error"] = ""
        save_config(config)

    def connect(self, payload: dict) -> dict:
        _require_root()
        ssid = _validate_ssid(payload.get("ssid"))
        security_kind = str(payload.get("security_kind", "personal"))
        if security_kind not in {"open", "personal", "enterprise"}:
            raise NetworkError("This Wi-Fi security type is not supported by the web setup")
        password = ""
        username = ""
        domain = ""
        if security_kind == "personal":
            password = _validate_password(payload.get("password"))
        elif security_kind == "enterprise":
            username = _clean_text(payload.get("username"), "Enterprise username")
            password = _clean_text(payload.get("password"), "Enterprise password", maximum=256)
            domain = _validate_domain(payload.get("domain"))

        profile = self._profile_name(ssid)
        config = load_config()
        failure: NetworkError | None = None
        with network_lock():
            interface = self.wifi_interface()
            self._delete_profile(profile)
            self.nmcli(
                "connection", "add", "type", "wifi", "ifname", interface,
                "con-name", profile, "ssid", ssid,
            )
            try:
                common = (
                    "connection", "modify", "id", profile,
                    "connection.autoconnect", "yes",
                    "connection.autoconnect-priority", "100",
                    "connection.autoconnect-retries", "0",
                    "ipv4.method", "auto",
                    "ipv6.method", "auto",
                )
                self.nmcli(*common)
                secret_setting = ""
                if security_kind == "personal":
                    self.nmcli(
                        "connection", "modify", "id", profile,
                        "802-11-wireless-security.key-mgmt", "wpa-psk",
                    )
                    secret_setting = "802-11-wireless-security.psk"
                elif security_kind == "enterprise":
                    self.nmcli(
                        "connection", "modify", "id", profile,
                        "802-11-wireless-security.key-mgmt", "wpa-eap",
                        "802-1x.eap", "peap",
                        "802-1x.identity", username,
                        "802-1x.phase2-auth", "mschapv2",
                        "802-1x.system-ca-certs", "yes",
                        "802-1x.domain-suffix-match", domain,
                    )
                    secret_setting = "802-1x.password"
                self.nmcli("connection", "down", "id", HOTSPOT_PROFILE, check=False)
                if secret_setting:
                    with self._password_file(secret_setting, password) as secret_file:
                        self.nmcli(
                            "--wait", "35", "connection", "up", "id", profile,
                            "ifname", interface, "passwd-file", secret_file, timeout=40,
                        )
                else:
                    self.nmcli(
                        "--wait", "35", "connection", "up", "id", profile,
                        "ifname", interface, timeout=40,
                    )
            except NetworkError as error:
                self._delete_profile(profile)
                config["last_error"] = f"Could not connect to {ssid}: {error}"
                config["last_message"] = ""
                save_config(config)
                failure = error
            if failure is None:
                details = self._device_details(interface)
                config["preferred_uuid"] = details["uuid"] if details["uuid"] != "--" else ""
                config["last_message"] = f"Connected to {ssid}."
                config["last_error"] = ""
                save_config(config)
        if failure is not None:
            try:
                self.start_hotspot()
            except NetworkError:
                pass
            raise failure
        return self.status()

    def activate_preferred(self) -> dict:
        _require_root()
        config = load_config()
        preferred = str(config.get("preferred_uuid", "")).strip()
        if not preferred:
            raise NetworkError("No preferred Wi-Fi has been saved yet")
        failure: NetworkError | None = None
        with network_lock():
            interface = self.wifi_interface()
            self.nmcli("connection", "down", "id", HOTSPOT_PROFILE, check=False)
            try:
                self.nmcli(
                    "--wait", "35", "connection", "up", "uuid", preferred,
                    "ifname", interface, timeout=40,
                )
            except NetworkError as error:
                config["last_error"] = f"Could not reconnect to preferred Wi-Fi: {error}"
                config["last_message"] = ""
                save_config(config)
                failure = error
            if failure is None:
                details = self._device_details(interface)
                config["last_message"] = f"Connected to {details['connection']}."
                config["last_error"] = ""
                save_config(config)
        if failure is not None:
            try:
                self.start_hotspot()
            except NetworkError:
                pass
            raise failure
        return self.status()

    def watch(self, timeout_seconds: int = 30) -> None:
        _require_root()
        deadline = time.monotonic() + timeout_seconds
        next_preferred_attempt = 0.0
        while True:
            try:
                status = self.status()
                mode = status["wifi"]["mode"]
                if mode == "hotspot":
                    deadline = time.monotonic() + timeout_seconds
                elif mode == "client":
                    deadline = time.monotonic() + timeout_seconds
                else:
                    config = load_config()
                    preferred = config.get("preferred_uuid", "")
                    now = time.monotonic()
                    if now >= deadline:
                        try:
                            self.start_hotspot()
                        except NetworkError as error:
                            config["last_error"] = f"Automatic hotspot failed: {error}"
                            save_config(config)
                            deadline = time.monotonic() + timeout_seconds
                    elif preferred and now >= next_preferred_attempt:
                        interface = self.wifi_interface()
                        self.nmcli(
                            "--wait", "5", "connection", "up", "uuid", preferred,
                            "ifname", interface, timeout=8, check=False,
                        )
                        # Keep retrying during the 30-second window without
                        # hammering NetworkManager between connection attempts.
                        next_preferred_attempt = time.monotonic() + 2
            except NetworkError as error:
                config = load_config()
                config["last_error"] = f"Network monitor: {error}"
                save_config(config)
            self._sleep(2)


def load_config() -> dict:
    config = dict(DEFAULT_CONFIG)
    try:
        saved = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        if isinstance(saved, dict):
            for key in config:
                if key in saved:
                    config[key] = saved[key]
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return config


def save_config(config: dict) -> None:
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    temporary = CONFIG_PATH.with_name(f"{CONFIG_PATH.name}.tmp.{os.getpid()}")
    temporary.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    os.chmod(temporary, 0o600)
    os.replace(temporary, CONFIG_PATH)


@contextmanager
def network_lock():
    LOCK_PATH.parent.mkdir(parents=True, exist_ok=True)
    with LOCK_PATH.open("a+", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _require_root() -> None:
    if getattr(os, "geteuid", lambda: 0)() != 0:
        raise NetworkError("This network operation must run as root")


def read_payload() -> dict:
    if sys.stdin.isatty():
        return {}
    try:
        payload = json.load(sys.stdin)
    except json.JSONDecodeError as error:
        raise NetworkError(f"Invalid request data: {error}") from error
    if not isinstance(payload, dict):
        raise NetworkError("Request data must be a JSON object")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="MotionModule NetworkManager helper")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("status")
    subparsers.add_parser("scan")
    subparsers.add_parser("init")
    subparsers.add_parser("hotspot")
    subparsers.add_parser("connect")
    subparsers.add_parser("preferred")
    subparsers.add_parser("hostname")
    watch_parser = subparsers.add_parser("watch")
    watch_parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args(argv)
    manager = NetworkManager()
    try:
        if args.command == "status":
            result = manager.status()
        elif args.command == "scan":
            result = {"networks": manager.scan(rescan=True)}
        elif args.command == "init":
            result = manager.initialize()
        elif args.command == "hotspot":
            result = manager.start_hotspot(read_payload())
        elif args.command == "connect":
            result = manager.connect(read_payload())
        elif args.command == "preferred":
            result = manager.activate_preferred()
        elif args.command == "hostname":
            result = manager.change_hostname(read_payload())
        else:
            if not 5 <= args.timeout <= 300:
                raise NetworkError("Failover timeout must be 5-300 seconds")
            manager.watch(args.timeout)
            return 0
        print(json.dumps({"ok": True, **result}))
        return 0
    except NetworkError as error:
        print(json.dumps({"ok": False, "error": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
