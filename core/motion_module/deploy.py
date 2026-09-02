"""Safe installation of a robot project uploaded from a development computer."""

from __future__ import annotations

import argparse
import ast
import os
import re
import shutil
import tarfile
import tokenize
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Iterable

from .config import load_project_config
from .errors import ConfigurationError, MotionModuleError


PROJECT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_EXPANDED_BYTES = 100 * 1024 * 1024
MAX_MEMBERS = 2_000
MAX_BROWSER_BYTES = 8 * 1024 * 1024
MAX_BROWSER_FILE_BYTES = 2 * 1024 * 1024
MAX_BROWSER_FILES = 250
ALLOWED_BROWSER_SUFFIXES = {".py", ".md", ".txt"}
EXCLUDED_PARTS = {
    ".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".venv",
    "__pycache__", "build", "dist", "node_modules",
}


def validate_project_name(value: str) -> str:
    if not isinstance(value, str) or not PROJECT_NAME.fullmatch(value) or value == "active":
        raise MotionModuleError(
            "Project names must start with a letter or number, use only letters, "
            "numbers, dots, dashes, or underscores, and cannot be 'active'"
        )
    return value


def _member_parts(member: tarfile.TarInfo) -> tuple[str, ...]:
    name = member.name
    path = PurePosixPath(name)
    if (
        not name
        or name.startswith("/")
        or "\\" in name
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise MotionModuleError(f"Unsafe path in uploaded project: {name!r}")
    if not (member.isfile() or member.isdir()):
        raise MotionModuleError(f"Links and special files are not allowed: {name!r}")
    return path.parts


def _extract_archive(archive_path: Path, staging: Path) -> None:
    try:
        archive_size = archive_path.stat().st_size
    except OSError as error:
        raise MotionModuleError(f"Cannot read uploaded project archive: {error}") from error
    if archive_size > MAX_ARCHIVE_BYTES:
        raise MotionModuleError("Uploaded project archive is larger than 50 MiB")

    try:
        with tarfile.open(archive_path, mode="r:gz") as archive:
            members = archive.getmembers()
            if len(members) > MAX_MEMBERS:
                raise MotionModuleError("Uploaded project contains too many files")
            expanded = sum(member.size for member in members if member.isfile())
            if expanded > MAX_EXPANDED_BYTES:
                raise MotionModuleError("Uploaded project expands beyond 100 MiB")

            validated: list[tuple[tarfile.TarInfo, tuple[str, ...]]] = []
            seen: set[tuple[str, ...]] = set()
            for member in members:
                parts = _member_parts(member)
                if parts in seen:
                    raise MotionModuleError(f"Duplicate path in uploaded project: {member.name}")
                seen.add(parts)
                validated.append((member, parts))

            for member, parts in validated:
                destination = staging.joinpath(*parts)
                if member.isdir():
                    destination.mkdir(parents=True, exist_ok=True)
                    destination.chmod(0o755)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                source = archive.extractfile(member)
                if source is None:
                    raise MotionModuleError(f"Could not read uploaded file: {member.name}")
                with source, destination.open("wb") as output:
                    shutil.copyfileobj(source, output)
                destination.chmod(0o755 if member.mode & 0o111 else 0o644)
    except (tarfile.TarError, OSError) as error:
        raise MotionModuleError(f"Uploaded project is not a valid archive: {error}") from error


def _check_python(project: Path, *, require_hardware: bool = False) -> None:
    robot = project / "robot.py"
    if not robot.is_file():
        raise MotionModuleError("The uploaded project must contain robot.py at its top level")
    if require_hardware and not (project / "hardware.py").is_file():
        raise MotionModuleError(
            "The robot folder must contain hardware.py with its pins and hardware setup"
        )
    for source_path in sorted(project.rglob("*.py")):
        try:
            with tokenize.open(source_path) as source_file:
                compile(source_file.read(), str(source_path), "exec")
        except (OSError, SyntaxError, UnicodeError) as error:
            relative = source_path.relative_to(project)
            raise MotionModuleError(f"Python check failed for {relative}: {error}") from error
    if require_hardware:
        try:
            tree = ast.parse(robot.read_text(encoding="utf-8"), filename=str(robot))
        except (OSError, SyntaxError, UnicodeError) as error:
            raise MotionModuleError(f"Could not validate robot.py: {error}") from error
        if not any(
            isinstance(node, ast.FunctionDef) and node.name == "create_drive"
            for node in tree.body
        ):
            raise MotionModuleError("robot.py must define create_drive(module)")
        try:
            load_project_config(project)
        except ConfigurationError as error:
            raise MotionModuleError(str(error)) from error


def _replace_project(staging: Path, target: Path, backups: Path, name: str) -> Path | None:
    backup: Path | None = None
    if target.exists():
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        backup = backups / f"{name}-{stamp}-{uuid.uuid4().hex[:8]}"
        os.replace(target, backup)
    try:
        os.replace(staging, target)
    except OSError:
        if backup is not None and not target.exists():
            os.replace(backup, target)
        raise
    return backup


def deploy_archive(
    archive_path: str | os.PathLike[str],
    robots_directory: str | os.PathLike[str],
    backup_directory: str | os.PathLike[str],
    project_name: str,
) -> dict:
    """Validate, back up, and atomically install one uploaded robot project."""

    name = validate_project_name(project_name)
    archive = Path(archive_path).resolve()
    robots = Path(robots_directory).resolve()
    backups = Path(backup_directory).resolve()
    robots.mkdir(parents=True, exist_ok=True)
    backups.mkdir(parents=True, exist_ok=True)

    target = robots / name
    if target.is_symlink() or (target.exists() and not target.is_dir()):
        raise MotionModuleError(f"Refusing to replace non-project path: {target}")

    staging = robots / f".{name}.deploy-{uuid.uuid4().hex}"
    staging.mkdir(mode=0o700)
    backup: Path | None = None
    try:
        _extract_archive(archive, staging)
        _check_python(staging)
        backup = _replace_project(staging, target, backups, name)
    except MotionModuleError:
        raise
    except OSError as error:
        raise MotionModuleError(f"Could not install project {name}: {error}") from error
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)

    return {
        "name": name,
        "target": str(target),
        "backup": str(backup) if backup is not None else None,
    }


def _browser_parts(filename: str) -> tuple[str, ...]:
    normalized = str(filename or "").replace("\\", "/")
    path = PurePosixPath(normalized)
    if (
        not normalized
        or normalized.startswith("/")
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise MotionModuleError(f"Unsafe path in selected folder: {filename!r}")
    return path.parts


def deploy_project_files(
    files: Iterable[tuple[str, bytes]],
    robots_directory: str | os.PathLike[str],
    backup_directory: str | os.PathLike[str],
    project_name: str | None = None,
) -> dict:
    """Validate and atomically install a folder selected in the web Driver Station."""

    entries = [(str(filename), content) for filename, content in files]
    if not entries:
        raise MotionModuleError("Choose one robot project folder first")
    if len(entries) > MAX_BROWSER_FILES:
        raise MotionModuleError(f"Robot folders are limited to {MAX_BROWSER_FILES} files")
    raw_parts = [_browser_parts(filename) for filename, _content in entries]
    if not all(len(parts) > 1 for parts in raw_parts):
        raise MotionModuleError("Select the robot project folder, not individual loose files")
    common_root = raw_parts[0][0]
    if not all(parts[0] == common_root for parts in raw_parts):
        raise MotionModuleError("Select exactly one robot project folder")
    if project_name and project_name != common_root:
        raise MotionModuleError("The project name must match the selected folder name")
    name = validate_project_name(common_root)

    normalized: list[tuple[tuple[str, ...], bytes]] = []
    seen: set[str] = set()
    total_bytes = 0
    for parts, (_filename, content) in zip(raw_parts, entries):
        relative = parts[1:] if common_root else parts
        if not relative or any(part in EXCLUDED_PARTS for part in relative):
            continue
        suffix = Path(relative[-1]).suffix.casefold()
        if suffix not in ALLOWED_BROWSER_SUFFIXES:
            raise MotionModuleError(
                f"{PurePosixPath(*relative)} is not Python or project documentation; remove it before upload"
            )
        if not isinstance(content, bytes):
            raise MotionModuleError("Uploaded project data is invalid")
        if len(content) > MAX_BROWSER_FILE_BYTES:
            raise MotionModuleError(f"{PurePosixPath(*relative)} is larger than 2 MiB")
        if b"\x00" in content:
            raise MotionModuleError(f"{PurePosixPath(*relative)} is not a text file")
        key = "/".join(relative).casefold()
        if key in seen:
            raise MotionModuleError(f"Duplicate path in selected folder: {PurePosixPath(*relative)}")
        seen.add(key)
        total_bytes += len(content)
        if total_bytes > MAX_BROWSER_BYTES:
            raise MotionModuleError("Robot folder is larger than 8 MiB")
        normalized.append((relative, content))

    robots = Path(robots_directory).resolve()
    backups = Path(backup_directory).resolve()
    robots.mkdir(parents=True, exist_ok=True)
    backups.mkdir(parents=True, exist_ok=True)
    target = robots / name
    if target.is_symlink() or (target.exists() and not target.is_dir()):
        raise MotionModuleError(f"Refusing to replace non-project path: {target}")
    staging = robots / f".{name}.browser-{uuid.uuid4().hex}"
    staging.mkdir(mode=0o700)
    backup: Path | None = None
    try:
        for relative, content in normalized:
            destination = staging.joinpath(*relative)
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(content)
            destination.chmod(0o644)
        _check_python(staging, require_hardware=True)
        backup = _replace_project(staging, target, backups, name)
    except MotionModuleError:
        raise
    except OSError as error:
        raise MotionModuleError(f"Could not install project {name}: {error}") from error
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
    return {
        "name": name,
        "target": str(target),
        "backup": str(backup) if backup is not None else None,
        "files": len(normalized),
        "bytes": total_bytes,
    }


def activate_project(target: str | os.PathLike[str], active_link: str | os.PathLike[str]) -> None:
    """Atomically point the managed active symlink at a validated robot project."""

    project = Path(target).resolve()
    link = Path(active_link)
    link.parent.mkdir(parents=True, exist_ok=True)
    temporary = link.with_name(f".{link.name}.new-{uuid.uuid4().hex}")
    try:
        temporary.symlink_to(project, target_is_directory=True)
        os.replace(temporary, link)
    finally:
        temporary.unlink(missing_ok=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install a validated MotionModule robot archive")
    parser.add_argument("archive", type=Path)
    parser.add_argument("robots_directory", type=Path)
    parser.add_argument("backup_directory", type=Path)
    parser.add_argument("project_name")
    args = parser.parse_args(argv)
    try:
        result = deploy_archive(
            args.archive,
            args.robots_directory,
            args.backup_directory,
            args.project_name,
        )
    except MotionModuleError as error:
        parser.exit(1, f"[MotionModule ERROR] {error}\n")
    print(f"Installed robot project {result['name']} at {result['target']}")
    if result["backup"]:
        print(f"Previous project backed up at {result['backup']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
