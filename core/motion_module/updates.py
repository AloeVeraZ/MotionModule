"""Update checks and the dashboard's Update now button.

The Pi asks GitHub which commit each branch is on with ``git ls-remote`` (no
account, no API limits), compares that with the commit this release was built
from, and can install a branch through the root helper the installer puts at
/usr/local/sbin/motionmodule-update. That helper accepts only ``main`` or
``testing``, and runs the install in its own service so that restarting
MotionModule partway through does not kill the update.

A Pi on ``main`` is offered the main line only. A Pi on ``testing`` is offered
both, so it can take the newest testing code or go back to the main line.
"""

from __future__ import annotations

import os
import re
import subprocess
import threading
import time
from pathlib import Path

from .errors import MotionModuleError


REPOSITORY_URL = "https://github.com/AloeVeraZ/MotionModule.git"
REPOSITORY_NAME = "AloeVeraZ/MotionModule"
BRANCHES = ("main", "testing")
BRANCH_LABELS = {"main": "Main line", "testing": "Testing line"}
BRANCH_NOTES = {
    "main": "The stable line. Every release is merged here after testing.",
    "testing": "New work lands here first and can break. Go back with the main line.",
}
UPDATE_HELPER = Path("/usr/local/sbin/motionmodule-update")
UPDATE_UNIT = "motionmodule-update.service"
UPDATE_LOG = Path("/var/log/motionmodule-update.log")
CHECK_INTERVAL_SECONDS = 15 * 60
MAX_LOG_LINES = 40


def _short(text: str, limit: int = 200) -> str:
    return " ".join(str(text or "").split())[:limit]


def _read(path: Path, pattern: str) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeError):
        return ""
    return value if re.fullmatch(pattern, value) else ""


def installed_release(release_root: Path | None = None) -> dict:
    """The branch and commit this release was installed from, if recorded."""

    root = release_root or Path(__file__).resolve().parents[2]
    return {
        "ref": _read(root / "INSTALL_REF", r"[A-Za-z0-9._/-]{1,80}"),
        "commit": _read(root / "INSTALL_COMMIT", r"[0-9a-f]{7,40}"),
    }


def remote_commits(
    refs: tuple[str, ...] = BRANCHES,
    *,
    repository: str = REPOSITORY_URL,
    run=subprocess.run,
    timeout: float = 25.0,
) -> dict[str, str]:
    """Which commit each branch is on, straight from GitHub."""

    command = ["git", "ls-remote", "--heads", repository, *(f"refs/heads/{ref}" for ref in refs)]
    try:
        # No terminal here, so a repository that asks for a password must fail
        # rather than wait for one.
        result = run(
            command, capture_output=True, text=True, timeout=timeout,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_ASKPASS": "", "SSH_ASKPASS": ""},
        )
    except (OSError, subprocess.SubprocessError) as error:
        raise MotionModuleError(f"Could not reach GitHub: {_short(error)}") from error
    if result.returncode != 0:
        raise MotionModuleError(_short(result.stderr) or "Could not reach GitHub")
    found = {}
    for line in (result.stdout or "").splitlines():
        parts = line.split()
        if len(parts) == 2 and parts[1].startswith("refs/heads/") and re.fullmatch(r"[0-9a-f]{40}", parts[0]):
            found[parts[1][len("refs/heads/"):]] = parts[0]
    if not found:
        raise MotionModuleError("GitHub did not name a commit for those branches")
    return found


def update_lines(installed: dict, remotes: dict, *, error: str = "") -> list[dict]:
    """One row per branch this Pi is offered, in the order to show them."""

    ref = installed.get("ref", "")
    commit = installed.get("commit", "")
    if not ref:
        return []
    order = [ref] if ref in BRANCHES else []
    if "main" not in order:
        order.append("main")

    lines = []
    for branch in order:
        latest = remotes.get(branch, "")
        current = branch == ref
        if not latest:
            status = "unreachable"
        elif not current:
            status = "other-line"
        elif not commit:
            status = "unknown"
        elif latest == commit or latest.startswith(commit):
            status = "up-to-date"
        else:
            status = "update-available"
        lines.append({
            "ref": branch,
            "label": BRANCH_LABELS.get(branch, branch),
            "note": BRANCH_NOTES.get(branch, ""),
            "current": current,
            "status": status,
            "latest": latest[:7],
            "installed": commit[:7] if current else "",
            "action": "Update now" if current else f"Switch to the {BRANCH_LABELS.get(branch, branch).casefold()}",
        })
    return lines


def start_update(ref: str, *, run=subprocess.run, helper: Path = UPDATE_HELPER, timeout: float = 30.0) -> str:
    """Ask the root helper to install one branch. Returns as soon as it starts."""

    if ref not in BRANCHES:
        raise MotionModuleError("MotionModule installs the main or the testing branch")
    if not os.access(helper, os.X_OK):
        raise MotionModuleError(
            "This Pi was set up before the update button existed. Update it once over SSH with "
            f"motionmodule install {ref}; the button works from then on."
        )
    try:
        result = run(["sudo", "-n", str(helper), ref], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as error:
        raise MotionModuleError(f"Could not start the update: {_short(error)}") from error
    if result.returncode != 0:
        raise MotionModuleError(_short(result.stderr) or _short(result.stdout) or "Could not start the update")
    return _short(result.stdout) or f"Installing the {ref} branch."


def update_job(*, run=subprocess.run, unit: str = UPDATE_UNIT, log: Path = UPDATE_LOG) -> dict:
    """What the running or last update is doing, from systemd and its log."""

    values: dict[str, str] = {}
    try:
        answer = run(
            ["systemctl", "show", unit, "--property=ActiveState", "--property=Result",
             "--property=ExecMainStatus"],
            capture_output=True, text=True, timeout=10,
        )
        values = dict(
            line.split("=", 1) for line in (answer.stdout or "").splitlines() if "=" in line
        )
    except (OSError, subprocess.SubprocessError):
        values = {}

    try:
        text = log.read_text(encoding="utf-8", errors="replace")
        finished_at = log.stat().st_mtime
    except OSError:
        text, finished_at = "", None

    active = values.get("ActiveState", "")
    exit_status = values.get("ExecMainStatus", "")
    if active in {"activating", "active", "deactivating", "reloading"}:
        state = "running"
    elif active == "failed" or (exit_status not in {"", "0"} and text):
        state = "failed"
    elif text:
        state = "finished"
    else:
        state = "idle"
    return {
        "state": state,
        "result": values.get("Result", ""),
        "finished_at": finished_at,
        "log": [line for line in text.splitlines() if line.strip()][-MAX_LOG_LINES:],
    }


class UpdateChecker:
    """Keeps GitHub's answer for the dashboard, refreshed in the background.

    Asking GitHub takes a moment, so page requests never wait for it: they get
    the newest answer there is, and a check runs behind them when it is stale.
    """

    def __init__(
        self,
        *,
        release_root: Path | None = None,
        run=subprocess.run,
        clock=time.monotonic,
        interval: float = CHECK_INTERVAL_SECONDS,
        helper: Path = UPDATE_HELPER,
        unit: str = UPDATE_UNIT,
        log: Path = UPDATE_LOG,
    ) -> None:
        self._root = release_root
        self._run = run
        self._clock = clock
        self._interval = interval
        self._helper = helper
        self._unit = unit
        self._log = log
        self._lock = threading.Lock()
        self._remotes: dict[str, str] = {}
        self._error = ""
        self._checked = 0.0
        self._checked_at: float | None = None
        self._checking = False
        self._thread: threading.Thread | None = None

    def snapshot(self, *, refresh: bool = False) -> dict:
        installed = installed_release(self._root)
        with self._lock:
            stale = not self._checked or self._clock() - self._checked >= self._interval
            remotes = dict(self._remotes)
            error, checking, checked_at = self._error, self._checking, self._checked_at
            if (refresh or stale) and not checking:
                self._checking = checking = True
                self._thread = threading.Thread(
                    target=self._check, name="motionmodule-update-check", daemon=True
                )
                start = True
            else:
                start = False
        if start:
            self._thread.start()
        return {
            "repository": REPOSITORY_NAME,
            "installed": installed,
            "lines": update_lines(installed, remotes, error=error),
            "checking": checking,
            "checked_at": checked_at,
            "error": error,
            "installable": bool(os.access(self._helper, os.X_OK)),
            "job": update_job(run=self._run, unit=self._unit, log=self._log),
        }

    def _check(self) -> None:
        try:
            remotes, error = remote_commits(run=self._run), ""
        except MotionModuleError as failure:
            remotes, error = {}, str(failure)
        except Exception as failure:  # a check must never take the dashboard down
            remotes, error = {}, f"Could not check for updates: {_short(failure)}"
        with self._lock:
            self._remotes = remotes
            self._error = error
            self._checked = self._clock()
            self._checked_at = time.time()
            self._checking = False

    def start_update(self, ref: str) -> str:
        return start_update(ref, run=self._run, helper=self._helper)

    def close(self) -> None:
        with self._lock:
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=2.0)
