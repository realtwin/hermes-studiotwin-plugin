"""Local media path checks. No process or authority sandbox is implied."""
from __future__ import annotations

import os
import stat
from contextlib import contextmanager
from pathlib import Path

from fastapi import HTTPException

MIME = {'.glb':'model/gltf-binary', '.gltf':'model/gltf+json', '.fbx':'application/octet-stream',
        '.obj':'model/obj', '.mtl':'text/plain', '.stl':'model/stl', '.usdz':'model/vnd.usdz+zip',
        '.hdr':'image/vnd.radiance', '.exr':'image/x-exr', '.png':'image/png', '.jpg':'image/jpeg',
        '.jpeg':'image/jpeg', '.webp':'image/webp', '.wav':'audio/wav', '.mp3':'audio/mpeg',
        '.ogg':'audio/ogg', '.opus':'audio/ogg', '.flac':'audio/flac', '.mp4':'video/mp4',
        '.json':'application/json', '.tar':'application/x-tar'}
MAX_BYTES = 128 * 1024 * 1024


def readable(raw: str, roots) -> Path:
    if not raw or '\x00' in raw or '..' in raw.replace('\\','/').split('/'):
        raise HTTPException(400, 'an absolute non-traversing path is required')
    path = Path(raw).expanduser()
    if not path.is_absolute():
        raise HTTPException(400, 'path must be absolute')
    if path.suffix.lower() not in MIME:
        raise HTTPException(415, 'unsupported media extension')
    if any(p.is_symlink() for p in (path, *path.parents)):
        raise HTTPException(403, 'symbolic links are not served')
    if not any(path.is_relative_to(Path(r).resolve()) for r in roots):
        raise HTTPException(403, 'outside allowed media folders')
    try:
        st = path.stat()
    except OSError:
        raise HTTPException(404, 'file not found') from None
    if not stat.S_ISREG(st.st_mode):
        raise HTTPException(404, 'file not found')
    if st.st_size > MAX_BYTES:
        raise HTTPException(413, 'media exceeds 128 MiB')
    return path


@contextmanager
def open_media(raw, roots):
    path = readable(raw, roots)
    # Walk from the filesystem root using no-follow descriptors on POSIX, preventing
    # a link swap between validation and reading. Hold the final descriptor throughout.
    fd = None
    try:
        if os.name == 'posix':
            fd = os.open(path.anchor, os.O_RDONLY | os.O_DIRECTORY)
            for part in path.parts[1:-1]:
                new = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
                os.close(fd)
                fd = new
            new = os.open(path.name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=fd)
            os.close(fd)
            fd = new
        else:
            fd = os.open(path, os.O_RDONLY | getattr(os, 'O_BINARY', 0))
        st = os.fstat(fd)
        if not stat.S_ISREG(st.st_mode) or st.st_size > MAX_BYTES:
            raise HTTPException(413, 'invalid or oversized media')
        with os.fdopen(fd, 'rb') as source:
            fd = None
            yield path, source, st
    except OSError:
        raise HTTPException(403, 'media could not be opened safely') from None
    finally:
        if fd is not None:
            os.close(fd)


def local_folder(root: Path, child: str) -> Path:
    folder = root / child
    if any(p.is_symlink() for p in (folder, *folder.parents)):
        raise HTTPException(403, 'storage folder must not be a symbolic link')
    folder.mkdir(parents=True, exist_ok=True)
    return folder
