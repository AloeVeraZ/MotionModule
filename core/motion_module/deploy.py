"""Safe installation of a robot project uploaded from a development computer."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import tarfile
import tokenize
import uuid
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from .errors import MotionModuleError


PROJECT_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
MAX_ARCHIVE_BYTES = 50 * 1024 * 1024
MAX_EXPANDED_BYTES = 100 * 1024 * 1024
MAX_MEMBERS = 2_000


def validate_project_name(value: str) -> str:
    if not PROJECT_NAME.fullmatch(value) or value == "active":
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


def _check_python(project: Path) -> None:
    robot = project / "robot.py"
    if not robot.is_file():
        raise MotionModuleError("The uploaded project must contain robot.py at its top level")
    for source_path in sorted(project.rglob("*.py")):
        try:
            with tokenize.open(source_path) as source_file:
                compile(source_file.read(), str(source_path), "exec")
        except (OSError, SyntaxError, UnicodeError) as error:
            relative = source_path.relative_to(project)
            raise MotionModuleError(f"Python check failed for {relative}: {error}") from error


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
