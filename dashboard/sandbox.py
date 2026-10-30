"""Descriptor-safe reads under explicit plugin/generated/project grants (D10).

No implicit HOME grant, tilde expansion, percent decoding or path reopening.
Windows uses S05's owner-ACL/reparse policy, not chmod as ACL. MIME/signature
checks reuse S07's actual finite media policy; full decoder validation belongs
in the consuming processor. Callers must keep using the returned opened fd.
"""
from __future__ import annotations

from contextlib import ExitStack
import os
from pathlib import Path
import stat

from .ipc_client import ipc, redaction
import importlib
media_cache = importlib.import_module(ipc.__package__ + '.media_cache')


class SandboxRefused(ValueError):
    def __init__(self):
        super().__init__('Local media unavailable.')


def validate_path_syntax(raw):
    failed = False
    try:
        if type(raw) is not str or '\x00' in raw or '..' in raw.replace('\\','/').split('/'):
            raise ValueError
        ipc.validate('dashboard','LocalPathV1',raw)
    except (ValueError,TypeError,OSError):
        failed = True
    if failed:
        raise SandboxRefused()
    return raw


class FileSandbox:
    def __init__(self, *, plugin_root, generated_roots=(), project_roots=(), windows_files=None):
        failed = False
        try:
            self._roots = tuple(Path(validate_path_syntax(str(root))) for root in
                (plugin_root,*generated_roots,*project_roots))
            self._windows = windows_files
            if os.name == 'nt' and self._windows is None:
                self._windows = ipc.WindowsFiles()
            for root in self._roots:
                if not root.is_absolute() or root.resolve(strict=True) != root or not root.is_dir():
                    raise ValueError
        except (ValueError,TypeError,OSError,RuntimeError):
            failed = True
        if failed:
            raise SandboxRefused()

    def open(self, raw, *, mime, kind, max_bytes=None):
        failed = False
        result = None
        try:
            path = Path(validate_path_syntax(raw))
            root = next((r for r in self._roots if path.is_relative_to(r)),None)
            if root is None or not path.is_absolute() or path.resolve(strict=True) != path:
                raise SandboxRefused()
            media_cache._format(path.suffix.lower(),mime,kind)
            cap = media_cache.CATEGORY_CAPS[kind]
            if max_bytes is not None:
                if type(max_bytes) is not int or max_bytes <= 0:
                    raise SandboxRefused()
                cap = min(cap,max_bytes)
            before = path.lstat()
            with ExitStack() as stack:
                if self._windows is not None:
                    # Lock every ancestor against reparse/rename until the
                    # opened-file ACL and fstat validation complete.
                    # S05's private ACL policy applies to the granted tree,
                    # not OS-owned ancestors such as a Windows drive root.
                    for parent in reversed(path.parents):
                        if parent.is_relative_to(root):
                            stack.enter_context(self._windows.directory(parent))
                    fd = self._windows.open(path)
                else:
                    parent_fd = os.open(path.anchor,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NONBLOCK)
                    stack.callback(os.close,parent_fd)
                    current = Path(path.anchor)
                    for part in path.parent.parts[1:]:
                        current /= part
                        parent_fd = os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent_fd)
                        stack.callback(os.close,parent_fd)
                        info = os.fstat(parent_fd)
                        if current.is_relative_to(root) and (info.st_uid != os.getuid() or info.st_mode & 0o022):
                            raise SandboxRefused()
                    fd = os.open(path.name,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=parent_fd)
                stack.callback(os.close,fd)
                info = os.fstat(fd)
                if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                        info.st_size <= 0 or info.st_size > cap or
                        (info.st_dev,info.st_ino) != (before.st_dev,before.st_ino) or
                        (self._windows is None and (info.st_uid != os.getuid() or info.st_mode & 0o022))):
                    raise SandboxRefused()
                media_cache._sniff(os.read(fd,512),path.suffix.lower())
                os.lseek(fd,0,os.SEEK_SET)
                result = os.fdopen(os.dup(fd),'rb')
        except (ValueError,TypeError,OSError,RuntimeError,StopIteration,KeyError):
            failed = True
        if failed:
            raise SandboxRefused()
        return result
