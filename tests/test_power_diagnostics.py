"""Read-only Pi firmware flags: never pretend these measure battery current."""

import subprocess
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from motion_module.diagnostics import pi_power_check


class PowerDiagnosticsTests(unittest.TestCase):
    def report(self, output, code=0):
        with patch("motion_module.diagnostics.subprocess.run", return_value=SimpleNamespace(
            returncode=code, stdout=output,
        )) as run:
            result = pi_power_check(True)
        run.assert_called_once_with(
            ["vcgencmd", "get_throttled"], capture_output=True, text=True, timeout=1, check=False,
        )
        return result

    def test_simulation_never_runs_a_hardware_command(self):
        with patch("motion_module.diagnostics.subprocess.run") as run:
            report = pi_power_check(False)
        run.assert_not_called()
        self.assertEqual(report["level"], "info")
        self.assertIn("Simulation", report["detail"])

    def test_clean_flags_do_not_promise_brownout_protection(self):
        report = self.report("throttled=0x0\n")
        self.assertEqual(report["raw_flags"], "0x0")
        self.assertIn("cannot rule out abrupt power loss", report["detail"])
        self.assertIn("does not limit motor power", report["detail"])

    def test_current_undervoltage_is_distinct_from_history(self):
        report = self.report("throttled=0x1")
        self.assertEqual(report["level"], "warn")
        self.assertIn("undervoltage NOW", report["detail"])
        self.assertNotIn("undervoltage recorded", report["detail"])
        report = self.report("throttled=0x10000")
        self.assertIn("undervoltage recorded this boot", report["detail"])
        self.assertNotIn("undervoltage NOW", report["detail"])

    def test_all_documented_flags_are_decoded(self):
        report = self.report("throttled=0xF000F")
        self.assertEqual(report["level"], "warn")
        for phrase in ("undervoltage", "CPU frequency cap", "throttling", "soft temperature limit"):
            self.assertIn(phrase, report["detail"])
        self.assertIn("History resets on reboot", report["detail"])

    def test_throttling_is_not_mislabelled_as_undervoltage(self):
        report = self.report("throttled=0x40004")
        self.assertIn("throttling NOW", report["detail"])
        self.assertNotIn("undervoltage NOW", report["detail"])
        self.assertNotIn("undervoltage recorded", report["detail"])

    def test_unknown_flags_are_not_reported_as_clean(self):
        report = self.report("throttled=0x10")
        self.assertEqual(report["level"], "warn")
        self.assertIn("Unrecognized", report["detail"])

    def test_missing_failed_or_malformed_results_are_unavailable(self):
        for output, code in (("", 0), ("error", 0), ("throttled=0x0", 1)):
            report = self.report(output, code)
            self.assertIn("unavailable", report["detail"])
            self.assertNotIn("raw_flags", report)
        for error in (FileNotFoundError(), PermissionError(), subprocess.TimeoutExpired("vcgencmd", 1)):
            with patch("motion_module.diagnostics.subprocess.run", side_effect=error):
                report = pi_power_check(True)
            self.assertIn("unavailable", report["detail"])
            self.assertNotIn("raw_flags", report)
