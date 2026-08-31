"""Load a student robot.py file under systemd with guaranteed safe shutdown."""

from __future__ import annotations

import argparse
import importlib.util
import signal
import sys
import threading
from pathlib import Path

from .controller import MotionModule


def load_project(path: Path):
    if not path.is_file():
        raise FileNotFoundError(f"Robot project was not found: {path}")
    project_dir = str(path.parent.resolve())
    if project_dir not in sys.path:
        sys.path.insert(0, project_dir)
    spec = importlib.util.spec_from_file_location("motionmodule_user_robot", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load robot project: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run one MotionModule robot project")
    parser.add_argument("project", type=Path, help="Path to the student's robot.py")
    args = parser.parse_args(argv)
    stop_event = threading.Event()

    def stop(_signum=None, _frame=None):
        stop_event.set()

    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    project = load_project(args.project.resolve())
    run = getattr(project, "run", None)
    if not callable(run):
        raise RuntimeError(f"{args.project} must define run(module, stop_event)")

    with MotionModule() as controller:
        try:
            run(controller, stop_event)
        finally:
            stop_event.set()
            controller.stop_all()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

