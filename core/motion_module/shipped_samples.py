"""Give a robot folder this release's sample when nobody has edited it.

An install never writes over `~/MotionModule/robots/<name>`: that folder is
the robot's own, and the work someone does on the robot lives in it. A folder
that still holds an untouched copy of a sample MotionModule shipped holds no
such work, though, so until now a fix to a sample — a motor's `inverted`
value, a correction in the drive math — never reached a Pi that already had
the sample. It went on running the copy it was first given.

The installer runs this on every install, before the new release starts. A
robot folder whose every file is a copy this project has shipped is given the
sample this release ships, and the folder it replaces is kept under
`~/MotionModule/backups`, beside the copies a dashboard deployment makes. One
file that is edited, added or the robot's own is enough to leave the whole
folder alone: the sample is then only a starting point someone built on.

`shipped_samples.json` beside this file lists every copy of every sample
MotionModule shipped up to 20 September 2026, as the SHA-256 of its contents
with Unix line endings. It does not need entries for later ones: an install
also counts the sample in the release it replaces, so a folder this step
updates is recognised by the install after it.

    python -m motion_module.shipped_samples ROBOTS_DIRECTORY BACKUPS_DIRECTORY
        [--released-with EXAMPLES_DIRECTORY]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import uuid
from pathlib import Path, PurePosixPath

from .deploy import replace_project


EXAMPLES_DIRECTORY = Path(__file__).resolve().parents[2] / "examples"
SHIPPED_SAMPLES_PATH = Path(__file__).with_name("shipped_samples.json")
IGNORED_DIRECTORIES = {"__pycache__"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}
# Copies the retired-wiring move keeps beside a pin map it replaced. They are
# this software's own backups, not anybody's work.
KEPT_BACKUP_MARKER = ".retired-wiring"


def _ignored(relative: PurePosixPath) -> bool:
    """True for files a robot folder collects by being run or upgraded."""

    return any(
        part in IGNORED_DIRECTORIES or part.startswith(".") or KEPT_BACKUP_MARKER in part
        for part in relative.parts
    ) or relative.suffix in IGNORED_SUFFIXES


def digest(data: bytes) -> str:
    """The digest of one file's contents, however its lines end."""

    return hashlib.sha256(data.replace(b"\r\n", b"\n")).hexdigest()


def folder_digests(folder: Path) -> dict[str, str | None]:
    """Every file in a robot folder or sample, as path -> digest.

    A symbolic link or an unreadable file gets None, which matches no copy
    this project shipped, so the folder holding it counts as the robot's own.
    """

    digests: dict[str, str | None] = {}
    for path in sorted(folder.rglob("*")):
        relative = PurePosixPath(path.relative_to(folder).as_posix())
        if _ignored(relative):
            continue
        if path.is_dir() and not path.is_symlink():
            continue
        try:
            digests[str(relative)] = None if path.is_symlink() else digest(path.read_bytes())
        except OSError:
            digests[str(relative)] = None
    return digests


def shipped_digests() -> dict[str, dict[str, set[str]]]:
    """Every copy of every sample this project shipped, as sample -> path -> digests."""

    try:
        document = json.loads(SHIPPED_SAMPLES_PATH.read_text(encoding="utf-8"))
        return {
            name: {path: set(digests) for path, digests in paths.items()}
            for name, paths in document["samples"].items()
        }
    except (OSError, ValueError, LookupError, AttributeError, TypeError):
        # Without the list, only the samples this release and the one it
        # replaces ship are recognised. Robot folders are still never lost.
        return {}


def _also_shipped(shipped: dict[str, dict[str, set[str]]], examples: Path) -> None:
    """Count the samples in an examples directory as copies this project shipped."""

    for example in _samples(examples):
        known = shipped.setdefault(example.name, {})
        for path, value in folder_digests(example).items():
            if value is not None:
                known.setdefault(path, set()).add(value)


def _samples(examples: Path) -> list[Path]:
    """The sample robot projects in an examples directory."""

    try:
        return sorted(path for path in examples.iterdir() if (path / "robot.py").is_file())
    except OSError:
        return []


def _named(paths: list[str], limit: int = 3) -> str:
    """The first few file names, as a sentence reads them."""

    if len(paths) > limit:
        return f"{', '.join(paths[:limit])} and {len(paths) - limit} more"
    if len(paths) > 1:
        return f"{', '.join(paths[:-1])} and {paths[-1]}"
    return paths[0]


def _give_sample(example: Path, target: Path, backups: Path) -> Path | None:
    """Put the shipped sample where the robot folder is, keeping the old folder."""

    staging = target.with_name(f".{target.name}.sample-{uuid.uuid4().hex}")
    try:
        shutil.copytree(
            example, staging, ignore=shutil.ignore_patterns(*IGNORED_DIRECTORIES, "*.pyc")
        )
        backups.mkdir(parents=True, exist_ok=True)
        return replace_project(staging, target, backups, target.name)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def refresh_untouched_samples(
    robots_directory: str | os.PathLike[str],
    backups_directory: str | os.PathLike[str],
    released_with: str | os.PathLike[str] | None = None,
) -> list[str]:
    """Update every robot folder that is still a shipped sample and say what changed.

    `released_with` is the examples directory of the release this install
    replaces, whose samples count as shipped copies as well.
    """

    robots = Path(robots_directory)
    backups = Path(backups_directory)
    shipped = shipped_digests()
    if released_with is not None:
        _also_shipped(shipped, Path(released_with))

    messages = []
    for example in _samples(EXAMPLES_DIRECTORY):
        name = example.name
        target = robots / name
        if target.is_symlink() or not target.is_dir():
            continue
        release = folder_digests(example)
        current = folder_digests(target)
        if current == release:
            continue
        known = shipped.get(name, {})
        own = sorted(
            path
            for path, value in current.items()
            if value is None or (value != release.get(path) and value not in known.get(path, set()))
        )
        if own:
            messages.append(
                f"Kept {target} as it is: {_named(own)} "
                f"{'is' if len(own) == 1 else 'are'} this robot's own, so the {name} sample this "
                "release ships was not copied over it. The dashboard's Code page has that sample "
                "to download whenever you want it."
            )
            continue
        try:
            backup = _give_sample(example, target, backups)
        except OSError as error:
            messages.append(
                f"Could not give {target} the {name} sample this release ships: {error}. "
                "The folder was left as it is."
            )
            continue
        messages.append(
            f"Updated {target} to the {name} sample this release ships; it still held an "
            f"untouched copy of an older one. That copy is kept at {backup}. Motors may turn "
            "differently now, so test each wheel with the robot raised before driving."
        )
    return messages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Give robot folders nobody has edited the samples this release ships"
    )
    parser.add_argument("robots_directory", type=Path)
    parser.add_argument("backups_directory", type=Path)
    parser.add_argument(
        "--released-with",
        type=Path,
        default=None,
        help="the examples directory of the release this install replaces",
    )
    args = parser.parse_args(argv)
    for message in refresh_untouched_samples(
        args.robots_directory, args.backups_directory, args.released_with
    ):
        print(message)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
