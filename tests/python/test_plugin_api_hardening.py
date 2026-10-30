"""S11 local-read hardening: actual descriptors, no network or broad HOME grant.

Adapted test ideas from meshy/tests/test_plugin_api_hardening.py @
1e326ddd28ae261821d7714d106fe114999a0bba (MIT; Copyright (c) 2025 Nous Research).
No provider HTTP or task assumptions are retained.
"""
import importlib
import os
from pathlib import Path
import socket
import stat

import pytest
from tests.python.test_dashboard_core import D

S = importlib.import_module('s11_dashboard.sandbox')
PNG = b'\x89PNG\r\n\x1a\n' + b'\0'*50


def setup(tmp_path):
    root = tmp_path/'My Project'/'.hidden'
    root.mkdir(parents=True,mode=0o700)
    path = root/'view.png'
    path.write_bytes(PNG)
    path.chmod(0o600)
    return S.FileSandbox(plugin_root=root), root, path


def test_spaces_hidden_dirs_explicit_project_grant_and_checked_fd(tmp_path):
    box, root, path = setup(tmp_path)
    with box.open(str(path),mime='image/png',kind='image') as stream:
        assert stream.read() == PNG
        assert stat.S_ISREG(os.fstat(stream.fileno()).st_mode)
    project = tmp_path/'user project'
    project.mkdir(mode=0o700)
    copy = project/'other.png'
    copy.write_bytes(PNG)
    copy.chmod(0o600)
    with pytest.raises(S.SandboxRefused): box.open(str(copy),mime='image/png',kind='image')
    granted = S.FileSandbox(plugin_root=root,project_roots=[project])
    with granted.open(str(copy),mime='image/png',kind='image') as stream:
        assert stream.read() == PNG


@pytest.mark.parametrize('raw',['relative.png','/etc/passwd','/ok/../view.png','/ok/\0.png','/ok/%2e%2e/view.png'])
def test_path_syntax_and_unapproved_roots(tmp_path,raw):
    box,_,_ = setup(tmp_path)
    with pytest.raises(S.SandboxRefused): box.open(raw,mime='image/png',kind='image')


@pytest.mark.parametrize('raw',['C:/Users/alice/My Project/.hidden/view.png','/home/alice/.hermes/My Project/view.png'])
def test_portable_syntax_does_not_itself_authorize_access(raw):
    assert S.validate_path_syntax(raw) == raw


@pytest.mark.parametrize('raw',['C:/Users/alice/../view.png','C:\\Users\\alice\\..\\view.png','C:/Users/alice/view.png\0','C:relative.png'])
def test_windows_traversal_and_drive_relative_refused(raw):
    with pytest.raises(S.SandboxRefused): S.validate_path_syntax(raw)


@pytest.mark.parametrize('kind',['leaf_link','ancestor_link','fifo','directory','socket','hardlink'])
def test_nonregular_and_linked_files_refused_without_blocking(tmp_path,kind):
    box,root,path = setup(tmp_path)
    victim = tmp_path/'outside.png'
    victim.write_bytes(PNG)
    victim.chmod(0o600)
    sock = None
    if kind == 'leaf_link':
        path.unlink(); path.symlink_to(victim)
    if kind == 'ancestor_link':
        (root/'alias').symlink_to(root,target_is_directory=True); path = root/'alias'/'view.png'
    if kind == 'fifo': path.unlink(); os.mkfifo(path,0o600)
    if kind == 'directory': path.unlink(); path.mkdir()
    if kind == 'socket':
        path.unlink(); sock = socket.socket(socket.AF_UNIX)
        directory_fd = os.open(root,os.O_RDONLY|os.O_DIRECTORY)
        try:
            sock.bind(f'/proc/self/fd/{directory_fd}/{path.name}')
        finally:
            os.close(directory_fd)
    if kind == 'hardlink': path.unlink(); os.link(victim,path)
    try:
        with pytest.raises(S.SandboxRefused): box.open(str(path),mime='image/png',kind='image')
        assert victim.read_bytes() == PNG
    finally:
        if sock: sock.close()


@pytest.mark.parametrize('change',['size','mime','sniff','suffix','permissions'])
def test_content_type_size_and_ownership_policy(tmp_path,change):
    box,root,path = setup(tmp_path)
    if change=='size': path.write_bytes(PNG*100)
    if change=='sniff': path.write_bytes(b'<script>not PNG</script>')
    if change=='suffix': path = path.rename(root/'view.html')
    if change=='permissions': path.chmod(0o666)
    with pytest.raises(S.SandboxRefused):
        box.open(str(path),mime='text/html' if change=='mime' else 'image/png',kind='image',max_bytes=100)


def test_fstat_is_on_opened_fd_before_read_and_swap_refused(tmp_path,monkeypatch):
    box,root,path = setup(tmp_path)
    replacement = root/'swap.png'
    replacement.write_bytes(PNG+b'changed')
    replacement.chmod(0o600)
    real = os.open
    calls = []
    def swapping(name,flags,*args,**kw):
        if str(name) == path.name:
            assert flags & os.O_NOFOLLOW and flags & os.O_NONBLOCK
            replacement.replace(path)
            calls.append('swap')
        return real(name,flags,*args,**kw)
    monkeypatch.setattr(os,'open',swapping)
    with pytest.raises(S.SandboxRefused): box.open(str(path),mime='image/png',kind='image')
    assert calls == ['swap']


def test_opened_descriptor_not_reopened_by_path(tmp_path):
    box,root,path = setup(tmp_path)
    with box.open(str(path),mime='image/png',kind='image') as stream:
        path.unlink()
        path.write_bytes(b'wrong inode')
        assert stream.read() == PNG


def test_sanitized_refusal_has_no_raw_path_or_exception_context(tmp_path):
    box,root,path = setup(tmp_path)
    with pytest.raises(S.SandboxRefused) as e:
        box.open(str(root/'secret-name.png'),mime='image/png',kind='image')
    assert str(e.value) == 'Local media unavailable.'
    assert e.value.__cause__ is None and e.value.__context__ is None


@pytest.mark.parametrize('unsafe',[None,'owner','foreign','null','reparse'])
def test_windows_actual_s05_acl_seam_on_granted_tree(tmp_path,unsafe):
    from tests.python.test_ipc import WindowsApiFixture
    box,root,path = setup(tmp_path)
    class Api(WindowsApiFixture):
        def __init__(self):
            super().__init__()
            self.paths = {}
        def open(self,path,**kw):
            fd = super().open(path,**kw)
            self.paths[fd] = Path(path)
            return fd
        def inspect(self,fd):
            info = super().inspect(fd)
            if not self.paths[fd].is_relative_to(root):
                info['entries'] = [('system-users',1)]
            if self.paths[fd] == path:
                if unsafe=='owner': info['owner'] = 'other'
                if unsafe=='foreign': info['entries'] = [('other',1)]
                if unsafe=='null': info['entries'] = None
                if unsafe=='reparse': info['reparse'] = True
            return info
    api = Api()
    box = S.FileSandbox(plugin_root=root,windows_files=D.ipc.WindowsFiles(api=api))
    if unsafe:
        with pytest.raises(S.SandboxRefused): box.open(str(path),mime='image/png',kind='image')
    else:
        with box.open(str(path),mime='image/png',kind='image') as stream:
            assert stream.read() == PNG
    assert not any(p == Path('/') for p in api.paths.values())
