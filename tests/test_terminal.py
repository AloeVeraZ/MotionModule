import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from motion_module.errors import MotionModuleError
from motion_module.terminal import TerminalManager, TerminalSession


class TerminalManagerTests(unittest.TestCase):
    def write_access(self, path, *, code="abc123", expires_offset=60, boot_id="test-boot"):
        path.write_text(
            json.dumps(
                {
                    "code": code,
                    "expires_at": time.time() + expires_offset,
                    "boot_id": boot_id,
                }
            ),
            encoding="utf-8",
        )

    def test_access_grant_must_match_boot_and_expiration(self):
        with tempfile.TemporaryDirectory() as directory:
            access = Path(directory) / "terminal.json"
            self.write_access(access)
            manager = TerminalManager(
                access_path=access,
                shell_path=str(Path(directory) / "missing-bash"),
                boot_id="test-boot",
            )
            status = manager.status()
            self.assertTrue(status["enabled"])
            self.assertFalse(status["available"])

            wrong_boot = TerminalManager(access_path=access, boot_id="another-boot")
            self.assertFalse(wrong_boot.status()["enabled"])
            self.write_access(access, expires_offset=-1)
            self.assertFalse(manager.status()["enabled"])

    def test_pty_master_descriptor_is_closed_exactly_once(self):
        session = TerminalSession.__new__(TerminalSession)
        session._lock = threading.RLock()
        session._master_fd = 123
        with patch("motion_module.terminal.os.close") as close:
            session._close_master()
            session._close_master()
        close.assert_called_once_with(123)
        self.assertIsNone(session._master_fd)

    @unittest.skipUnless(os.name == "posix" and Path("/bin/bash").is_file(), "Linux Bash required")
    def test_real_pty_shell_streams_output_and_checks_session_token(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            access = root / "terminal.json"
            self.write_access(access)
            manager = TerminalManager(
                access_path=access,
                shell_path="/bin/bash",
                idle_seconds=10,
                boot_id="test-boot",
            )
            with self.assertRaisesRegex(MotionModuleError, "Invalid terminal access code"):
                manager.start("wrong", root)
            started = manager.start("abc123", root)
            token = started["token"]
            with self.assertRaisesRegex(MotionModuleError, "Invalid terminal session"):
                manager.write("wrong-token", "echo unsafe\n")
            manager.write(token, "printf 'terminal-test-ok\\n'\n")
            cursor = 0
            combined = ""
            deadline = time.monotonic() + 3
            while "terminal-test-ok" not in combined and time.monotonic() < deadline:
                result = manager.read(token, cursor)
                combined += result["output"]
                cursor = result["cursor"]
                time.sleep(0.05)
            self.assertIn("terminal-test-ok", combined)
            manager.stop(token)
            self.assertFalse(manager.status()["active"])


if __name__ == "__main__":
    unittest.main()
