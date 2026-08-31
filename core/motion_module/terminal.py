"""Time-limited, authenticated Bash sessions for the local robot dashboard."""

from __future__ import annotations

import json
import os
import secrets
import signal
import subprocess
import threading
import time
from pathlib import Path

from .errors import MotionModuleError


DEFAULT_ACCESS_PATH = Path("~/.config/motionmodule/terminal-access.json").expanduser()
DEFAULT_IDLE_SECONDS = 300
MAX_INPUT_BYTES = 4096
MAX_BUFFER_CHARS = 100_000


def current_boot_id() -> str:
    try:
        return Path("/proc/sys/kernel/random/boot_id").read_text(encoding="utf-8").strip()
    except OSError:
        return "unavailable"


class TerminalSession:
    """One persistent, line-oriented Bash process owned by the service user."""

    def __init__(
        self,
        shell_path: str,
        working_directory: Path,
        expires_at: float,
        access_code: str,
        idle_seconds: int,
    ) -> None:
        environment = dict(os.environ)
        environment.update(
            {
                "TERM": "dumb",
                "PS1": "motionmodule:\\w$ ",
                "PS2": "> ",
                "HISTFILE": "/dev/null",
            }
        )
        self.token = secrets.token_urlsafe(32)
        self.access_code = access_code
        self.expires_at = expires_at
        self.idle_seconds = idle_seconds
        self._last_activity = time.monotonic()
        self._lock = threading.RLock()
        self._buffer = ""
        self._base_cursor = 0
        self._stopping = False
        self._master_fd, slave_fd = os.openpty()
        try:
            self.process = subprocess.Popen(
                [shell_path, "--noprofile", "--norc", "-i"],
                cwd=working_directory,
                env=environment,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                bufsize=0,
                close_fds=True,
                start_new_session=True,
            )
        except Exception:
            os.close(self._master_fd)
            os.close(slave_fd)
            raise
        else:
            os.close(slave_fd)
        threading.Thread(target=self._reader, name="motionmodule-terminal-output", daemon=True).start()
        threading.Thread(target=self._reaper, name="motionmodule-terminal-timeout", daemon=True).start()

    @property
    def active(self) -> bool:
        return self.process.poll() is None

    def _append(self, text: str) -> None:
        with self._lock:
            self._buffer += text
            if len(self._buffer) > MAX_BUFFER_CHARS:
                removed = len(self._buffer) - MAX_BUFFER_CHARS
                self._buffer = self._buffer[removed:]
                self._base_cursor += removed

    def _reader(self) -> None:
        try:
            while True:
                data = os.read(self._master_fd, 4096)
                if not data:
                    break
                self._append(data.decode("utf-8", errors="replace"))
        except OSError:
            pass
        finally:
            if not self._stopping:
                self._append("\n[MotionModule terminal closed]\n")
            try:
                os.close(self._master_fd)
            except OSError:
                pass

    def _reaper(self) -> None:
        while self.active:
            if time.time() >= self.expires_at:
                self._append("\n[Terminal access expired]\n")
                self.stop()
                return
            if time.monotonic() - self._last_activity >= self.idle_seconds:
                self._append("\n[Terminal closed after inactivity]\n")
                self.stop()
                return
            time.sleep(1)

    def touch(self) -> None:
        self._last_activity = time.monotonic()

    def write(self, value: str) -> None:
        if not self.active:
            raise MotionModuleError("The terminal session is closed")
        if not isinstance(value, str) or not value:
            raise MotionModuleError("Terminal input must not be empty")
        encoded = value.encode("utf-8")
        if len(encoded) > MAX_INPUT_BYTES:
            raise MotionModuleError(f"Terminal input is limited to {MAX_INPUT_BYTES} bytes")
        if "\x00" in value:
            raise MotionModuleError("Terminal input cannot contain a null byte")
        try:
            os.write(self._master_fd, encoded)
        except (BrokenPipeError, OSError) as error:
            raise MotionModuleError("The terminal process stopped") from error
        self.touch()

    def read(self, cursor: int) -> dict:
        if isinstance(cursor, bool) or not isinstance(cursor, int) or cursor < 0:
            raise MotionModuleError("Terminal cursor must be a non-negative integer")
        self.touch()
        with self._lock:
            reset = cursor < self._base_cursor
            start = 0 if reset else min(len(self._buffer), cursor - self._base_cursor)
            output = self._buffer[start:]
            next_cursor = self._base_cursor + len(self._buffer)
        return {
            "output": output,
            "cursor": next_cursor,
            "reset": reset,
            "active": self.active,
        }

    def interrupt(self) -> None:
        if not self.active:
            return
        try:
            os.killpg(self.process.pid, signal.SIGINT)
        except (AttributeError, OSError):
            self.process.send_signal(signal.SIGINT)
        self.touch()

    def stop(self) -> None:
        if not self.active:
            return
        self._stopping = True
        try:
            os.killpg(self.process.pid, signal.SIGTERM)
        except (AttributeError, OSError):
            self.process.terminate()
        try:
            self.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(self.process.pid, signal.SIGKILL)
            except (AttributeError, OSError):
                self.process.kill()
        try:
            os.close(self._master_fd)
        except OSError:
            pass


class TerminalManager:
    """Validate temporary access grants and own at most one Bash session."""

    def __init__(
        self,
        access_path: str | os.PathLike[str] | None = None,
        shell_path: str | None = None,
        idle_seconds: int = DEFAULT_IDLE_SECONDS,
        boot_id: str | None = None,
    ) -> None:
        self.access_path = Path(access_path or os.environ.get("MOTIONMODULE_TERMINAL_ACCESS", DEFAULT_ACCESS_PATH)).expanduser()
        self.shell_path = shell_path or os.environ.get("MOTIONMODULE_SHELL", "/bin/bash")
        self.idle_seconds = idle_seconds
        self.boot_id = boot_id or current_boot_id()
        self._lock = threading.RLock()
        self._session: TerminalSession | None = None

    @property
    def available(self) -> bool:
        return (
            os.name == "posix"
            and Path(self.shell_path).is_file()
            and os.access(self.shell_path, os.X_OK)
        )

    def _access_record(self) -> dict | None:
        try:
            record = json.loads(self.access_path.read_text(encoding="utf-8"))
            code = record["code"]
            expires_at = float(record["expires_at"])
            boot_id = record["boot_id"]
        except (OSError, KeyError, TypeError, ValueError, json.JSONDecodeError):
            return None
        if not isinstance(code, str) or not code or boot_id != self.boot_id:
            return None
        if expires_at <= time.time():
            return None
        return {"code": code, "expires_at": expires_at}

    def status(self) -> dict:
        record = self._access_record()
        with self._lock:
            if self._session and self._session.active:
                if record is None or not secrets.compare_digest(
                    record["code"], self._session.access_code
                ):
                    self._session.stop()
            active = bool(self._session and self._session.active)
        return {
            "available": self.available,
            "enabled": record is not None,
            "expires_in_seconds": max(0, round(record["expires_at"] - time.time())) if record else 0,
            "active": active,
            "idle_timeout_seconds": self.idle_seconds,
        }

    def start(self, access_code: str, working_directory: Path | None = None) -> dict:
        if not self.available:
            raise MotionModuleError("Web Bash is available only on the Raspberry Pi Linux runtime")
        record = self._access_record()
        if record is None:
            raise MotionModuleError("Terminal access is disabled or expired; run motionmodule terminal enable over SSH")
        if not isinstance(access_code, str) or not secrets.compare_digest(
            access_code.strip(), record["code"]
        ):
            raise MotionModuleError("Invalid terminal access code")
        with self._lock:
            if self._session and self._session.active:
                raise MotionModuleError("A terminal session is already active")
            directory = (working_directory or Path.cwd()).resolve()
            self._session = TerminalSession(
                self.shell_path,
                directory,
                record["expires_at"],
                record["code"],
                self.idle_seconds,
            )
            return {"token": self._session.token, "cursor": 0}

    def _authorized_session(self, token: str) -> TerminalSession:
        with self._lock:
            session = self._session
        if session is None or not session.active:
            raise MotionModuleError("No terminal session is active")
        if not isinstance(token, str) or not secrets.compare_digest(token, session.token):
            raise MotionModuleError("Invalid terminal session")
        record = self._access_record()
        if record is None or not secrets.compare_digest(record["code"], session.access_code):
            session.stop()
            raise MotionModuleError("Terminal access was disabled or expired")
        return session

    def read(self, token: str, cursor: int) -> dict:
        return self._authorized_session(token).read(cursor)

    def write(self, token: str, value: str) -> None:
        self._authorized_session(token).write(value)

    def interrupt(self, token: str) -> None:
        self._authorized_session(token).interrupt()

    def stop(self, token: str) -> None:
        self._authorized_session(token).stop()
