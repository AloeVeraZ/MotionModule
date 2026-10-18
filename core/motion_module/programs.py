"""Discover named teleop and autonomous folders without executing robot code."""

from pathlib import Path

from .errors import MotionModuleError


def program_mode(folder: Path) -> str | None:
    name = folder.name.casefold()
    if name.endswith("_tele"):
        return "teleop"
    if name.endswith("_auto"):
        return "autonomous"
    return None


def program_folders(project: Path) -> list[Path]:
    if not project.is_dir():
        return []
    return sorted(
        (child for child in project.iterdir()
         if child.is_dir() and not child.is_symlink() and program_mode(child)
         and (child / "robot.py").is_file()),
        key=lambda child: child.name.casefold(),
    )


def default_program(project: Path) -> Path:
    programs = program_folders(project)
    if programs:
        return next((folder for folder in programs if program_mode(folder) == "teleop"), programs[0])
    return project


def workspace_for(project: Path) -> Path | None:
    for parent in project.resolve().parents:
        if parent.name == "robots":
            return parent.parent
    return None


def list_programs(robots: Path, mode: str) -> list[dict]:
    if not isinstance(mode, str) or mode not in {"teleop", "autonomous"}:
        raise MotionModuleError("Choose teleop or autonomous")
    entries = []
    if not robots.is_dir():
        return entries
    root = robots.resolve()
    for project in sorted(robots.iterdir(), key=lambda path: path.name.casefold()):
        if not project.is_dir() or project.is_symlink() or project.name.startswith("."):
            continue
        folders = program_folders(project)
        for folder in folders or [project]:
            if not (folder / "robot.py").is_file():
                continue
            if program_mode(folder) and program_mode(folder) != mode:
                continue
            if mode == "autonomous" and not (folder / "autonomous.py").is_file():
                continue
            # Do not follow an entry point or folder outside the robot library.
            if not (folder / "robot.py").resolve().is_relative_to(root):
                continue
            entries.append({"id": folder.relative_to(robots).as_posix(),
                            "name": folder.name, "project": project.name, "mode": mode})
    return entries


def resolve_program(robots: Path, identifier: str, mode: str) -> Path:
    if not isinstance(identifier, str):
        raise MotionModuleError("Choose an installed program folder")
    entry = next((entry for entry in list_programs(robots, mode) if entry["id"] == identifier), None)
    if entry is None:
        raise MotionModuleError("Choose an installed program folder for this mode")
    return robots / entry["id"]
