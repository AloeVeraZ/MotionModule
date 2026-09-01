#!/usr/bin/env python3
"""Push a local robot project to MotionModule over SSH."""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import uuid
from pathlib import Path


HOST = re.compile(r"^[A-Za-z0-9._-]+@[A-Za-z0-9.-]+$")
PROJECT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
EXCLUDED_PARTS = {
    ".git",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    ".venv",
    "__pycache__",
    "build",
    "dist",
    "node_modules",
}


def validate_source(source: Path, name: str, host: str) -> Path:
    source = source.expanduser().resolve()
    if not source.is_dir() or not (source / "robot.py").is_file():
        raise ValueError(f"{source} must be a folder containing robot.py")
    if not PROJECT.fullmatch(name) or name == "active":
        raise ValueError("Project name must be 1-64 safe filename characters and cannot be active")
    if not HOST.fullmatch(host):
        raise ValueError("Robot must look like username@motionmodule.local or username@192.168.1.20")
    return source


def create_archive(source: Path, destination: Path) -> None:
    with tarfile.open(destination, mode="w:gz") as archive:
        for item in sorted(source.rglob("*")):
            relative = item.relative_to(source)
            if any(part in EXCLUDED_PARTS for part in relative.parts):
                continue
            if item.is_symlink():
                raise ValueError(f"Symbolic links are not supported in robot projects: {relative}")
            if item.is_file():
                archive.add(item, arcname=relative.as_posix(), recursive=False)


def _run(command: list[str]) -> None:
    subprocess.run(command, check=True)


def push_project(source: Path, name: str, host: str) -> None:
    source = validate_source(source, name, host)
    for executable in ("ssh", "scp"):
        if shutil.which(executable) is None:
            raise OSError(
                f"{executable} was not found. Install the Windows OpenSSH Client or your "
                "operating system's OpenSSH tools, then restart VS Code."
            )

    remote_name = f"{name}-{uuid.uuid4().hex}.tar.gz"
    remote_path = f"MotionModule/.uploads/{remote_name}"
    handle, temporary_name = tempfile.mkstemp(prefix="motionmodule-", suffix=".tar.gz")
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        create_archive(source, temporary)
        print(f"Uploading {source} to {host}...")
        _run(["ssh", host, "mkdir -p MotionModule/.uploads"])
        _run(["scp", str(temporary), f"{host}:{remote_path}"])
        _run(["ssh", host, f"motionmodule deploy {name} {remote_path}"])
    finally:
        temporary.unlink(missing_ok=True)
    print(f"{name} is now the active robot project on {host}.")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Upload, activate, and run a local MotionModule robot project"
    )
    parser.add_argument("folder", type=Path, help="Local folder containing robot.py")
    parser.add_argument(
        "--host",
        default=os.environ.get("MOTIONMODULE_ROBOT"),
        help="SSH target, for example angelo@motionmodule.local",
    )
    parser.add_argument("--name", help="Robot project name; defaults to the folder name")
    args = parser.parse_args(argv)
    if not args.host:
        parser.error("--host is required (or set MOTIONMODULE_ROBOT)")
    try:
        push_project(args.folder, args.name or args.folder.name, args.host)
    except (OSError, ValueError, subprocess.CalledProcessError) as error:
        parser.exit(1, f"MotionModule push failed: {error}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
