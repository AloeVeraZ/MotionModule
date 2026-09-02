import unittest
from pathlib import Path


INSTALLER = Path(__file__).resolve().parents[1] / "installer" / "install.sh"
BOOTSTRAP = Path(__file__).resolve().parents[1] / "install.sh"


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

    def test_release_tests_run_from_release_root(self):
        self.assertIn('cd "$release_dir"', self.script)
        self.assertIn('./.venv/bin/python -m unittest discover -s tests -v', self.script)

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
        self.assertIn("client_max_body_size 12m", self.script)
        self.assertIn("Environment=MOTIONMODULE_ACTIVE_PROJECT=$PROJECT_DIR/active", self.script)
        self.assertIn("Restart=always", self.script)

    def test_first_install_assigns_hostname_through_constrained_helper(self):
        self.assertIn('TARGET_HOSTNAME="motionmodule"', self.script)
        self.assertIn("motionmodule-network hostname", self.script)
        self.assertNotIn('sudo hostnamectl set-hostname "$TARGET_HOSTNAME"', self.script)

    def test_root_bootstrap_enters_the_root_system_installer(self):
        bootstrap = BOOTSTRAP.read_text(encoding="utf-8")
        self.assertIn('${BASH_SOURCE[0]:-}', bootstrap)
        self.assertIn("installer/install.sh", bootstrap)
        self.assertIn('--source "$script_dir"', bootstrap)
        self.assertIn('--source "$temporary/source"', bootstrap)

    def test_robot_projects_are_discovered_and_selected_through_active_symlink(self):
        self.assertIn('--robot)', self.script)
        self.assertIn('for robot_file in "$release_dir"/examples/*/robot.py', self.script)
        self.assertIn('ROBOT_DIR="${MOTIONMODULE_ROBOT_DIR:-$PROJECT_DIR/robots}"', self.script)
        self.assertIn('mv "$old_robot_template" "$ROBOT_DIR/$old_robot_name"', self.script)
        self.assertIn('ACTIVE_LINK="$PROJECT_DIR/active"', self.script)
        self.assertIn('WorkingDirectory=$PROJECT_DIR/active', self.script)
        manager = (INSTALLER.parent / "motionmodule").read_text(encoding="utf-8")
        self.assertIn('project)', manager)
        self.assertIn('motionmodule project [list|PROJECT_NAME]', manager)
        self.assertIn('for robot_file in "$ROBOT_DIR"/*/robot.py', manager)
        self.assertIn('mv -Tf "$PROJECT_DIR/active.new.$$" "$PROJECT_DIR/active"', manager)
        self.assertIn('examples/$ROBOT_PROJECT/hardware.py', self.script)

    def test_launcher_recognizes_new_core_layout_and_older_releases(self):
        launcher = (INSTALLER.parent / "dashboard_launcher").read_text(encoding="utf-8")
        self.assertIn("core/motion_module/dashboard.py", launcher)
        self.assertIn("runtime/motion_module/dashboard.py", launcher)

    def test_manager_creates_time_limited_boot_scoped_terminal_access(self):
        manager = (INSTALLER.parent / "motionmodule").read_text(encoding="utf-8")
        self.assertIn("terminal enable [MINUTES]", manager)
        self.assertIn("terminal-access.json", manager)
        self.assertIn("/proc/sys/kernel/random/boot_id", manager)
        self.assertIn("chmod 0600", manager)
        self.assertIn('rm -f -- "$TERMINAL_ACCESS_FILE"', manager)
        self.assertIn('minutes" -le 120', manager)

    def test_local_push_is_validated_activated_and_restarted(self):
        manager = (INSTALLER.parent / "motionmodule").read_text(encoding="utf-8")
        self.assertIn('deploy)', manager)
        self.assertIn('-m motion_module.deploy', manager)
        self.assertIn('"$upload_root"/*.tar.gz', manager)
        self.assertIn('mv -Tf "$PROJECT_DIR/active.new.$$" "$PROJECT_DIR/active"', manager)
        self.assertIn("systemctl is-active --quiet motionmodule.service", manager)
        self.assertIn("The uploaded code is now running", manager)
        self.assertIn("restart motionmodule.service", self.script)

    def test_installed_readme_teaches_browser_folder_deployment(self):
        self.assertIn("Open the dashboard Code page", self.script)
        self.assertIn("hardware.py", self.script)
        self.assertIn("directly through the robot website", self.script)
        self.assertNotIn("VS Code", self.script)


if __name__ == "__main__":
    unittest.main()
