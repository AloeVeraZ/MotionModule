"""Checking GitHub for a newer MotionModule, and starting an update."""

import getpass
import subprocess
import tempfile
import time
import unittest
from pathlib import Path

from motion_module.errors import MotionModuleError
from motion_module.updates import (
    BRANCHES,
    PASSWORD_ATTEMPTS,
    PASSWORD_WINDOW_SECONDS,
    PasswordRequired,
    TooManyPasswordAttempts,
    UpdateChecker,
    installed_release,
    remote_commits,
    start_update,
    sudo_needs_password,
    update_job,
    update_lines,
)


MAIN = "1111111111111111111111111111111111111111"
TESTING = "2222222222222222222222222222222222222222"
LS_REMOTE = f"{MAIN}\trefs/heads/main\n{TESTING}\trefs/heads/testing\n"


def release(ref="testing", commit=TESTING):
    directory = tempfile.TemporaryDirectory()
    root = Path(directory.name)
    if ref is not None:
        (root / "INSTALL_REF").write_text(f"{ref}\n", encoding="utf-8")
    if commit is not None:
        (root / "INSTALL_COMMIT").write_text(f"{commit}\n", encoding="utf-8")
    return directory, root


class Runner:
    """Stands in for subprocess.run, one answer per command name."""

    def __init__(self, **answers):
        self.answers = answers
        self.commands = []
        self.options = []

    def __call__(self, command, **options):
        self.commands.append(command)
        self.options.append(options)
        for name, answer in self.answers.items():
            if name in " ".join(command):
                if isinstance(answer, Exception):
                    raise answer
                return subprocess.CompletedProcess(command, answer[0], answer[1], answer[2])
        return subprocess.CompletedProcess(command, 0, "", "")


class InstalledReleaseTests(unittest.TestCase):
    def test_the_installed_branch_and_commit_are_read(self):
        directory, root = release()
        self.addCleanup(directory.cleanup)
        self.assertEqual(installed_release(root), {"ref": "testing", "commit": TESTING})

    def test_a_development_checkout_has_neither(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertEqual(installed_release(Path(directory)), {"ref": "", "commit": ""})

    def test_nonsense_files_are_ignored(self):
        directory, root = release(ref="testing; rm -rf /", commit="not a commit")
        self.addCleanup(directory.cleanup)
        self.assertEqual(installed_release(root), {"ref": "", "commit": ""})


class RemoteCommitTests(unittest.TestCase):
    def test_github_is_asked_for_both_branches_without_a_password_prompt(self):
        environments = []

        def run(command, **options):
            environments.append(options.get("env", {}))
            return subprocess.CompletedProcess(command, 0, LS_REMOTE, "")

        self.assertEqual(remote_commits(run=run), {"main": MAIN, "testing": TESTING})
        self.assertEqual(environments[0]["GIT_TERMINAL_PROMPT"], "0")

    def test_being_offline_is_an_error_not_a_guess(self):
        runner = Runner(**{"ls-remote": (128, "", "fatal: unable to access ... Could not resolve host")})
        with self.assertRaisesRegex(MotionModuleError, "Could not resolve host"):
            remote_commits(run=runner)
        with self.assertRaisesRegex(MotionModuleError, "Could not reach GitHub"):
            remote_commits(run=Runner(**{"ls-remote": OSError("git is missing")}))
        with self.assertRaisesRegex(MotionModuleError, "did not name a commit"):
            remote_commits(run=Runner(**{"ls-remote": (0, "nonsense\n", "")}))


class UpdateLineTests(unittest.TestCase):
    def test_a_pi_on_main_is_offered_the_main_line_only(self):
        lines = update_lines({"ref": "main", "commit": MAIN}, {"main": MAIN, "testing": TESTING})
        self.assertEqual([line["ref"] for line in lines], ["main"])
        self.assertEqual(lines[0]["status"], "up-to-date")
        self.assertTrue(lines[0]["current"])
        self.assertEqual(lines[0]["action"], "Update now")

    def test_a_pi_on_testing_is_offered_testing_first_then_main(self):
        lines = update_lines({"ref": "testing", "commit": "9" * 40}, {"main": MAIN, "testing": TESTING})
        self.assertEqual([line["ref"] for line in lines], ["testing", "main"])
        self.assertEqual(lines[0]["status"], "update-available")
        self.assertEqual(lines[0]["installed"], "9999999")
        self.assertEqual(lines[0]["latest"], TESTING[:7])
        self.assertEqual(lines[1]["status"], "other-line")
        self.assertIn("main line", lines[1]["action"])

    def test_an_unrecorded_commit_says_so_instead_of_claiming_to_be_current(self):
        lines = update_lines({"ref": "main", "commit": ""}, {"main": MAIN})
        self.assertEqual(lines[0]["status"], "unknown")

    def test_without_github_no_line_claims_to_know(self):
        lines = update_lines({"ref": "testing", "commit": TESTING}, {})
        self.assertEqual({line["status"] for line in lines}, {"unreachable"})

    def test_a_development_checkout_is_offered_nothing(self):
        self.assertEqual(update_lines({"ref": "", "commit": ""}, {"main": MAIN}), [])


SUDO_WANTS_PASSWORD = {"-n -k true": (1, "", "sudo: a password is required\n")}
WRONG_PASSWORD = (1, "", "Sorry, try again.\nsudo: no password was provided\nsudo: 1 incorrect password attempt\n")


def helper_calls(runner):
    return [index for index, command in enumerate(runner.commands) if "motionmodule-update" in " ".join(command)]


class StartUpdateTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.helper = Path(self.directory.name) / "motionmodule-update"
        self.askpass = Path(self.directory.name) / "motionmodule-askpass"
        for path in (self.helper, self.askpass):
            path.write_text("#!/bin/sh\n", encoding="utf-8")
            path.chmod(0o755)

    def start(self, ref, runner, **options):
        return start_update(ref, run=runner, helper=self.helper, askpass=self.askpass, **options)

    def test_only_the_two_branches_can_be_installed(self):
        for ref in ("", "rm -rf /", "some-other-branch", "main; reboot"):
            with self.assertRaisesRegex(MotionModuleError, "main or the testing"):
                self.start(ref, Runner())

    def test_the_root_helper_is_asked_to_install_the_branch(self):
        runner = Runner()
        message = self.start("testing", runner)
        self.assertEqual(runner.commands, [
            ["sudo", "-n", "-k", "true"],  # does sudo want a password? Here it does not.
            ["sudo", "-n", str(self.helper), "testing"],
        ])
        self.assertEqual(runner.options[-1]["input"], "")
        self.assertIn("testing", message)

    def test_an_older_pi_without_the_helper_is_told_what_to_run(self):
        with self.assertRaisesRegex(MotionModuleError, "motionmodule install main"):
            start_update("main", run=Runner(), helper=self.helper.with_name("missing"))

    def test_a_refused_helper_reports_why(self):
        runner = Runner(**{"motionmodule-update": (1, "", "sudo: a password is required")})
        with self.assertRaisesRegex(MotionModuleError, "password is required"):
            self.start("main", runner)

    def test_sudo_wanting_a_password_asks_the_dashboard_for_it_first(self):
        runner = Runner(**SUDO_WANTS_PASSWORD)
        with self.assertRaises(PasswordRequired) as asked:
            self.start("testing", runner)
        self.assertFalse(asked.exception.rejected)
        self.assertEqual(asked.exception.user, getpass.getuser())
        self.assertEqual(helper_calls(runner), [], "nothing starts without the password")
        # sudo's messages are read in English, whatever the Pi's language.
        self.assertEqual(runner.options[0]["env"]["LC_ALL"], "C")

    def test_a_wrong_password_is_refused_before_anything_starts(self):
        runner = Runner(**SUDO_WANTS_PASSWORD, **{"-S -k": WRONG_PASSWORD})
        with self.assertRaises(PasswordRequired) as refused:
            self.start("testing", runner, password="not-it")
        self.assertTrue(refused.exception.rejected)
        self.assertIn("not accepted", str(refused.exception))
        self.assertEqual(helper_calls(runner), [])

    def test_the_right_password_reaches_the_helper_on_stdin_only(self):
        runner = Runner(**SUDO_WANTS_PASSWORD)
        self.start("testing", runner, password="hunter2 two")
        check = runner.commands.index(["sudo", "-S", "-k", "-p", "", "true"])
        self.assertEqual(runner.options[check]["input"], "hunter2 two\n")
        self.assertEqual(helper_calls(runner), [len(runner.commands) - 1])
        self.assertEqual(runner.commands[-1], ["sudo", "-n", str(self.helper), "testing"])
        self.assertEqual(runner.options[-1]["input"], "hunter2 two\n")
        for command in runner.commands:
            self.assertNotIn("hunter2 two", " ".join(command))

    def test_a_password_is_not_passed_on_when_sudo_needs_none(self):
        runner = Runner()
        self.start("testing", runner, password="left over")
        self.assertEqual(runner.options[-1]["input"], "")
        self.assertNotIn(["sudo", "-S", "-k", "-p", "", "true"], runner.commands)

    def test_a_password_with_a_line_break_is_refused_unchecked(self):
        runner = Runner(**SUDO_WANTS_PASSWORD)
        with self.assertRaises(PasswordRequired) as refused:
            self.start("testing", runner, password="first\nsecond")
        self.assertTrue(refused.exception.rejected)
        self.assertEqual(len(runner.commands), 1)

    def test_a_user_sudo_refuses_outright_is_told_why(self):
        runner = Runner(**SUDO_WANTS_PASSWORD, **{"-S -k": (1, "", "aloe is not in the sudoers file.\n")})
        with self.assertRaisesRegex(MotionModuleError, "not in the sudoers file") as refused:
            self.start("testing", runner, password="hunter2")
        self.assertNotIsInstance(refused.exception, PasswordRequired)
        self.assertEqual(helper_calls(runner), [])

    def test_a_helper_too_old_for_passwords_says_to_update_over_ssh(self):
        runner = Runner(**SUDO_WANTS_PASSWORD)
        with self.assertRaisesRegex(MotionModuleError, "motionmodule install testing"):
            start_update("testing", password="hunter2", run=runner, helper=self.helper,
                         askpass=self.askpass.with_name("missing"))
        self.assertEqual(helper_calls(runner), [])

    def test_a_pi_without_sudo_is_not_asked_for_a_password(self):
        self.assertFalse(sudo_needs_password(run=Runner(**{"-n -k true": OSError("no sudo")})))
        self.assertFalse(sudo_needs_password(run=Runner(**{"-n -k true": (1, "", "sudo: some other trouble")})))


class UpdateJobTests(unittest.TestCase):
    def job(self, active, log_text=None, exit_status="0"):
        with tempfile.TemporaryDirectory() as directory:
            log = Path(directory) / "update.log"
            if log_text is not None:
                log.write_text(log_text, encoding="utf-8")
            runner = Runner(**{"systemctl": (
                0, f"ActiveState={active}\nResult=success\nExecMainStatus={exit_status}\n", "")})
            return update_job(run=runner, log=log)

    def test_nothing_has_run_yet(self):
        self.assertEqual(self.job("inactive")["state"], "idle")

    def test_a_running_update_shows_its_latest_output(self):
        job = self.job("activating", "[MotionModule] Updating to testing\nBuilding release\n")
        self.assertEqual(job["state"], "running")
        self.assertEqual(job["log"][-1], "Building release")
        self.assertIsNotNone(job["finished_at"])

    def test_a_finished_update_stays_visible(self):
        self.assertEqual(self.job("inactive", "done\n")["state"], "finished")

    def test_a_failed_update_is_not_reported_as_finished(self):
        self.assertEqual(self.job("failed", "boom\n")["state"], "failed")
        self.assertEqual(self.job("inactive", "boom\n", exit_status="1")["state"], "failed")

    def test_systemd_being_unavailable_is_survivable(self):
        self.assertEqual(update_job(run=Runner(**{"systemctl": OSError("no systemd")}),
                                    log=Path("/nonexistent/update.log"))["state"], "idle")


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


class UpdateCheckerTests(unittest.TestCase):
    def build(self, **options):
        directory, root = release(**options.pop("release", {}))
        self.addCleanup(directory.cleanup)
        self.clock = Clock()
        self.runner = Runner(**{"ls-remote": (0, LS_REMOTE, ""), "systemctl": (
            0, "ActiveState=inactive\nResult=success\nExecMainStatus=0\n", "")})
        checker = UpdateChecker(
            release_root=root, run=self.runner, clock=self.clock,
            helper=root / "missing-helper", log=root / "update.log", **options,
        )
        self.addCleanup(checker.close)
        return checker

    def settle(self, checker):
        deadline = time.monotonic() + 3
        while checker.snapshot()["checking"] and time.monotonic() < deadline:
            time.sleep(0.01)
        return checker.snapshot()

    def test_the_first_look_starts_a_check_and_the_answer_arrives(self):
        checker = self.build()
        first = checker.snapshot()
        self.assertTrue(first["checking"])
        self.assertEqual([line["status"] for line in first["lines"]], ["unreachable", "unreachable"])
        answered = self.settle(checker)
        self.assertEqual(answered["lines"][0]["status"], "up-to-date")
        self.assertEqual(answered["repository"], "AloeVeraZ/MotionModule")
        self.assertFalse(answered["installable"])  # no helper in this fake release

    def test_github_is_not_asked_again_until_the_answer_is_stale(self):
        checker = self.build()
        self.settle(checker)
        asked = len([command for command in self.runner.commands if "ls-remote" in command])
        checker.snapshot()
        self.assertEqual(len([c for c in self.runner.commands if "ls-remote" in c]), asked)
        self.clock.now += 16 * 60
        self.settle(checker)
        self.assertGreater(len([c for c in self.runner.commands if "ls-remote" in c]), asked)

    def test_check_now_asks_again_immediately(self):
        checker = self.build()
        self.settle(checker)
        checker.snapshot(refresh=True)
        self.settle(checker)
        self.assertEqual(len([c for c in self.runner.commands if "ls-remote" in c]), 2)

    def test_a_failed_check_is_reported_and_does_not_stop_the_dashboard(self):
        checker = self.build()
        self.runner.answers["ls-remote"] = (128, "", "fatal: Could not resolve host: github.com")
        snapshot = self.settle(checker)
        self.assertIn("Could not resolve host", snapshot["error"])
        self.assertEqual(snapshot["lines"][0]["status"], "unreachable")

    def test_an_update_needs_the_helper_the_installer_adds(self):
        checker = self.build()
        with self.assertRaisesRegex(MotionModuleError, "motionmodule install testing"):
            checker.start_update("testing")

    def installable(self, **answers):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        helpers = [Path(directory.name) / name for name in ("motionmodule-update", "motionmodule-askpass")]
        for path in helpers:
            path.write_text("#!/bin/sh\n", encoding="utf-8")
            path.chmod(0o755)
        self.clock = Clock()
        self.runner = Runner(**SUDO_WANTS_PASSWORD, **answers)
        checker = UpdateChecker(run=self.runner, clock=self.clock, helper=helpers[0], askpass=helpers[1])
        self.addCleanup(checker.close)
        return checker

    def checks(self):
        return self.runner.commands.count(["sudo", "-S", "-k", "-p", "", "true"])

    def test_wrong_passwords_stop_being_checked_for_a_while(self):
        checker = self.installable(**{"-S -k": WRONG_PASSWORD})
        for _ in range(PASSWORD_ATTEMPTS):
            with self.assertRaises(PasswordRequired):
                checker.start_update("testing", "guess")
        with self.assertRaisesRegex(TooManyPasswordAttempts, "Wait 10 minutes"):
            checker.start_update("testing", "one more guess")
        self.assertEqual(self.checks(), PASSWORD_ATTEMPTS, "sudo is not asked once the limit is reached")
        # The popup still opens meanwhile; it just cannot check anything.
        with self.assertRaises(PasswordRequired):
            checker.start_update("testing")
        self.clock.now += PASSWORD_WINDOW_SECONDS
        with self.assertRaises(PasswordRequired):
            checker.start_update("testing", "later guess")
        self.assertEqual(self.checks(), PASSWORD_ATTEMPTS + 1)

    def test_the_right_password_starts_the_update_and_clears_the_count(self):
        checker = self.installable(**{"-S -k": WRONG_PASSWORD})
        for _ in range(PASSWORD_ATTEMPTS - 1):
            with self.assertRaises(PasswordRequired):
                checker.start_update("testing", "guess")
        del self.runner.answers["-S -k"]
        self.assertIn("testing", checker.start_update("testing", "right"))
        self.runner.answers["-S -k"] = WRONG_PASSWORD
        for _ in range(PASSWORD_ATTEMPTS):
            with self.assertRaises(PasswordRequired):
                checker.start_update("testing", "guess")

    def test_branches_offered_are_the_two_lines(self):
        self.assertEqual(BRANCHES, ("main", "testing"))


if __name__ == "__main__":
    unittest.main()
