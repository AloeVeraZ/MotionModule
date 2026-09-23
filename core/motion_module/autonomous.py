"""Optional autonomous routine support.

A robot folder may contain one extra file, ``autonomous.py``, holding the
routine the robot runs by itself. It is optional: a project without it simply
has no autonomous mode, and the Driver Station says so.

The file defines one entry point::

    def create_autonomous(module, drive):
        return MyAuto(module, drive)

and the object it returns needs a ``run(stop)`` method. ``stop`` is a
``threading.Event``: check ``stop.is_set()`` inside every loop and return as
soon as it is set. A plain module-level ``run(module, stop)`` function works
too, for a routine short enough not to need a class.

Nothing here trusts the routine to behave. Disabling stops every output
immediately whether or not the thread has noticed yet, and the run is bounded
by ``duration_seconds`` so a routine that never returns still ends.
"""

from __future__ import annotations

import math
import threading
import time
from pathlib import Path

from .runner import load_project


# Autonomous periods are bounded in every competition, and an unbounded routine
# is a robot nobody can talk to. A project may set its own `duration_seconds`,
# or None for no limit.
DEFAULT_DURATION_SECONDS = 30.0


def load_autonomous(module, drive, project_path: Path | None = None):
    """Load ``autonomous.py`` beside the active ``robot.py``, if there is one.

    Returns None when the project has no autonomous routine, which is the
    normal case rather than an error.
    """

    if project_path is None:
        return None
    path = project_path.with_name("autonomous.py")
    if not path.is_file():
        return None
    project = load_project(path)

    factory = getattr(project, "create_autonomous", None)
    if callable(factory):
        routine = factory(module, drive)
        if not callable(getattr(routine, "run", None)):
            raise RuntimeError(
                f"{path}: create_autonomous(module, drive) must return an object with run(stop)"
            )
        return routine

    # A short routine does not need a class, so accept a bare run(module, stop).
    plain = getattr(project, "run", None)
    if callable(plain):
        return _FunctionRoutine(plain, module)

    raise RuntimeError(
        f"{path} must define create_autonomous(module, drive) or run(module, stop)"
    )


class _FunctionRoutine:
    """Adapt a module-level ``run(module, stop)`` to the object interface."""

    def __init__(self, function, module) -> None:
        self._function = function
        self._module = module
        self.duration_seconds = getattr(function, "duration_seconds", DEFAULT_DURATION_SECONDS)

    def run(self, stop) -> None:
        self._function(self._module, stop)


class AutonomousRunner:
    """Start, watch, and reliably stop one autonomous routine.

    The routine runs on its own thread so the dashboard keeps answering while
    the robot moves. ``stop`` never waits on that thread to cooperate: it stops
    the outputs first and lets the thread notice afterwards.
    """

    def __init__(self, module, routine=None, stop_outputs=None, load_error: str = "") -> None:
        self._module = module
        self._routine = routine
        self._stop_outputs = stop_outputs
        # A broken autonomous.py must not take the dashboard down with it, so
        # the reason is carried here and shown instead of the mode.
        self._load_error = load_error
        self._lock = threading.RLock()
        self._thread: threading.Thread | None = None
        self._stop_event = threading.Event()
        self._state = "idle"
        self._error = ""
        self._started_at = 0.0
        self._finished_at = 0.0

    @property
    def configured(self) -> bool:
        return self._routine is not None

    @property
    def running(self) -> bool:
        with self._lock:
            return self._state == "running"

    def _duration(self) -> float | None:
        limit = getattr(self._routine, "duration_seconds", DEFAULT_DURATION_SECONDS)
        if limit is None:
            return None
        try:
            limit = float(limit)
        except (TypeError, ValueError):
            return DEFAULT_DURATION_SECONDS
        if not math.isfinite(limit):
            return DEFAULT_DURATION_SECONDS
        return limit if limit > 0 else None

    def status(self) -> dict:
        with self._lock:
            elapsed = 0.0
            if self._started_at:
                end = self._finished_at or time.monotonic()
                elapsed = round(max(0.0, end - self._started_at), 1)
            return {
                "configured": self.configured,
                "state": self._state,
                "error": self._error or self._load_error,
                "load_error": self._load_error,
                "elapsed_seconds": elapsed,
                "duration_seconds": self._duration() if self.configured else None,
            }

    def start(self) -> None:
        """Begin the routine. Raises if it cannot start."""

        with self._lock:
            if self._routine is None:
                raise RuntimeError(
                    self._load_error
                    or "This robot project has no autonomous.py, so it has no autonomous routine"
                )
            if self._state == "running" or (self._thread is not None and self._thread.is_alive()):
                raise RuntimeError("The autonomous routine is already running or still stopping")
            self._stop_event = threading.Event()
            self._state = "running"
            self._error = ""
            self._started_at = time.monotonic()
            self._finished_at = 0.0
            self._thread = threading.Thread(
                target=self._run, name="motionmodule-autonomous", daemon=True
            )
            self._thread.start()

    def _run(self) -> None:
        stop = self._stop_event
        limit = self._duration()
        expired = threading.Event()

        def cut_short() -> None:
            expired.set()
            stop.set()

        deadline = threading.Timer(limit, cut_short) if limit else None
        if deadline is not None:
            deadline.daemon = True
            deadline.start()
        state, error = "finished", ""
        try:
            self._routine.run(stop)
        except Exception as failure:   # the routine is student code
            state, error = "failed", f"{type(failure).__name__}: {failure}"
        finally:
            if deadline is not None:
                deadline.cancel()
            # However it ended, the robot stops moving.
            self._halt()
            with self._lock:
                # stop() already recorded an operator stop; don't overwrite it.
                if self._state == "running":
                    if state == "finished" and expired.is_set():
                        state = "expired"
                        error = f"The routine was still running after {limit:g} seconds and was cut short"
                    self._state = state
                    self._error = error
                    self._finished_at = time.monotonic()

    def _halt(self) -> None:
        if callable(self._stop_outputs):
            try:
                self._stop_outputs()
                return
            except Exception:
                pass
        try:
            self._module.stop_all()
        except Exception:
            pass

    def stop(self, *, timeout: float = 1.0) -> None:
        """Stop the routine and the robot, whether or not the thread agrees."""

        with self._lock:
            thread = self._thread
            self._stop_event.set()
            if self._state == "running":
                self._state = "stopped"
                self._finished_at = time.monotonic()
        # Outputs go quiet before waiting on anyone.
        self._halt()
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=timeout)
