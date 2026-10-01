"""Snapshot existing robot code before an install; never edit the live projects."""
from __future__ import annotations

import argparse
import json
import shutil
import stat
from pathlib import Path


def snapshot_projects(robots: Path, backups: Path, name: str, *, legacy_workspace: Path | None = None) -> Path | None:
    if not name or Path(name).name != name or name in {".", ".."} or "/" in name or "\\" in name:
        raise ValueError("Snapshot name must be one directory name")
    if backups.resolve().is_relative_to(robots.resolve()):
        raise ValueError("Code backups must be outside the robot projects directory")
    projects = []
    for label, folder in (("robots", robots), ("legacy", legacy_workspace)):
        if folder is None or not folder.is_dir():
            continue
        for project in sorted(folder.iterdir()):
            if project.name != "active" and project.is_dir() and (project / "robot.py").is_file():
                projects.append((label, project))
    if not projects:
        return None
    destination = backups / name
    destination.mkdir(parents=True, exist_ok=False)
    skipped_runtime_objects = []

    def ignore_runtime_objects(folder, names):
        ignored = []
        for entry in names:
            path = Path(folder) / entry
            mode = path.lstat().st_mode
            # GPIO notification FIFOs (.lgd-nfy*) and sockets describe running
            # processes, not saved project data. copytree cannot copy them.
            # Use the file type, not its name; keep all regular files and links.
            if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode) or stat.S_ISLNK(mode)):
                ignored.append(entry)
                skipped_runtime_objects.append(str(path))
        return ignored

    for label, project in projects:
        shutil.copytree(project, destination / label / project.name, symlinks=True,
                        ignore=ignore_runtime_objects)
    active = legacy_workspace / "active" if legacy_workspace is not None else None
    manifest = {
        "projects": [str(project) for _, project in projects],
        "active_project": str(active.resolve()) if active is not None and active.is_symlink() else None,
        "skipped_runtime_objects": skipped_runtime_objects,
        "note": "Robot code snapshot before a runtime update; live project files were not modified.",
    }
    (destination / "snapshot.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return destination


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("robots", type=Path)
    parser.add_argument("backups", type=Path)
    parser.add_argument("name")
    parser.add_argument("--legacy-workspace", type=Path)
    args = parser.parse_args(argv)
    destination = snapshot_projects(args.robots, args.backups, args.name, legacy_workspace=args.legacy_workspace)
    if destination is not None:
        print(f"Robot code is preserved in place; pre-update snapshot: {destination}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
