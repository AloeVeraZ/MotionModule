"""Separate teleop and autonomous program folders, inspected without execution."""

import argparse
import ast
import os
import shutil
import uuid
from pathlib import Path

from .errors import MotionModuleError

MODES = {"teleop", "autonomous"}


def source_mode(source: str, name: str = "") -> str:
    """Classify a standalone program; an old drive plus autonomous.py is teleop."""
    if name.casefold().endswith("_auto"):
        return "autonomous"
    if name.casefold().endswith("_tele"):
        return "teleop"
    try:
        nodes = ast.parse(source).body
    except (SyntaxError, ValueError):
        return "teleop"  # Validation reports the actual error when selected.
    for node in nodes:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "PROGRAM_MODE" for t in node.targets):
            if isinstance(node.value, ast.Constant) and node.value.value in MODES:
                return node.value.value
    names = {node.name for node in nodes if isinstance(node, (ast.FunctionDef, ast.ClassDef))}
    if {"create_drive", "MecanumDrive"} & names:
        return "teleop"
    return "autonomous" if {"create_autonomous", "run"} & names else "teleop"


def program_mode(folder: Path) -> str:
    if folder.parent.name in MODES:
        return folder.parent.name
    try:
        source = (folder / "robot.py").read_text(encoding="utf-8-sig")
    except (OSError, UnicodeError):
        source = ""
    return source_mode(source, folder.name)


def program_folders(project: Path) -> list[Path]:
    if not project.is_dir():
        return []
    return sorted((child.parent for child in project.rglob("robot.py")
                   if child.parent != project and not any(part.startswith(".") or part == "__pycache__"
                   for part in child.relative_to(project).parts)
                   and not any(parent.is_symlink() for parent in child.parents if parent != project)
                   and not child.is_symlink()), key=lambda folder: folder.as_posix().casefold())


def default_program(project: Path) -> Path:
    if (project / "robot.py").is_file():
        return project
    programs = program_folders(project)
    return next((folder for folder in programs if program_mode(folder) == "teleop"), programs[0] if programs else project)


def workspace_for(project: Path) -> Path | None:
    for parent in project.resolve().parents:
        if parent.name == "robots":
            return parent.parent
    return None


def list_programs(robots: Path, mode: str) -> list[dict]:
    if not isinstance(mode, str) or mode not in MODES:
        raise MotionModuleError("Choose teleop or autonomous")
    if not robots.is_dir():
        return []
    entries = []
    mode_root = robots / mode
    if not mode_root.is_dir() or mode_root.is_symlink():
        return []
    root = mode_root.resolve()
    for folder in sorted(mode_root.iterdir(), key=lambda item: item.name.casefold()):
        # Only robots/<mode>/<name>/robot.py is a selectable program. Old flat
        # projects, loose Python files and deeper nested folders are ignored.
        if not folder.is_dir() or folder.is_symlink() or folder.name.startswith("."):
            continue
        robot_file = folder / "robot.py"
        if not robot_file.is_file() or robot_file.is_symlink() or not robot_file.resolve().is_relative_to(root):
            continue
        entries.append({"id": folder.relative_to(robots).as_posix(), "name": folder.name,
                        "project": folder.name, "mode": mode})
    return entries


def resolve_program(robots: Path, identifier: str, mode: str) -> Path:
    if not isinstance(identifier, str):
        raise MotionModuleError("Choose an installed program folder")
    if not any(entry["id"] == identifier for entry in list_programs(robots, mode)):
        raise MotionModuleError("Choose an installed program folder for this mode")
    return robots / identifier


def _contents(folder: Path) -> dict[str, bytes]:
    return {path.relative_to(folder).as_posix(): path.read_bytes().replace(b"\r\n", b"\n")
            for path in folder.rglob("*") if path.is_file() and not path.is_symlink()
            and not any(part.startswith(".") or part == "__pycache__" for part in path.relative_to(folder).parts)
            and path.suffix not in {".pyc", ".pyo"}}


def initialize_library(robots: Path, backups: Path, sample: Path, previous_examples: Path | None = None) -> Path:
    """Install Mecanum teleop and Autonomous Driver for four-wheel mecanum robots."""
    robots.mkdir(parents=True, exist_ok=True)
    backups.mkdir(parents=True, exist_ok=True)
    if backups.resolve().is_relative_to(robots.resolve()):
        raise MotionModuleError("Program backups must be outside the robot library")
    for name in ("Mecanum", "MecanumMini"):
        old = robots / name
        reference = previous_examples / name if previous_examples else None
        if old.is_dir() and not old.is_symlink() and reference and reference.is_dir() and _contents(old) == _contents(reference):
            # Paths are fixed children of the robot library; retain the entire old folder.
            if old.resolve().parent != robots.resolve():
                raise MotionModuleError("The old program is outside the robot library")
            os.replace(old, backups / f"retired-{name}-{uuid.uuid4().hex[:8]}")
    target = robots / "teleop" / "Mecanum"
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(sample, target, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    autonomous_sample = sample.parent / "MecanumAutonomous"
    if not (autonomous_sample / "robot.py").is_file() or not (autonomous_sample / "autonomous.py").is_file():
        raise MotionModuleError("The bundled Autonomous Driver program is incomplete")
    old_autonomous = robots / "autonomous" / "Mecanum"
    old_reference = previous_examples / "MecanumAutonomous" if previous_examples else None
    if (old_autonomous.is_dir() and not old_autonomous.is_symlink() and old_reference
            and old_reference.is_dir() and _contents(old_autonomous) == _contents(old_reference)):
        if old_autonomous.resolve().parent != (robots / "autonomous").resolve():
            raise MotionModuleError("The old autonomous program is outside the robot library")
        os.replace(old_autonomous, backups / f"retired-autonomous-Mecanum-{uuid.uuid4().hex[:8]}")
    autonomous_target = robots / "autonomous" / "Autonomous Driver"
    if not autonomous_target.exists():
        autonomous_target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(autonomous_sample, autonomous_target,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
    return target


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("robots", type=Path)
    parser.add_argument("backups", type=Path)
    parser.add_argument("sample", type=Path)
    parser.add_argument("--previous-examples", type=Path)
    args = parser.parse_args(argv)
    print(initialize_library(args.robots, args.backups, args.sample, args.previous_examples))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
