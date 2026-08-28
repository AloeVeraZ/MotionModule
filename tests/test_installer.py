import unittest
from pathlib import Path


INSTALLER = Path(__file__).resolve().parents[1] / "installer" / "install.sh"


class InstallerFinishTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = INSTALLER.read_text(encoding="utf-8")

    def test_doctor_runs_before_the_automatic_reboot(self):
        doctor = "/usr/local/bin/motionmodule doctor"
        reboot = "sudo systemctl reboot"
        self.assertIn(doctor, self.script)
        self.assertIn(reboot, self.script)
        self.assertLess(self.script.index(doctor), self.script.index(reboot))

    def test_pinout_link_is_the_final_printed_message(self):
        message = (
            "Check GitHub for the proper pinout before wiring the robot: "
            "https://github.com/AloeVeraZ/MotionModule/blob/main/docs/PINOUT.md"
        )
        self.assertIn(message, self.script)
        after_message = self.script.split(message, 1)[1]
        self.assertNotIn("printf ", after_message)
        self.assertNotIn("say ", after_message)

    def test_reboot_can_be_skipped_explicitly(self):
        self.assertIn("--no-reboot)", self.script)
        self.assertIn('if [ "$REBOOT_SYSTEM" = true ]', self.script)

    def test_dashboard_runs_from_versioned_runtime_and_nginx_exposes_port_80(self):
        self.assertIn("/usr/local/sbin/motionmodule-dashboard", self.script)
        launcher = (INSTALLER.parent / "dashboard_launcher").read_text(encoding="utf-8")
        self.assertIn("-m motion_module.dashboard --project", launcher)
        self.assertIn("-m motion_module.runner", launcher)
        self.assertIn("listen 80 default_server", self.script)
        self.assertIn("proxy_pass http://127.0.0.1:8080", self.script)
        self.assertIn("sudo nginx -t", self.script)
        self.assertIn("http://%s.local (or type the Pi IP directly)", self.script)


if __name__ == "__main__":
    unittest.main()
