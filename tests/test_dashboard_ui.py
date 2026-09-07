"""Exercise dashboard control behavior without a browser or connected hardware."""

import json
import re
import shutil
import subprocess
import unittest
from html.parser import HTMLParser
from pathlib import Path

from jinja2 import Environment


ROOT = Path(__file__).resolve().parents[1]
NODE = shutil.which("node")


class DashboardDOM(HTMLParser):
    """Keep the real template's controls and hierarchy for the Node DOM fixture."""

    VOID_ELEMENTS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input", "link",
        "meta", "param", "source", "track", "wbr",
    }

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.nodes = []
        self.stack = []

    def handle_starttag(self, tag, attrs):
        index = len(self.nodes)
        self.nodes.append({
            "tag": tag,
            "attrs": dict(attrs),
            "parent": self.stack[-1] if self.stack else None,
            "text": "",
        })
        if tag not in self.VOID_ELEMENTS:
            self.stack.append(index)

    def handle_endtag(self, tag):
        for index in range(len(self.stack) - 1, -1, -1):
            if self.nodes[self.stack[index]]["tag"] == tag:
                del self.stack[index:]
                return

    def handle_data(self, text):
        if self.stack:
            self.nodes[self.stack[-1]]["text"] += text


@unittest.skipUnless(NODE, "Node.js is required for dashboard JavaScript behavior tests")
class DashboardUIBehaviorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        template = ROOT / "core" / "motion_module" / "templates" / "dashboard.html"
        rendered = Environment().from_string(template.read_text(encoding="utf-8")).render(
            dashboard_token="ui-test-token",
            active_page="drive",
            active_tab="",
            project_name="TestRobot",
        )
        dom = DashboardDOM()
        dom.feed(rendered)
        script = re.search(r"<script>(.*?)</script>", rendered, re.DOTALL).group(1)
        # Startup polling is driven explicitly by the tests so timing and
        # connection failures are deterministic. All production handlers run.
        script = script[:script.index("/* ------------------------------------------------------------ startup */")]
        cls.fixture = {"nodes": dom.nodes, "script": script}

    def run_behavior(self, scenario):
        result = subprocess.run(
            [NODE, str(ROOT / "tests" / "dashboard_ui_harness.js"), scenario],
            input=json.dumps(self.fixture),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_leaving_drive_page_disarms_and_stops_keyboard_commands(self):
        self.run_behavior("tab-disarm")

    def test_releasing_a_drive_key_immediately_sends_zero(self):
        self.run_behavior("key-release-stop")

    def test_a_disconnected_servo_board_is_red_and_explained(self):
        self.run_behavior("servo-offline")

    def test_a_servo_board_rejecting_commands_is_yellow(self):
        self.run_behavior("servo-command-fault")

    def test_stop_disarms_and_key_repeat_cannot_restart_motors(self):
        self.run_behavior("stop-disarm")

    def test_connection_loss_marks_unknown_outputs_and_requires_rearming(self):
        self.run_behavior("connection-error")

    def test_rejected_drive_command_disarms_and_surfaces_error(self):
        self.run_behavior("drive-error")

    def test_reloaded_page_sends_sequences_newer_than_previous_page(self):
        self.run_behavior("reload-sequence")


if __name__ == "__main__":
    unittest.main()
