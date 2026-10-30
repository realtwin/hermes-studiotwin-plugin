"""Local-only, per-boot authenticated IPC, frozen v1 envelopes.

Loopback is a deliberate alternative to a platform named-pipe adapter. A private
owner-only descriptor carries a random 256-bit boot secret; the browser/model
never receive it. Request MAC includes scope/generation and direction. Responses
have a separate transport MAC frame (the frozen IpcResponseV1 is unchanged).
Nonce is an unsigned 256-bit big-endian counter encoded as unpadded base64url
(43 characters). One sender per boot; reconnect MUST retain the same Channel.
No nonce eviction: rotate the boot secret when the channel is replaced.

JSON Schema is lazy-loaded only for IPC validation from the pinned MCP 2.3.0
bundle; importing this module needs only stdlib. There is no live installation
or test-helper import. S06 owns value mediation: before it exists the real
server emits ONLY static UNAVAILABLE errors, never raw upstream results.
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
import stat
from threading import RLock
import time
from urllib.parse import urljoin, urlsplit


PROTOCOL = 'studiotwin.host-gateway.v1'
MAX_BYTES = 1048576
CONTRACTS = Path(__file__).resolve().parents[1] / 'contracts'


class Refused(ValueError):
    """Static codes only: never interpolate an envelope, URL, key or exception."""


class VersionRefused(Refused):
    def __init__(self, received):
        super().__init__('INCOMPATIBLE_PROTOCOL_VERSION')
        self.envelope = {'protocol': 'studiotwin.gateway.v1', 'ok': False, 'error': {
            'code': 'INCOMPATIBLE_PROTOCOL_VERSION', 'supported': ['studiotwin.gateway.v1'],
            'received': received if isinstance(received, str) and
                re.fullmatch(r'[A-Za-z0-9._-]{0,64}', received) else None,
            'message': 'Incompatible protocol version.'}}


class WindowsFiles:
    """Private storage policy over an injectable Win32 handle/ACL adapter.

    Directory handles stay open without FILE_SHARE_DELETE during use. Files are
    created with a protected owner-only DACL BEFORE any secret bytes are written.
    Existing foreign-owned files, null/foreign ACLs, unprotected directories and
    reparse points fail closed. Inherited file grants must still be owner-only;
    SQLite may create WAL/SHM this way beneath the locked private directory.
    Only startup may tighten an owner-owned data directory.
    """
    def __init__(self, *, api=None):
        self.api = api if api is not None else _WindowsApi()

    @staticmethod
    def _check(info, *, directory, tightening=False):
        if (info['owner'] != info['user'] or info['reparse'] or
                info['directory'] != directory):
            raise Refused('PRIVATE_STORAGE_REQUIRED')
        if not tightening and ((directory and not info['protected']) or not info['entries'] or
                any(sid != info['user'] or mask != 0x1f01ff for sid, mask in info['entries'])):
            raise Refused('PRIVATE_STORAGE_REQUIRED')

    def directory(self, path, *, tighten=False):
        from contextlib import contextmanager
        @contextmanager
        def locked():
            handle = self.api.open(path, directory=True)
            try:
                self._check(self.api.inspect(handle), directory=True, tightening=tighten)
                if tighten:
                    self.api.secure(handle)
                    self._check(self.api.inspect(handle), directory=True)
                yield
            finally:
                self.api.close(handle)
        return locked()

    def open(self, path, *, create=False, exclusive=False):
        handle = self.api.open(path, create=create, exclusive=exclusive)
        try:
            self._check(self.api.inspect(handle), directory=False)
            fd = self.api.detach(handle)
        except BaseException:
            self.api.close(handle)
            raise
        return fd


class _WindowsApi:
    """Stdlib-only Win32 implementation; loaded only on a native Windows host.

    Handle-based GetSecurityInfo, protected DACLs, current process token SID,
    OPEN_REPARSE_POINT and non-delete-sharing locks (not chmod on Windows).
    The injectable boundary is tested on Linux; native API execution is not.
    """
    def __init__(self):
        import ctypes as c
        from ctypes import wintypes as w
        self.c, self.w = c, w
        self.kernel = c.WinDLL('kernel32', use_last_error=True)
        self.advapi = c.WinDLL('advapi32', use_last_error=True)
        P, D, H, B = c.c_void_p, w.DWORD, w.HANDLE, w.BOOL
        def bind(lib, name, result, *args):
            fn = getattr(lib, name)
            fn.restype, fn.argtypes = result, args
            return fn
        self.close = bind(self.kernel, 'CloseHandle', B, H)
        self.free = bind(self.kernel, 'LocalFree', P, P)
        current = bind(self.kernel, 'GetCurrentProcess', H)
        token = H()
        self._ok(bind(self.advapi, 'OpenProcessToken', B, H, D, c.POINTER(H))(
            current(), 8, c.byref(token)))
        try:
            size = D()
            get_token = bind(self.advapi, 'GetTokenInformation', B, H, c.c_int, P, D, c.POINTER(D))
            get_token(token, 1, None, 0, c.byref(size))
            buffer = c.create_string_buffer(size.value)
            self._ok(get_token(token, 1, buffer, size, c.byref(size)))
            self.sid_text = bind(self.advapi, 'ConvertSidToStringSidW', B, P, c.POINTER(P))
            self.user = self._sid(c.cast(buffer, c.POINTER(P))[0])
        finally:
            self.close(token)
        self.from_sddl = bind(self.advapi, 'ConvertStringSecurityDescriptorToSecurityDescriptorW',
            B, w.LPCWSTR, D, c.POINTER(P), c.POINTER(D))
        self.get_security = bind(self.advapi, 'GetSecurityInfo', D, H, c.c_int, D,
            c.POINTER(P), c.POINTER(P), c.POINTER(P), c.POINTER(P), c.POINTER(P))
        self.get_control = bind(self.advapi, 'GetSecurityDescriptorControl', B, P,
            c.POINTER(w.WORD), c.POINTER(D))
        self.get_ace = bind(self.advapi, 'GetAce', B, P, D, c.POINTER(P))
        self.get_dacl = bind(self.advapi, 'GetSecurityDescriptorDacl', B, P,
            c.POINTER(B), c.POINTER(P), c.POINTER(B))
        self.set_security = bind(self.advapi, 'SetSecurityInfo', D, H, c.c_int, D, P, P, P, P)
        self.create_file = bind(self.kernel, 'CreateFileW', H, w.LPCWSTR, D, D, P, D, D, H)
        self.file_info = bind(self.kernel, 'GetFileInformationByHandle', B, H, P)

    def _ok(self, result):
        if not result:
            raise Refused('PRIVATE_STORAGE_UNAVAILABLE')
        return result

    def _sid(self, pointer):
        c = self.c
        text = c.c_void_p()
        self._ok(self.sid_text(pointer, c.byref(text)))
        try:
            return c.wstring_at(text)
        finally:
            self.free(text)

    def _descriptor(self):
        c = self.c
        sd = c.c_void_p()
        self._ok(self.from_sddl(f'O:{self.user}D:P(A;OICI;FA;;;{self.user})',
            1, c.byref(sd), None))
        return sd

    def open(self, path, *, directory=False, create=False, exclusive=False):
        c, w = self.c, self.w
        class Attributes(c.Structure):
            _fields_ = [('length', w.DWORD), ('descriptor', c.c_void_p), ('inherit', w.BOOL)]
        # No secret exists yet. The owner-owned directory is locked, checked and
        # tightened before creating any child; children inherit that private ACL.
        if directory:
            Path(path).mkdir(parents=True, exist_ok=True)
        sd = self._descriptor()
        attrs = Attributes(c.sizeof(Attributes), sd, False)
        try:
            handle = self.create_file(str(Path(path).absolute()),
                0x60080 if directory else 0xc0000000 | 0x20000,
                3, c.byref(attrs), 1 if exclusive else (4 if create else 3),
                0x200000 | (0x2000000 if directory else 0), None)
            if handle == c.c_void_p(-1).value:
                raise Refused('PRIVATE_STORAGE_UNAVAILABLE')
            return handle
        finally:
            self.free(sd)

    def inspect(self, handle):
        c, w = self.c, self.w
        owner, acl, sd = c.c_void_p(), c.c_void_p(), c.c_void_p()
        if self.get_security(handle, 1, 5, c.byref(owner), None, c.byref(acl), None, c.byref(sd)):
            raise Refused('PRIVATE_STORAGE_UNAVAILABLE')
        try:
            control, revision = w.WORD(), w.DWORD()
            self._ok(self.get_control(sd, c.byref(control), c.byref(revision)))
            entries = None
            if acl.value:
                # ACL header: revision, reserved byte, size WORD, ACE count WORD.
                count = c.c_ushort.from_address(acl.value + 4).value
                entries = []
                for index in range(count):
                    ace = c.c_void_p()
                    self._ok(self.get_ace(acl, index, c.byref(ace)))
                    # Only ACCESS_ALLOWED_ACE; inheritance may carry owner-only
                    # grants to SQLite sidecars, never foreign/conditional grants.
                    kind = c.c_ubyte.from_address(ace.value).value
                    flags = c.c_ubyte.from_address(ace.value + 1).value
                    mask = w.DWORD.from_address(ace.value + 4).value
                    sid = self._sid(ace.value + 8) if kind == 0 else 'unsupported-ace'
                    entries.append((sid if not flags & ~0x13 else 'unsupported-ace-flags', mask))
            # BY_HANDLE_FILE_INFORMATION is thirteen DWORDs including FILETIMEs.
            info = (w.DWORD * 13)()
            self._ok(self.file_info(handle, info))
            return dict(owner=self._sid(owner), user=self.user,
                protected=bool(control.value & 0x1000), entries=entries,
                reparse=bool(info[0] & 0x400), directory=bool(info[0] & 0x10),
                size=(info[8] << 32) | info[9])
        finally:
            self.free(sd)

    def secure(self, handle):
        c, w = self.c, self.w
        sd = self._descriptor()
        try:
            present, defaulted, acl = w.BOOL(), w.BOOL(), c.c_void_p()
            self._ok(self.get_dacl(sd, c.byref(present), c.byref(acl), c.byref(defaulted)))
            if self.set_security(handle, 1, 0x80000004, None, None, acl, None):
                raise Refused('PRIVATE_STORAGE_UNAVAILABLE')
        finally:
            self.free(sd)

    def detach(self, handle):
        import msvcrt
        return msvcrt.open_osfhandle(handle, os.O_RDWR | os.O_BINARY)


def _pairs(items):
    result = {}
    for key, value in items:
        if key in result:
            raise Refused('INVALID_PARAMS')
        result[key] = value
    return result


def _constant(_):
    raise Refused('INVALID_PARAMS')


def _bounds(value):
    pending = [(value, 0)]
    visited = 0
    while pending:
        node, depth = pending.pop()
        visited += 1
        if depth > 48 or visited > 100000:
            raise Refused('INVALID_PARAMS')
        if isinstance(node, dict):
            if any(not isinstance(k, str) for k in node):
                raise Refused('INVALID_PARAMS')
            pending.extend((v, depth + 1) for v in node.values())
        elif isinstance(node, list):
            pending.extend((v, depth + 1) for v in node)


def encode(value):
    try:
        _bounds(value)
        wire = json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        if len(wire) > MAX_BYTES:
            raise Refused('INVALID_PARAMS')
        return wire
    except (ValueError, TypeError, RecursionError):
        raise Refused('INVALID_PARAMS') from None


def decode(wire):
    try:
        if len(wire) > MAX_BYTES:
            raise Refused('INVALID_PARAMS')
        value = json.loads(wire, object_pairs_hook=_pairs, parse_constant=_constant)
        _bounds(value)
        return value
    except (ValueError, TypeError, UnicodeError, RecursionError):
        raise Refused('INVALID_PARAMS') from None


# Resources are local immutable package contracts; registry cannot fetch HTTP refs.
_DOCS = {}
for _name in ('gateway', 'host-gateway', 'dashboard'):
    _file = 'dashboard-v1.openapi.json' if _name == 'dashboard' else _name + '-v1.schema.json'
    _doc = json.loads((CONTRACTS / _file).read_text())
    _uri = 'urn:hermes-studiotwin:contracts:' + _name + '-v1'
    if _name == 'dashboard':
        _doc = {'$schema': 'https://json-schema.org/draft/2020-12/schema',
                '$id': _uri, 'components': _doc['components']}
    _DOCS[_name] = (_uri, _doc)
_REGISTRY = None
_SCHEMA_LOCK = RLock()


def validate(contract, definition, value):
    # Exact frozen validation is lazy: these packages are bundled by pinned MCP,
    # not independent startup dependencies or installed dynamically at runtime.
    from jsonschema import Draft202012Validator
    from referencing import Registry, Resource
    from referencing.jsonschema import DRAFT202012
    global _REGISTRY
    with _SCHEMA_LOCK:
        if _REGISTRY is None:
            _REGISTRY = Registry().with_resources(
                (uri, Resource.from_contents(doc, default_specification=DRAFT202012))
                for uri, doc in _DOCS.values())
    encode(value)  # traversal/bytes/non-finite limits precede the schema walk
    uri, _ = _DOCS[contract]
    fragment = '/components/schemas/' if contract == 'dashboard' else '/$defs/'
    validator = Draft202012Validator({'$ref': uri + '#' + fragment + definition}, registry=_REGISTRY)
    if not validator.is_valid(value):
        raise Refused('INVALID_PARAMS')


def local_address(host):
    try:
        if not ipaddress.ip_address(host).is_loopback or '%' in host:
            raise ValueError
        return host
    except ValueError:
        raise Refused('NON_LOCAL_ADDRESS') from None


def local_redirect(origin, target):
    """Validate BEFORE any network operation; no DNS or redirect request occurs."""
    try:
        base, candidate = urlsplit(origin), urlsplit(urljoin(origin, target))
        for url in (base, candidate):
            if url.scheme != 'http' or url.username is not None or url.password is not None or url.fragment:
                raise ValueError
            local_address(url.hostname)
        if (base.scheme, base.hostname, base.port) != (candidate.scheme, candidate.hostname, candidate.port):
            raise ValueError
        return candidate.geturl()
    except (ValueError, TypeError):
        raise Refused('REDIRECT_REFUSED') from None


class Channel:
    def __init__(self, key, *, scope, generation, clock=None, max_pending=128):
        if not isinstance(key, bytes) or len(key) != 32 or not isinstance(scope, str) or not scope:
            raise Refused('INVALID_BOOTSTRAP')
        if type(generation) is not int or generation < 0 or max_pending < 1:
            raise Refused('INVALID_BOOTSTRAP')
        self._key, self.scope, self.generation = key, scope, generation
        self.clock = clock if clock is not None else lambda: int(time.time() * 1000)
        self.max_pending = max_pending
        self.pending = {}
        self._sent = 0
        self._received = -1
        self._lock = RLock()

    def _mac(self, payload, direction):
        binding = encode([direction, self.scope, self.generation, payload])
        return hmac.new(self._key, b'studiotwin-ipc-v1\0' + binding, hashlib.sha256).hexdigest()

    def request(self, method, params):
        with self._lock:
            if len(self.pending) >= self.max_pending or self._sent >= 2 ** 256 - 1:
                raise Refused('CAPACITY_REACHED')
            self._sent += 1
            request = {'protocol': PROTOCOL, 'requestId': 'rq_' + secrets.token_urlsafe(16),
                'nonce': base64.urlsafe_b64encode(self._sent.to_bytes(32, 'big')).decode().rstrip('='),
                'issuedAtMs': self.clock(), 'method': method, 'params': params}
            request = decode(encode(request))
            request['mac'] = self._mac(request, 'request')
            validate('host-gateway', 'IpcRequestV1', request)
            self.pending[request['requestId']] = (method, request['issuedAtMs'])
            return request

    def accept_request(self, candidate):
        request = decode(encode(candidate))
        if not isinstance(request, dict):
            raise Refused('INVALID_PARAMS')
        # Authenticate even version refusals before replying over the socket.
        # No unauthenticated caller can turn the listener into an echo service.
        mac = request.get('mac')
        if not isinstance(mac, str) or not re.fullmatch('[0-9a-f]{64}', mac):
            raise Refused('BAD_MAC')
        payload = {k: v for k, v in request.items() if k != 'mac'}
        if not hmac.compare_digest(self._mac(payload, 'request'), mac):
            raise Refused('BAD_MAC')
        if request.get('protocol') != PROTOCOL:
            raise VersionRefused(request.get('protocol'))
        validate('host-gateway', 'IpcRequestV1', request)
        if abs(self.clock() - request['issuedAtMs']) > 30000:
            raise Refused('STALE_REQUEST')
        raw = base64.urlsafe_b64decode(request['nonce'] + '=')
        if base64.urlsafe_b64encode(raw).decode().rstrip('=') != request['nonce']:
            raise Refused('INVALID_PARAMS')
        nonce = int.from_bytes(raw, 'big')
        with self._lock:
            if nonce <= self._received:
                raise Refused('REPLAYED_NONCE')
            self._received = nonce
        return request

    def response(self, request, *, payload=None, code=None):
        # A request is supplied by the authenticated dispatch path. There is no
        # user-selectable callback in the pre-S06 server; only static errors.
        response = {'protocol': PROTOCOL, 'requestId': request['requestId'], 'ok': code is None}
        if code is None:
            response['result'] = {'method': request['method'], 'payload': payload}
        else:
            response['error'] = {'code': code, 'message': 'Gateway request unavailable.'}
        return self.seal_response(response)

    def seal_response(self, response):
        validate('host-gateway', 'IpcResponseV1', response)
        snapshot = decode(encode(response))
        return {'envelope': snapshot, 'mac': self._mac(snapshot, 'response')}

    def accept_response(self, frame):
        frame = decode(encode(frame))
        if (not isinstance(frame, dict) or set(frame) != {'envelope', 'mac'}
                or not isinstance(frame['mac'], str)):
            raise Refused('INVALID_PARAMS')
        response = frame['envelope']
        if not hmac.compare_digest(self._mac(response, 'response'), frame['mac']):
            raise Refused('BAD_MAC')
        if isinstance(response, dict) and response.get('protocol') == 'studiotwin.gateway.v1':
            validate('gateway', 'VersionRefusalV1', response)
            refusal = VersionRefused(response['error']['received'])
            refusal.envelope = response  # validated snapshot; no pending ID in this contract
            raise refusal
        validate('host-gateway', 'IpcResponseV1', response)
        with self._lock:
            expected = self.pending.get(response['requestId'])
            if expected is None or (response['ok'] and response['result']['method'] != expected[0]):
                raise Refused('RESPONSE_MISMATCH')
            if abs(self.clock() - expected[1]) > 30000:
                raise Refused('STALE_REQUEST')
            del self.pending[response['requestId']]
        return response

    def clear_pending(self):
        with self._lock:
            self.pending.clear()  # NEVER reset sent/received counters


def read_descriptor(path, *, windows=None):
    """Read the local backend bootstrap using open/fstat, never tool JSON."""
    if windows is None and os.name == 'nt':
        windows = WindowsFiles()
    try:
        path = Path(path)
        if windows is not None:
            with windows.directory(path.parent):
                with os.fdopen(windows.open(path), 'rb') as stream:
                    if os.fstat(stream.fileno()).st_size > 4096:
                        raise Refused('INVALID_BOOTSTRAP')
                    result = decode(stream.read(4097))
        else:
            parent = path.parent.lstat()
            if not stat.S_ISDIR(parent.st_mode) or parent.st_uid != os.getuid() or parent.st_mode & 0o077:
                raise Refused('INVALID_BOOTSTRAP')
            fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(fd, 'rb') as stream:
                info = os.fstat(stream.fileno())
                if (not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or
                        info.st_mode & 0o077 or info.st_size > 4096):
                    raise Refused('INVALID_BOOTSTRAP')
                result = decode(stream.read(4097))
        if (not isinstance(result, dict) or set(result) != {'host', 'port', 'key'} or
                type(result['port']) is not int or not 1 <= result['port'] <= 65535 or
                not isinstance(result['key'], str) or not re.fullmatch('[0-9a-f]{64}', result['key'])):
            raise Refused('INVALID_BOOTSTRAP')
        local_address(result['host'])
        return result
    except (OSError, ValueError, TypeError):
        raise Refused('INVALID_BOOTSTRAP') from None


class LocalServer:
    """Real loopback peer guard plus boot MAC; setup-only, no hosted dispatcher.

    One request per connection. Fixed active-connection cap and read deadline;
    all authenticated calls receive static closed UNAVAILABLE until S06/S11.
    Never follows redirects, resolves external hosts or logs payloads.
    """
    def __init__(self, data, *, windows=None):
        self.windows = windows if windows is not None else (WindowsFiles() if os.name == 'nt' else None)
        self._directory_lock = None
        self.data = Path(data)
        self.channel = Channel(secrets.token_bytes(32), scope='setup', generation=0)
        self._active = set()
        self.server = None
        self.descriptor = self.data / 'gateway-ipc.json'
        self._descriptor_identity = None

    async def __aenter__(self):
        if self.windows is not None:
            lock = self.windows.directory(self.data)
            lock.__enter__()
            self._directory_lock = lock
        else:
            self.data.mkdir(mode=0o700, parents=True, exist_ok=True)
            info = self.data.lstat()
            if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise Refused('INVALID_BOOTSTRAP')
        try:
            self.server = await asyncio.start_server(self._serve, local_address('127.0.0.1'), 0, limit=MAX_BYTES + 1)
            port = self.server.sockets[0].getsockname()[1]
            fd = (self.windows.open(self.descriptor, create=True, exclusive=True)
                  if self.windows is not None else
                  os.open(self.descriptor, os.O_CREAT | os.O_EXCL | os.O_WRONLY | os.O_NOFOLLOW, 0o600))
            with os.fdopen(fd, 'wb') as stream:
                stream.write(encode({'host': '127.0.0.1', 'port': port, 'key': self.channel._key.hex()}))
                stream.flush()
                os.fsync(stream.fileno())
                info = os.fstat(stream.fileno())
                self._descriptor_identity = (info.st_dev, info.st_ino)
            return self
        except BaseException:
            await self.__aexit__(None, None, None)
            raise

    async def _serve(self, reader, writer):
        task = asyncio.current_task()
        if len(self._active) >= 32:
            writer.close()
            await writer.wait_closed()
            return
        self._active.add(task)
        try:
            local_address(writer.get_extra_info('peername')[0])
            line = await asyncio.wait_for(reader.readline(), 3)
            request = self.channel.accept_request(decode(line))
            writer.write(encode(self.channel.response(request, code='UNAVAILABLE')) + b'\n')
            await writer.drain()
        except VersionRefused as refusal:
            validate('gateway', 'VersionRefusalV1', refusal.envelope)
            frame = {'envelope': refusal.envelope,
                     'mac': self.channel._mac(refusal.envelope, 'response')}
            writer.write(encode(frame) + b'\n')
            await writer.drain()
        except (Refused, ValueError, OSError, asyncio.TimeoutError):
            # Invalid unauthenticated frames close the socket without reflection.
            pass
        finally:
            self._active.discard(task)
            writer.close()
            await writer.wait_closed()

    async def __aexit__(self, *_):
        if self.server is not None:
            self.server.close()
            await self.server.wait_closed()
        tasks = list(self._active)
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        if self._descriptor_identity is not None:
            try:
                info = self.descriptor.lstat()
                if (info.st_dev, info.st_ino) == self._descriptor_identity:
                    self.descriptor.unlink()
            except FileNotFoundError:
                pass
        if self._directory_lock is not None:
            self._directory_lock.__exit__(None, None, None)
            self._directory_lock = None
