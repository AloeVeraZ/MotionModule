"""Bounded download of saved robot files, excluding runtime objects and links."""
from __future__ import annotations

import io
import os
import stat
import zipfile
from pathlib import Path

from .deploy import EXCLUDED_PARTS, validate_project_name
from .errors import MotionModuleError

MAX_EXPORT_BYTES = 32 * 1024 * 1024
MAX_EXPORT_FILES = 2000


def project_archive(project: Path) -> io.BytesIO:
    project = project.resolve(strict=True)
    if not (project / 'robot.py').is_file():
        raise MotionModuleError('The active folder has no robot.py to download.')
    name = validate_project_name(project.name)
    archive = io.BytesIO()
    total = count = 0
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as output:
        for folder, directories, files in os.walk(project, followlinks=False):
            directories[:] = sorted(d for d in directories
                                    if d not in EXCLUDED_PARTS
                                    and not (Path(folder) / d).is_symlink()
                                    and not getattr(Path(folder) / d, 'is_junction', lambda: False)())
            for filename in sorted(files):
                source = Path(folder) / filename
                if source.suffix in {'.pyc', '.pyo'} or not stat.S_ISREG(source.lstat().st_mode):
                    continue
                count += 1
                if count > MAX_EXPORT_FILES:
                    raise MotionModuleError('Robot download exceeds 2,000 files. Copy the folder over SSH instead.')
                # O_NOFOLLOW also rejects a symlink swapped in during traversal
                # on the Pi. Never follow a link out of the owner's project.
                descriptor = os.open(source, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
                with os.fdopen(descriptor, 'rb') as stream:
                    if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode):
                        raise MotionModuleError('A project file changed during download. Try again.')
                    data = stream.read(MAX_EXPORT_BYTES - total + 1)
                total += len(data)
                if total > MAX_EXPORT_BYTES:
                    raise MotionModuleError('Robot download exceeds 32 MiB. Copy the folder over SSH instead.')
                output.writestr(f'{name}/{source.relative_to(project).as_posix()}', data)
    archive.seek(0)
    return archive
