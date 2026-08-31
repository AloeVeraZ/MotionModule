import unittest
from pathlib import Path


INSTALLER = Path(__file__).resolve().parents[1] / "installer" / "install.sh"
BOOTSTRAP = Path(__file__).resolve().parents[2] / "install.sh"


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
            "https://github.com/AloeVeraZ/MotionModule/blob/main/MotionModule/docs/PINOUT.md"
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

    def test_root_bootstrap_enters_the_central_system_folder(self):
        bootstrap = BOOTSTRAP.read_text(encoding="utf-8")
        self.assertIn("MotionModule/installer/install.sh", bootstrap)
        self.assertIn('--source "$script_dir/MotionModule"', bootstrap)
        self.assertIn('--source "$temporary/source/MotionModule"', bootstrap)

    def test_robot_projects_are_discovered_and_selected_through_active_symlink(self):
        self.assertIn('--robot)', self.script)
        self.assertIn('for robot_file in "$release_dir"/*/robot.py', self.script)
        self.assertIn('ACTIVE_LINK="$PROJECT_DIR/active"', self.script)
        self.assertIn('WorkingDirectory=$PROJECT_DIR/active', self.script)
        manager = (INSTALLER.parent / "motionmodule").read_text(encoding="utf-8")
        self.assertIn('project)', manager)
        self.assertIn('motionmodule project [list|PROJECT_NAME]', manager)
        self.assertIn('mv -Tf "$PROJECT_DIR/active.new.$$" "$PROJECT_DIR/active"', manager)

    def test_launcher_recognizes_new_core_layout_and_older_releases(self):
        launcher = (INSTALLER.parent / "dashboard_launcher").read_text(encoding="utf-8")
        self.assertIn("core/motion_module/dashboard.py", launcher)
        self.assertIn("runtime/motion_module/dashboard.py", launcher)


if __name__ == "__main__":
    unittest.main()
