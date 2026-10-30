"""S07 private scoped cache and opened-file sandbox (no network).

One cache owner per gateway data directory (S05 provides process ownership).
Quota is cumulative across scopes and includes restart-discovered cache files.
Pins are encoded only in random local filenames, never in handle tokens; they
survive restart. Scope/generation is authenticated by the caller, not a path.
"""
from __future__ import annotations

from contextlib import ExitStack, contextmanager
from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import secrets
import stat
from threading import RLock
import time
import weakref

from .handles import HandleStore, HandleNotFound
from .redaction import _binding

DEFAULT_QUOTA = 2 * 1024 * 1024 * 1024
DEFAULT_TTL = 30 * 24 * 60 * 60
CATEGORY_CAPS = {'model':128*1024*1024, 'audio':60*1024*1024,
                 'image':128*1024*1024, 'video':128*1024*1024,
                 'environment':128*1024*1024, 'motion':128*1024*1024,
                 'manifest':1024*1024, 'material':128*1024*1024, 'other':1024*1024}
_FORMATS = {'.png':{'image/png'}, '.jpg':{'image/jpeg'}, '.jpeg':{'image/jpeg'},
            '.webp':{'image/webp'}, '.hdr':{'image/vnd.radiance','image/x-hdr'},
            '.exr':{'image/x-exr'}, '.glb':{'model/gltf-binary'},
            '.gltf':{'model/gltf+json'}, '.wav':{'audio/wav','audio/x-wav'},
            '.mp3':{'audio/mpeg'}, '.flac':{'audio/flac'}, '.ogg':{'audio/ogg'},
            '.opus':{'audio/ogg','audio/opus'}, '.mp4':{'video/mp4'},
            '.webm':{'video/webm'}, '.json':{'application/json'}}
_KIND_MIMES = {'model':('model/',), 'audio':('audio/',), 'video':('video/',),
               'image':('image/',), 'environment':('image/',), 'material':('image/',),
               'motion':('model/','application/json'), 'manifest':('application/json',),
               'other':('application/json',)}


class MediaRefused(ValueError):
    def __init__(self):
        super().__init__('Media unavailable.')


def _format(extension, mime, kind):
    if (kind not in CATEGORY_CAPS or extension not in _FORMATS or
            mime not in _FORMATS[extension] or not mime.startswith(_KIND_MIMES[kind])):
        raise MediaRefused()


def _sniff(head, extension):
    checks = {
        '.png':lambda:head.startswith(b'\x89PNG\r\n\x1a\n'),
        '.jpg':lambda:head.startswith(b'\xff\xd8\xff'),
        '.jpeg':lambda:head.startswith(b'\xff\xd8\xff'),
        '.webp':lambda:head[:4]==b'RIFF' and head[8:12]==b'WEBP',
        '.hdr':lambda:head.startswith((b'#?RADIANCE',b'#?RGBE')),
        '.exr':lambda:head.startswith(b'v/1\x01'),
        '.glb':lambda:head.startswith(b'glTF\x02\0\0\0'),
        '.wav':lambda:head[:4]==b'RIFF' and head[8:12]==b'WAVE',
        '.mp3':lambda:head.startswith(b'ID3') or (len(head)>1 and head[0]==255 and head[1]&224==224),
        '.flac':lambda:head.startswith(b'fLaC'),
        '.ogg':lambda:head.startswith(b'OggS'),
        '.opus':lambda:head.startswith(b'OggS') and b'OpusHead' in head,
        '.mp4':lambda:head[4:8]==b'ftyp',
        '.webm':lambda:head.startswith(b'\x1aE\xdf\xa3'),
        '.json':lambda:head.lstrip().startswith((b'{',b'[')),
        '.gltf':lambda:head.lstrip().startswith(b'{'),
    }
    if not checks[extension]():
        raise MediaRefused()


@dataclass(frozen=True, slots=True)
class CachedMedia:
    path: str
    handle: str
    scope_id: str
    generation: int
    mime: str
    kind: str
    size: int


class MediaCache:
    def __init__(self, root, handles: HandleStore, *, quota=DEFAULT_QUOTA,
                 ttl=DEFAULT_TTL, clock=time.time, windows_files=None):
        self.root = Path(root)
        if (not self.root.is_absolute() or self.root.name != 'hermes-studiotwin' or
                type(quota) is not int or not 0 < quota <= DEFAULT_QUOTA or
                type(ttl) not in (int,float) or not 0 < ttl <= DEFAULT_TTL):
            raise MediaRefused()
        self.handles, self.quota, self.ttl, self.clock = handles, quota, ttl, clock
        self._windows = windows_files
        if os.name == 'nt' and self._windows is None:
            from .ipc import WindowsFiles
            self._windows = WindowsFiles()
        self._lock = RLock()
        self._streams = {}
        self._batch = None
        self._mkdir(self.root)
        if self.root.resolve(strict=True) != self.root:
            raise MediaRefused()

    def _mkdir(self, path):
        # Only root's parent is provisioned externally; descendants are private.
        # Creation itself is anchored: rejecting a followed link AFTER mkdir
        # would still have modified a foreign directory.
        failed=False
        try:
            with ExitStack() as stack:
                if self._windows is not None:
                    if path.parent.resolve(strict=True) != path.parent:
                        raise MediaRefused()
                    stack.enter_context(self._windows.directory(path.parent))
                    created=False
                    try:
                        path.mkdir(mode=0o700)
                        created=True
                    except FileExistsError:
                        pass
                    with self._windows.directory(path,tighten=created):
                        pass
                else:
                    parent=self._parent_fd(path,stack)
                    try:
                        os.mkdir(path.name,mode=0o700,dir_fd=parent)
                    except FileExistsError:
                        pass
                    st=os.stat(path.name,dir_fd=parent,follow_symlinks=False)
                    if not stat.S_ISDIR(st.st_mode) or st.st_uid != os.getuid() or st.st_mode & 0o077:
                        raise MediaRefused()
        except (OSError,ValueError):
            failed=True
        if failed:
            raise MediaRefused()

    def _directory(self, scope_id, generation):
        self.handles.bind(scope_id,generation)
        current = self.root
        for part in ('scopes',scope_id,'media'):
            current /= part
            self._mkdir(current)
        return current

    def _relative(self, path, scope_id, generation):
        self.handles.bind(scope_id,generation)
        path = Path(path)
        if not path.is_absolute() or '..' in path.parts or '\x00' in str(path):
            raise MediaRefused()
        relative = path.relative_to(self.root/'scopes'/scope_id/'media')
        if len(relative.parts) != 1 or not re.fullmatch(r'[pu]_'+f'{generation:016x}'+r'_[0-9a-f]{64}\.[a-z0-9]{2,5}',relative.name):
            raise MediaRefused()
        if path.resolve(strict=True) != path:
            raise MediaRefused()
        return path

    def _parent_fd(self, path, stack):
        """Walk from / with dirfds: no symlinked ancestor or check/open race."""
        fd = os.open(path.anchor, os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        stack.callback(os.close,fd)
        private = False
        current = Path(path.anchor)
        for part in path.parent.parts[1:]:
            current /= part
            fd = os.open(part,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=fd)
            stack.callback(os.close,fd)
            if current == self.root:
                private = True
            # The exact private subtree is also checked independently of names.
            info=os.fstat(fd)
            if private and (info.st_uid != os.getuid() or info.st_mode & 0o077):
                raise MediaRefused()
        return fd

    def _raw_open(self, path, stack, *, create=False):
        if self._windows is not None:
            # S05 seam holds each directory against reparse/rename, checks ACL
            # on the exact file handle and opens without FILE_SHARE_DELETE.
            for ancestor in (self.root, self.root/'scopes',path.parent.parent,path.parent):
                stack.enter_context(self._windows.directory(ancestor))
            fd=self._windows.open(path,create=create,exclusive=create)
        else:
            parent=self._parent_fd(path,stack)
            flags=(os.O_WRONLY|os.O_CREAT|os.O_EXCL if create else os.O_RDONLY)
            fd=os.open(path.name, flags|os.O_NOFOLLOW|os.O_NONBLOCK,0o600,dir_fd=parent)
        stack.callback(os.close,fd)
        return fd

    def open(self, path, *, scope_id, generation, mime, kind):
        failed=False
        result=None
        try:
            with self._lock, ExitStack() as stack:
                path=self._relative(path,scope_id,generation)
                _format(path.suffix,mime,kind)
                before=path.lstat()
                fd=self._raw_open(path,stack)
                info=os.fstat(fd)
                if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                        info.st_size <= 0 or info.st_size > CATEGORY_CAPS[kind] or
                        (info.st_dev,info.st_ino)!=(before.st_dev,before.st_ino) or
                        (self._windows is None and (info.st_uid != os.getuid() or info.st_mode & 0o077))):
                    raise MediaRefused()
                head=os.read(fd,512)
                _sniff(head,path.suffix)
                os.lseek(fd,0,os.SEEK_SET)
                # TTL is sliding idle age; pinned items do not expire.
                if path.name.startswith('u_') and self.clock()-info.st_mtime >= self.ttl:
                    raise MediaRefused()
                os.utime(fd,(self.clock(),self.clock()))
                # dup keeps the checked inode, not a reopened pathname.
                result=os.fdopen(os.dup(fd),'rb')
                self._streams.setdefault(scope_id,weakref.WeakSet()).add(result)
        except (OSError,ValueError,TypeError):
            failed=True
        if failed:
            raise MediaRefused()
        return result

    @contextmanager
    def batch(self):
        """Retain allocations through publication, rolling back on ANY failure.

        A tentative result may not evict unrelated files: rollback must preserve
        their bytes and handles too. Batches conservatively use free quota only;
        normal explicit evict()/standalone put() still provide unpinned LRU.
        The owner lock prevents competing batches/writes from self-evicting.
        """
        with self._lock:
            if self._batch is not None:
                raise MediaRefused()
            allocated=[]
            self._batch=allocated
            try:
                yield
                for item in allocated:
                    with self.open(item.path,scope_id=item.scope_id,generation=item.generation,
                                   mime=item.mime,kind=item.kind):
                        pass
            except BaseException:
                for item in reversed(allocated):
                    self.handles.revoke(item.handle)
                    self._unlink(Path(item.path))
                raise
            finally:
                self._batch=None

    def put(self, *, scope_id, generation, data, mime, kind, extension, pinned=False):
        failed=False
        result=None
        path=None
        try:
            with self._lock:
                _binding(scope_id,generation)
                _format(extension,mime,kind)
                if type(data) is not bytes or not 0 < len(data) <= CATEGORY_CAPS[kind] or type(pinned) is not bool:
                    raise MediaRefused()
                _sniff(data[:512],extension)
                parent=self._directory(scope_id,generation)
                self.evict(reserve=len(data))
                path=parent/(('p_' if pinned else 'u_')+f'{generation:016x}_'+secrets.token_hex(32)+extension)
                with ExitStack() as stack:
                    fd=self._raw_open(path,stack,create=True)
                    view=memoryview(data)
                    while view:
                        count=os.write(fd,view)
                        if count <= 0:
                            raise MediaRefused()
                        view=view[count:]
                    os.fsync(fd)
                    os.utime(fd,(self.clock(),self.clock()))
                # The exact consumer sandbox is exercised before publishing.
                with self.open(path,scope_id=scope_id,generation=generation,mime=mime,kind=kind):
                    pass
                token=self.handles.mint(scope_id=scope_id,generation=generation,purpose='resource',
                    kind=kind,role='media',mime=mime,size=len(data),target={'localPath':str(path)},
                    ttl=min(self.ttl,2592000),operations=('read','process'),max_reads=1000000)
                result=CachedMedia(str(path),token,scope_id,generation,mime,kind,len(data))
                if self._batch is not None:
                    self._batch.append(result)
        except (OSError,ValueError,TypeError):
            failed=True
            if path is not None:
                self._unlink(path)
        if failed:
            raise MediaRefused()
        return result

    def media_line(self, item, *, scope_id, generation):
        if item.scope_id != scope_id or item.generation != generation:
            raise MediaRefused()
        with self.open(item.path,scope_id=scope_id,generation=generation,mime=item.mime,kind=item.kind):
            pass
        return 'MEDIA:'+item.path

    def _list(self, directory):
        """Enumerate through a checked directory handle, never a followed link."""
        failed=False
        result=None
        try:
            with ExitStack() as stack:
                if directory.resolve(strict=True) != directory:
                    raise MediaRefused()
                if self._windows is not None:
                    current=self.root
                    stack.enter_context(self._windows.directory(current))
                    for part in directory.relative_to(self.root).parts:
                        current /= part
                        stack.enter_context(self._windows.directory(current))
                    result=list(directory.iterdir())
                else:
                    fd=self._parent_fd(directory/'unused',stack)
                    result=[directory/name for name in os.listdir(fd)]
        except (OSError,ValueError):
            failed=True
        if failed:
            raise MediaRefused()
        return result

    def _unlink(self, path):
        with ExitStack() as stack:
            if self._windows is not None:
                current=self.root
                stack.enter_context(self._windows.directory(current))
                for part in path.parent.relative_to(self.root).parts:
                    current /= part
                    stack.enter_context(self._windows.directory(current))
                path.unlink(missing_ok=True)
            else:
                fd=self._parent_fd(path,stack)
                try:
                    os.unlink(path.name,dir_fd=fd)
                except FileNotFoundError:
                    pass

    def evict(self, *, reserve=0):
        """No recursion through links. Unknown entries refuse, not invisible quota."""
        with self._lock:
            entries=[]
            scopes=self.root/'scopes'
            if scopes.exists():
                for scope in self._list(scopes):
                    if not re.fullmatch('[0-9a-f]{64}',scope.name) or scope.is_symlink():
                        raise MediaRefused()
                    media=scope/'media'
                    if not media.exists():
                        continue
                    if media.is_symlink():
                        raise MediaRefused()
                    for path in self._list(media):
                        info=path.lstat()
                        if (not stat.S_ISREG(info.st_mode) or info.st_nlink != 1 or
                                not re.fullmatch(r'[pu]_[0-9a-f]{16}_[0-9a-f]{64}\.[a-z0-9]{2,5}',path.name)):
                            raise MediaRefused()
                        entries.append((info.st_mtime,path,info.st_size,path.name.startswith('p_'),scope.name))
            total=sum(e[2] for e in entries)
            if self._batch is not None:
                # Actual cumulative bytes include unknown-size loaded resources,
                # manifests, existing pins and every in-flight batch allocation.
                if total+reserve > self.quota:
                    raise MediaRefused()
                return
            for modified,path,size,pinned,scope in sorted(entries):
                if not pinned and (self.clock()-modified >= self.ttl or total+reserve > self.quota):
                    self._unlink(path)
                    self.handles.invalidate_target(scope,str(path))
                    total-=size
            if total+reserve > self.quota:
                raise MediaRefused()

    def purge_scope(self, scope_id):
        _binding(scope_id,0)
        with self._lock:
            self.handles.purge_scope(scope_id)
            for stream in self._streams.pop(scope_id,()):
                stream.close()
            media=self.root/'scopes'/scope_id/'media'
            if not media.exists():
                return
            if media.is_symlink() or media.resolve(strict=True)!=media:
                raise MediaRefused()
            for path in self._list(media):
                if path.is_dir() and not path.is_symlink():
                    raise MediaRefused()
                self._unlink(path)

    def rotate(self, scope_id, generation):
        with self._lock:
            self.purge_scope(scope_id)
            self.handles.rotate(scope_id,generation)
