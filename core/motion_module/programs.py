"""Separate teleop and autonomous program folders, inspected without execution."""

import argparse
import ast
import hashlib
import os
import shutil
import uuid
from pathlib import Path

from .errors import MotionModuleError

MODES = {"teleop", "autonomous"}

# Exact stock bundles from earlier releases. Older installers kept
# robot folders unchanged across software updates, so the previous release's
# example may be newer than the copy still on a robot. Never match by name.
LEGACY_AUTONOMOUS_BUNDLES = {
    "3bd4b319cd7f43ba71287414f37a67bcb1a2f5b9a5e57d2402137260631fd5a2",
    "2d8c43889bb28e49125708321368b315dc3634a2abec2511478a5bb7dfc4ab35",
    "da4b1d87e7e3888ab96d03c9c9b6ef27eea172d7dc686c36bcf47fe48865109c",
    "3680686eaa5b38a880a3115d689ff4ce4b67acfee2c6b78bf05fb50a31bd923b",
    "f0a93d84622724427410312967f67b31a892e67fdded05f0a807cbc1a316b68d",
    "b9054779c69ea10be0c0b90ff66b4fef6119a8888e0262980353f6fe5c7cd967",
    "2f6c86c5c42e574d719a65a13644d2c117f6f1c2bb1d7d0dad6c8591401e491f",
    "bd7ca9c9daa5bd60494697e029dcba1cb467aa334b53c7b5994bef8e08bec6a4",
    "329bc61f86b4d06ccef8fbc005f1f10bb41f0aa5c934bc73c60ca47610077c7d",
}


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


def _bundle_signature(contents: dict[str, bytes]) -> str:
    digest = hashlib.sha256()
    for name, content in sorted(contents.items()):
        digest.update(name.encode("utf-8") + b"\0" + hashlib.sha256(content).digest())
    return digest.hexdigest()


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
    installed_auto = (_contents(autonomous_target) if autonomous_target.is_dir()
                      and not autonomous_target.is_symlink() else None)
    stock_auto = installed_auto is not None and (
        _bundle_signature(installed_auto) in LEGACY_AUTONOMOUS_BUNDLES
        or (old_reference and old_reference.is_dir() and installed_auto == _contents(old_reference)))
    if stock_auto and installed_auto != _contents(autonomous_sample):
        # Refresh the shipped routine so control fixes reach existing robots.
        # Leave edited programs alone and retain the previous stock copy.
        if autonomous_target.resolve().parent != (robots / "autonomous").resolve():
            raise MotionModuleError("The autonomous program is outside the robot library")
        os.replace(autonomous_target, backups / f"updated-autonomous-driver-{uuid.uuid4().hex[:8]}")
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
