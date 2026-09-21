import os
import re
import shlex
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path


INSTALLER = Path(__file__).resolve().parents[1] / "installer" / "install.sh"
BOOTSTRAP = Path(__file__).resolve().parents[1] / "install.sh"
CLEANUP = INSTALLER.parent / "runtime_cleanup.sh"
UPDATE_HELPER = INSTALLER.parent / "update.sh"


def usable_bash():
    """A bash with GNU readlink, as on the Pi; None where there is none."""

    bash = shutil.which("bash")
    if not bash:
        return None
    try:
        probe = subprocess.run(
            [bash, "-c", "readlink -f ."], capture_output=True, text=True, timeout=10, check=False
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return bash if probe.returncode == 0 and probe.stdout.strip() else None


BASH = usable_bash()


def run_cleanup(commands):
    """Run commands with installer/runtime_cleanup.sh loaded, as install.sh does."""

    helpers = CLEANUP.read_text(encoding="utf-8").replace("\r\n", "\n")
    return subprocess.run(
        [BASH, "-s"],
        input=f"set -Eeuo pipefail\n{helpers}\n{commands}\n",
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=30,
        check=False,
    )


def make_release(releases, name, ref, complete=True):
    release = releases / name
    release.mkdir(parents=True)
    if complete:
        (release / ".complete").touch()
    (release / "INSTALL_REF").write_text(f"{ref}\n", encoding="utf-8")
    return release


def bash_path(path):
    return shlex.quote(Path(path).as_posix())


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

    def test_an_old_dashboard_helper_cannot_skip_its_successful_update_reboot(self):
        self.assertIn("motionmodule-update\\.service$", self.script)
        migration = self.script.index("Dashboard helpers shipped before automatic update reboots")
        options_done = self.script.index("\nsay()", migration)
        self.assertIn('REBOOT_SYSTEM=true', self.script[migration:options_done])

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

    def test_install_replaces_older_software_only_after_the_new_release_runs(self):
        self.assertIn('. "$SOURCE_DIR/installer/runtime_cleanup.sh"', self.script)
        restart = self.script.index("if ! sudo systemctl restart motionmodule.service; then")
        confirmed = self.script.index("new_release_running=true")
        purge = self.script.index('remove_other_releases "$RELEASES_DIR" "$release_dir" "$keep_release"')
        doctor = self.script.index("/usr/local/bin/motionmodule doctor")
        self.assertLess(restart, confirmed)
        self.assertLess(confirmed, purge)
        self.assertLess(purge, doctor)
        # Until the new release is seen running, the one it replaced stays.
        self.assertIn('keep_release="$old_target"', self.script)

    def test_every_system_file_is_recorded_for_the_stale_file_sweep(self):
        # The only direct install is inside install_system_file, which records
        # the destination; anything else would be swept as stale.
        self.assertEqual(self.script.count("sudo install -m"), 1)
        self.assertIn('installed_system_files+=("$3")', self.script)
        self.assertIn("installed_system_files+=(/etc/nginx/sites-enabled/motionmodule)", self.script)
        self.assertIn('| unlisted_paths "${installed_system_files[@]}"', self.script)
        sweep = self.script.index('| unlisted_paths "${installed_system_files[@]}"')
        self.assertLess(self.script.index("/etc/systemd/system/motionmodule.service"), sweep)
        self.assertLess(sweep, self.script.index("sudo systemctl daemon-reload"))

    def test_installer_never_deletes_robot_files_or_settings(self):
        protected = ("ROBOT_DIR", "backups", "CONFIG_FILE", "config.toml", "hardware.py", "network.json")
        for line in self.script.splitlines():
            if re.search(r"(^|[\s;&|(])rm\s", line):
                for name in protected:
                    self.assertNotIn(name, line, line)

    @unittest.skipUnless(BASH, "bash with GNU readlink is required to run the cleanup rules")
    def test_switching_branches_removes_the_other_branch_and_keeps_robot_files(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            releases = root / "releases"
            make_release(releases, "main-1", "main")
            running = make_release(releases, "main-2", "main")
            make_release(releases, "testing-1", "testing")
            make_release(releases, "unfinished", "main", complete=False)
            new = make_release(releases, "testing-2", "testing")
            robot = root / "MotionModule" / "robots" / "Mecanum"
            robot.mkdir(parents=True)
            (robot / "robot.py").write_text("# student code\n", encoding="utf-8")

            result = run_cleanup(
                f'keep="$(rollback_candidate {bash_path(running)} testing)"\n'
                '[ -z "$keep" ]\n'
                f'remove_other_releases {bash_path(releases)} {bash_path(new)} "$keep"\n'
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(sorted(result.stdout.split()), ["main-1", "main-2", "testing-1", "unfinished"])
            self.assertEqual([path.name for path in releases.iterdir()], ["testing-2"])
            self.assertEqual((robot / "robot.py").read_text(encoding="utf-8"), "# student code\n")

    @unittest.skipUnless(BASH, "bash with GNU readlink is required to run the cleanup rules")
    def test_updating_the_same_branch_keeps_the_release_it_replaced_for_rollback(self):
        with tempfile.TemporaryDirectory() as directory:
            releases = Path(directory) / "releases"
            make_release(releases, "main-1", "main")
            running = make_release(releases, "main-2", "main")
            make_release(releases, "testing-1", "testing")
            new = make_release(releases, "main-3", "main")

            result = run_cleanup(
                f'keep="$(rollback_candidate {bash_path(running)} main)"\n'
                f'[ "$keep" = {bash_path(running)} ]\n'
                f'remove_other_releases {bash_path(releases)} {bash_path(new)} "$keep"\n'
            )

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertEqual(sorted(result.stdout.split()), ["main-1", "testing-1"])
            self.assertEqual(sorted(path.name for path in releases.iterdir()), ["main-2", "main-3"])

    @unittest.skipUnless(BASH, "bash with GNU readlink is required to run the cleanup rules")
    def test_release_cleanup_never_follows_a_link_out_of_the_releases_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            releases = root / "releases"
            releases.mkdir()
            robot = root / "robots" / "Mecanum"
            robot.mkdir(parents=True)
            (robot / "robot.py").write_text("# student code\n", encoding="utf-8")
            try:
                os.symlink(root / "robots", releases / "escape", target_is_directory=True)
            except OSError:
                self.skipTest("this system cannot create symbolic links")

            result = run_cleanup(f"remove_other_releases {bash_path(releases)}\n")

            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue((robot / "robot.py").is_file())

    @unittest.skipUnless(BASH, "bash with GNU readlink is required to run the cleanup rules")
    def test_stale_file_sweep_lists_only_files_this_install_did_not_write(self):
        result = run_cleanup(
            "printf '%s\\n' /usr/local/sbin/motionmodule-network /usr/local/sbin/motionmodule-legacy "
            "/etc/systemd/system/motionmodule.service /etc/systemd/system/motionmodule-camera.service "
            "| unlisted_paths /usr/local/sbin/motionmodule-network /etc/systemd/system/motionmodule.service\n"
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(
            result.stdout.split(),
            ["/usr/local/sbin/motionmodule-legacy", "/etc/systemd/system/motionmodule-camera.service"],
        )

    def test_pi_is_ready_to_read_and_flash_the_giga(self):
        self.assertRegex(self.script, r"\n    dfu-util \\\n")
        self.assertIn("for group in gpio i2c dialout plugdev; do", self.script)
        self.assertIn("install_system_file 0644 \"$udev_temp\" /etc/udev/rules.d/motionmodule-giga.rules", self.script)
        self.assertIn('ATTRS{idVendor}=="2341", ATTRS{idProduct}=="0266|0366", MODE="0660", GROUP="plugdev"', self.script)
        # The rule is swept like every other file an install writes.
        sweep = self.script.index('| unlisted_paths "${installed_system_files[@]}"')
        self.assertIn("/etc/udev/rules.d", self.script[self.script.index("sudo find /usr/local/sbin"):sweep])
        self.assertLess(self.script.index("motionmodule-giga.rules"), sweep)

    def test_manager_flashes_the_giga_with_the_service_paused(self):
        manager = (INSTALLER.parent / "motionmodule").read_text(encoding="utf-8")
        flash = manager[manager.index("    giga)"):manager.index("    terminal)")]
        self.assertIn("-m motion_module.giga_firmware flash", flash)
        stop = flash.index("sudo systemctl stop motionmodule.service")
        run = flash.index("-m motion_module.giga_firmware flash")
        start = flash.index("sudo systemctl start motionmodule.service")
        self.assertLess(stop, run)
        self.assertLess(run, start)
        self.assertIn('exit "$flash_status"', flash)
        self.assertIn("giga status | giga flash", manager)

    def test_release_records_the_commit_the_dashboard_compares_with_github(self):
        commit = self.script.index('release_commit="$(git -C "$SOURCE_DIR" rev-parse HEAD')
        copied = self.script.index('cp -a "$SOURCE_DIR/." "$release_dir/"')
        self.assertLess(commit, copied)  # .git is removed from the release
        self.assertIn('"$release_commit" > "$release_dir/INSTALL_COMMIT"', self.script)

    def test_dashboard_can_install_a_branch_through_one_restricted_helper(self):
        self.assertIn('install_system_file 0755 "$release_dir/installer/update.sh" /usr/local/sbin/motionmodule-update',
                      self.script)
        self.assertIn("NOPASSWD: /usr/local/sbin/motionmodule-update main", self.script)
        self.assertIn("NOPASSWD: /usr/local/sbin/motionmodule-update testing", self.script)
        self.assertIn('install_system_file 0440 "$update_sudoers_temp" /etc/sudoers.d/motionmodule-update',
                      self.script)
        self.assertIn("visudo -cf \"$update_sudoers_temp\"", self.script)

        helper = (INSTALLER.parent / "update.sh").read_text(encoding="utf-8")
        # Only the two branches, and only ever one argument.
        self.assertIn("main|testing) ;;", helper)
        self.assertIn('[ "$#" -eq 1 ]', helper)
        # The update outlives the restart of the service that started it and
        # keeps the installer's default successful-install reboot enabled.
        self.assertIn("systemd-run", helper)
        self.assertIn('--uid="$OWNER"', helper)
        self.assertIn('/usr/local/bin/motionmodule install "$REF" >/dev/null', helper)
        self.assertNotIn('install "$REF" --no-reboot', helper)
        self.assertIn("/var/log/motionmodule-update.log", helper)

    def test_manager_installs_each_branch_through_its_own_bootstrap(self):
        manager = (INSTALLER.parent / "motionmodule").read_text(encoding="utf-8")
        self.assertIn('"$RAW_BASE/$ref/install.sh"', manager)
        self.assertIn('"$RAW_BASE/main/install.sh"', manager)
        self.assertIn('bash -s -- --version "$ref" "$@"', manager)
        self.assertIn("No earlier release of this branch is kept on the Pi", manager)

    def test_an_update_gets_the_sudo_password_only_through_the_helper(self):
        self.assertIn(
            'install_system_file 0755 "$release_dir/installer/askpass.sh" /usr/local/sbin/motionmodule-askpass',
            self.script,
        )
        self.assertIn("NOPASSWD: /usr/local/sbin/motionmodule-update password", self.script)
        # All three rules go through the same visudo check before installing.
        rules = self.script[self.script.index('update_sudoers_temp="$(mktemp)"'):
                            self.script.index('visudo -cf "$update_sudoers_temp"')]
        self.assertEqual(rules.count('>> "$update_sudoers_temp"'), 2)
        self.assertIn("motionmodule-update password", rules)
        askpass = (INSTALLER.parent / "askpass.sh").read_text(encoding="utf-8")
        self.assertIn("exec sudo -n /usr/local/sbin/motionmodule-update password", askpass)


# Stand-ins for what the update helper calls on a Pi. Each logs what it was
# asked, so the tests can see what reached systemd.
HELPER_STUBS = {
    "id": "echo 0\n",
    "getent": 'echo "aloe:x:1000:1000:Aloe:/home/aloe:/bin/bash"\n',
    "sleep": "exit 0\n",
    "systemctl": (
        'printf "%s\\n" "$*" >> "$STUBS/systemctl.log"\n'
        'case "$1" in\n'
        '    is-active) [ -f "$STUBS/update-active" ] ;;\n'
        '    show)\n'
        '        state="$(head -n 1 "$STUBS/states" 2>/dev/null || true)"\n'
        '        [ ! -f "$STUBS/states" ] || sed -i 1d "$STUBS/states"\n'
        '        echo "${state:-inactive}"\n'
        '        ;;\n'
        'esac\n'
    ),
    "systemd-run": (
        'printf "%s\\n" "$@" "@@" >> "$STUBS/systemd-run.log"\n'
        'case " $* " in\n'
        '    *" --unit=motionmodule-update "*) cat "$SECRET_FILE" > "$STUBS/secret-at-start" 2>/dev/null || true ;;\n'
        'esac\n'
        '[ ! -f "$STUBS/systemd-run-fails" ]\n'
    ),
}


@unittest.skipUnless(BASH, "bash with GNU readlink is required to run the update helper")
class UpdateHelperTests(unittest.TestCase):
    """installer/update.sh, run as it is on the Pi but against stand-ins for systemd."""

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.root = Path(directory.name)
        self.stubs = self.root / "stubs"
        self.stubs.mkdir()
        for name, body in HELPER_STUBS.items():
            stub = self.stubs / name
            stub.write_text("#!/bin/sh\n" + body, encoding="utf-8", newline="\n")
            stub.chmod(0o755)
        self.secret_dir = self.root / "run"
        self.secret = self.secret_dir / "sudo-password"
        self.cgroup = self.root / "cgroup"
        self.in_cgroup("motionmodule.service")
        self.log = self.root / "update.log"
        script = UPDATE_HELPER.read_text(encoding="utf-8").replace("\r\n", "\n")
        for real, stand_in in (
            ('LOG="/var/log/motionmodule-update.log"', f"LOG={bash_path(self.log)}"),
            ('SECRET_DIR="/run/motionmodule-update"', f"SECRET_DIR={bash_path(self.secret_dir)}"),
            ("/proc/self/cgroup", bash_path(self.cgroup)),
        ):
            self.assertIn(real, script, "the test must never touch the real path")
            script = script.replace(real, stand_in)
        self.helper = self.root / "update.sh"
        self.helper.write_text(script, encoding="utf-8", newline="\n")

    def in_cgroup(self, unit):
        self.cgroup.write_text(f"0::/system.slice/{unit}\n", encoding="utf-8", newline="\n")

    def store(self, text):
        self.secret_dir.mkdir()
        self.secret.write_text(text, encoding="utf-8", newline="\n")

    def run_helper(self, *arguments, stdin=""):
        environment = {
            **os.environ,
            "PATH": f"{self.stubs}{os.pathsep}{os.environ.get('PATH', '')}",
            "SUDO_USER": "aloe",
            "STUBS": self.stubs.as_posix(),
            "SECRET_FILE": self.secret.as_posix(),
        }
        # Bytes, so the password reaches bash exactly as typed on every system.
        result = subprocess.run(
            [BASH, str(self.helper), *arguments], input=stdin.encode("utf-8"), capture_output=True,
            env=environment, timeout=30, check=False,
        )
        return result.returncode, result.stdout.decode("utf-8"), result.stderr.decode("utf-8")

    def systemd_runs(self):
        log = self.stubs / "systemd-run.log"
        if not log.exists():
            return []
        return [run.strip("\n").split("\n") for run in log.read_text(encoding="utf-8").split("@@\n") if run.strip()]

    def test_a_password_is_stored_for_the_update_and_nowhere_else(self):
        password = ' correct horse \\ battery $HOME "quoted" '
        code, out, err = self.run_helper("testing", stdin=password + "\n")
        self.assertEqual(code, 0, out + err)

        update, forget = self.systemd_runs()
        self.assertIn("--unit=motionmodule-update", update)
        self.assertIn("--uid=aloe", update)
        self.assertIn("--setenv=SUDO_ASKPASS=/usr/local/sbin/motionmodule-askpass", update)
        self.assertIn("--setenv=DISPLAY=", update)
        self.assertEqual(update[-3:], ["/usr/local/bin/motionmodule", "install", "testing"])
        # In place before the update starts, byte for byte, for its sudo to read.
        self.assertEqual((self.stubs / "secret-at-start").read_text(encoding="utf-8"), password + "\n")
        self.assertEqual(self.secret.read_text(encoding="utf-8"), password + "\n")
        if os.name == "posix":
            self.assertEqual(self.secret_dir.stat().st_mode & 0o777, 0o700)
            self.assertEqual(self.secret.stat().st_mode & 0o777, 0o600)
        # A second unit deletes it once the update ends.
        self.assertIn("--unit=motionmodule-update-forget", forget)
        self.assertEqual(forget[-2:], ["/usr/local/sbin/motionmodule-update", "forget"])
        # Never on a command line, in the update log, or in the output.
        seen = (self.stubs / "systemd-run.log").read_text(encoding="utf-8") + self.log.read_text(encoding="utf-8")
        self.assertNotIn(password.strip(), seen + out + err)

    def test_without_a_password_the_update_starts_as_before(self):
        code, out, err = self.run_helper("main")
        self.assertEqual(code, 0, out + err)
        (update,) = self.systemd_runs()
        self.assertFalse([option for option in update if "SUDO_ASKPASS" in option or "DISPLAY" in option])
        self.assertEqual(update[-3:], ["/usr/local/bin/motionmodule", "install", "main"])
        self.assertFalse(self.secret_dir.exists())

    def test_a_second_press_leaves_the_running_update_its_password(self):
        self.store("first\n")
        (self.stubs / "update-active").touch()
        code, out, err = self.run_helper("testing", stdin="second\n")
        self.assertNotEqual(code, 0)
        self.assertIn("already running", err)
        self.assertEqual(self.secret.read_text(encoding="utf-8"), "first\n")
        self.assertEqual(self.systemd_runs(), [])

    def test_an_update_that_cannot_start_leaves_no_password_behind(self):
        (self.stubs / "systemd-run-fails").touch()
        code, out, err = self.run_helper("testing", stdin="secret\n")
        self.assertNotEqual(code, 0)
        self.assertIn("Could not start the update", err)
        self.assertFalse(self.secret_dir.exists())

    def test_a_password_left_by_an_earlier_update_is_removed(self):
        self.store("old\n")
        code, out, err = self.run_helper("testing")
        self.assertEqual(code, 0, out + err)
        self.assertFalse(self.secret_dir.exists())

    def test_only_processes_inside_the_update_are_given_the_password(self):
        self.store("secret\n")
        code, out, err = self.run_helper("password")  # asked from the robot's own service
        self.assertNotEqual(code, 0)
        self.assertEqual(out, "")
        self.assertIn("Only the running update", err)

        self.in_cgroup("motionmodule-update.service")
        self.assertEqual(self.run_helper("password")[:2], (0, "secret\n"))

    def test_an_update_without_a_password_has_none_to_give(self):
        self.in_cgroup("motionmodule-update.service")
        code, out, err = self.run_helper("password")
        self.assertNotEqual(code, 0)
        self.assertEqual(out, "")

    def test_the_password_is_deleted_once_the_update_ends(self):
        self.store("secret\n")
        (self.stubs / "states").write_text("active\ndeactivating\n", encoding="utf-8", newline="\n")
        code, out, err = self.run_helper("forget")
        self.assertEqual(code, 0, out + err)
        self.assertFalse(self.secret_dir.exists())
        shows = (self.stubs / "systemctl.log").read_text(encoding="utf-8").count("show")
        self.assertEqual(shows, 3, "it waited while the update was still running")

    def test_nothing_else_is_accepted(self):
        for arguments in ((), ("main", "testing"), ("rm -rf /",), ("--help",)):
            code, out, err = self.run_helper(*arguments)
            self.assertNotEqual(code, 0, arguments)
        self.assertEqual(self.systemd_runs(), [])


if __name__ == "__main__":
    unittest.main()
