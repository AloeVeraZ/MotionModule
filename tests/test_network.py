import importlib.util
import json
import subprocess
import unittest
from pathlib import Path
from unittest.mock import patch

from motion_module.errors import MotionModuleError
from motion_module.network import NetworkClient


HELPER_PATH = Path(__file__).resolve().parents[1] / "installer" / "network_manager.py"
SPEC = importlib.util.spec_from_file_location("motionmodule_network_helper", HELPER_PATH)
network_helper = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(network_helper)


class NetworkHelperTests(unittest.TestCase):
    def test_terse_parser_preserves_escaped_colons_and_backslashes(self):
        self.assertEqual(
            network_helper._split_terse(r"*:Robotics\:Lab\\Main:82:WPA2 PSK"),
            ["*", "Robotics:Lab\\Main", "82", "WPA2 PSK"],
        )

    def test_security_classification(self):
        classify = network_helper.NetworkManager.security_kind
        self.assertEqual(classify("--"), "open")
        self.assertEqual(classify("WPA2 PSK"), "personal")
        self.assertEqual(classify("WPA2 802.1X"), "enterprise")
        self.assertEqual(classify("WPA3 SAE"), "unsupported")
        self.assertEqual(classify("WEP"), "unsupported")

    def test_scan_deduplicates_by_ssid_and_keeps_strongest_signal(self):
        def runner(command, **_kwargs):
            if command[-2:] == ["device", "status"]:
                output = "wlan0:wifi\neth0:ethernet\n"
            elif "wifi" in command and "list" in command:
                output = "*:Workshop:52:WPA2 PSK\n:Workshop:88:WPA2 PSK\n:Guest:64:--\n"
            else:
                raise AssertionError(command)
            return subprocess.CompletedProcess(command, 0, output, "")

        networks = network_helper.NetworkManager(runner=runner).scan()
        self.assertEqual([item["ssid"] for item in networks], ["Workshop", "Guest"])
        self.assertTrue(networks[0]["connected"])
        self.assertEqual(networks[0]["signal"], 52)
        self.assertEqual(networks[1]["security_kind"], "open")

    def test_validation_rejects_unsafe_or_ambiguous_values(self):
        with self.assertRaises(network_helper.NetworkError):
            network_helper._validate_ssid("x" * 33)
        with self.assertRaises(network_helper.NetworkError):
            network_helper._validate_password("short")
        with self.assertRaises(network_helper.NetworkError):
            network_helper._validate_domain("not a full domain")

    def test_monitor_retries_preferred_network_then_starts_hotspot_at_deadline(self):
        class StopWatch(Exception):
            pass

        class WatchManager(network_helper.NetworkManager):
            def __init__(self, sleep):
                super().__init__(sleep=sleep)
                self.attempts = 0

            def status(self):
                return {"wifi": {"mode": "disconnected"}}

            def wifi_interface(self):
                return "wlan0"

            def nmcli(self, *arguments, **_kwargs):
                self.attempts += 1
                return subprocess.CompletedProcess(arguments, 1, "", "not found")

            def start_hotspot(self, payload=None):
                raise StopWatch

        clock = [0.0]

        def sleep(seconds):
            clock[0] += seconds

        manager = WatchManager(sleep)
        with (
            patch.object(network_helper, "_require_root"),
            patch.object(network_helper, "load_config", return_value={"preferred_uuid": "saved-uuid"}),
            patch.object(network_helper.time, "monotonic", side_effect=lambda: clock[0]),
            self.assertRaises(StopWatch),
        ):
            manager.watch(timeout_seconds=30)

        self.assertGreater(manager.attempts, 1)
        self.assertEqual(clock[0], 30)


class NetworkClientTests(unittest.TestCase):
    def test_client_sends_json_to_fixed_helper_subcommand(self):
        calls = []

        def runner(command, **kwargs):
            calls.append((command, kwargs))
            response = {"ok": True, "wifi": {"mode": "hotspot"}}
            return subprocess.CompletedProcess(command, 0, json.dumps(response), "")

        client = NetworkClient(helper="/fixed/helper", runner=runner)
        response = client.start_hotspot({"ssid": "Robot", "password": "safe-pass"})
        self.assertEqual(response["wifi"]["mode"], "hotspot")
        self.assertEqual(calls[0][0], ["sudo", "-n", "/fixed/helper", "hotspot"])
        self.assertEqual(json.loads(calls[0][1]["input"])["ssid"], "Robot")
        self.assertNotIn("safe-pass", calls[0][0])

    def test_client_surfaces_structured_helper_error(self):
        def runner(command, **_kwargs):
            return subprocess.CompletedProcess(command, 1, '{"ok": false, "error": "no adapter"}', "")

        with self.assertRaisesRegex(MotionModuleError, "no adapter"):
            NetworkClient(helper="/fixed/helper", runner=runner).scan()


if __name__ == "__main__":
    unittest.main()
