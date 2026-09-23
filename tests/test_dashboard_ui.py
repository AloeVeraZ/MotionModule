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
            active_page="diagnostics",
            active_tab="mecanum",
            project_name="TestRobot",
        )
        dom = DashboardDOM()
        dom.feed(rendered)
        script = re.search(r"<script>(.*?)</script>", rendered, re.DOTALL).group(1)
        # Startup polling is driven explicitly by the tests so timing and
        # connection failures are deterministic. All production handlers run.
        script = script[:script.index("/* ------------------------------------------------------------ startup */")]
        hold_script = (ROOT / "core/motion_module/static/hold-controls.js").read_text(encoding="utf-8")
        script = hold_script + "\n" + script
        cls.fixture = {"nodes": dom.nodes, "script": script}

        station_template = ROOT / "core" / "motion_module" / "templates" / "driver_station.html"
        station_rendered = Environment().from_string(station_template.read_text(encoding="utf-8")).render(
            dashboard_token="ui-test-token",
            project_name="TestRobot",
        )
        station_dom = DashboardDOM()
        station_dom.feed(station_rendered)
        station_script = re.search(r"<script>(.*?)</script>", station_rendered, re.DOTALL).group(1)
        station_script = station_script[:station_script.rfind("renderKeys();")]
        sticks_script = (ROOT / "core/motion_module/static/touch-sticks.js").read_text(encoding="utf-8")
        station_script = hold_script + "\n" + sticks_script + "\n" + station_script
        cls.station_fixture = {"nodes": station_dom.nodes, "script": station_script, "kind": "station"}

    def run_behavior(self, scenario, fixture=None):
        result = subprocess.run(
            [NODE, str(ROOT / "tests" / "dashboard_ui_harness.js"), scenario],
            input=json.dumps(fixture or self.fixture),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=15,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_leaving_drive_page_disarms_and_stops_keyboard_commands(self):
        self.run_behavior("tab-disarm")

    def test_shared_themes_follow_system_and_work_with_blocked_storage(self):
        result = subprocess.run(
            [NODE, str(ROOT / "tests/appearance_ui_harness.js"),
             str(ROOT / "core/motion_module/static/motionmodule.js")],
            capture_output=True, text=True, timeout=15,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_touch_drive_hold_release_cancel_and_multitouch(self):
        for fixture in (self.fixture, self.station_fixture):
            with self.subTest(kind=fixture.get("kind", "debug")):
                self.run_behavior("touch-drive", fixture)

    def test_touch_stop_invalidates_old_fingers_and_requires_reenable(self):
        for fixture in (self.fixture, self.station_fixture):
            with self.subTest(kind=fixture.get("kind", "debug")):
                self.run_behavior("touch-stop", fixture)

    def test_broken_drive_test_shows_error_and_stays_disabled_after_status_refresh(self):
        self.run_behavior("drive-test-load-error")

    def test_releasing_a_drive_key_immediately_sends_zero(self):
        self.run_behavior("key-release-stop")

    def test_q_and_e_continuously_send_pure_rotation_to_the_builtin_test(self):
        self.run_behavior("rotation-held")

    def test_q_and_e_continuously_send_pure_rotation_to_the_full_station(self):
        self.run_behavior("rotation-held", self.station_fixture)

    def test_full_station_mixer_selection_stops_and_requires_reenabling(self):
        self.run_behavior("station-drive-model", self.station_fixture)

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

    def test_an_update_asks_for_the_sudo_password_only_when_sudo_wants_one(self):
        self.run_behavior("update-password")

    def test_full_station_renders_cameras_imu_pi_inputs_and_usb_controller(self):
        self.run_behavior("station-telemetry-layout", self.station_fixture)

    def test_a_touchscreen_drives_with_two_sticks_that_let_go_safely(self):
        self.run_behavior("station-touch-sticks", self.station_fixture)

    def test_dashboard_py_lays_out_the_sticks_panels_and_game_controller(self):
        self.run_behavior("station-stick-layout", self.station_fixture)

    def test_a_gamepad_buttons_default_stop_button_disables_the_robot(self):
        self.run_behavior("station-gamepad-buttons", self.station_fixture)

    def test_a_camera_can_be_rotated_by_slider_button_or_typed_angle(self):
        self.run_behavior("station-camera-rotation", self.station_fixture)


if __name__ == "__main__":
    unittest.main()
