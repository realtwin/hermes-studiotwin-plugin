"""Authenticated local wire tests; no StudioTwin connection or paid calls."""
import asyncio
import copy
import importlib.util
import json
from pathlib import Path
import sys
import types

import pytest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
pkg = types.ModuleType('s05_ipc')
pkg.__path__ = [str(ROOT / 'gateway')]
sys.modules[pkg.__name__] = pkg
spec = importlib.util.spec_from_file_location('s05_ipc.ipc', ROOT / 'gateway/ipc.py')
ipc = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = ipc
spec.loader.exec_module(ipc)
KEY = b'k' * 32  # explicit offline 256-bit fixture, never a live boot secret


def pair(**kw):
    return ipc.Channel(KEY, scope='setup', generation=0, **kw)


def test_request_and_response_roundtrip_complete_closed_envelopes():
    client, server = pair(), pair()
    request = client.request('balance.get', {})
    accepted = server.accept_request(request)
    response = server.response(accepted, payload={'contract': 'studiotwin.dashboard.v1',
        'balance': {'state': 'known', 'credits': 12, 'asOfMs': 1}})
    assert client.accept_response(response)['result']['method'] == 'balance.get'
    assert not client.pending
    with pytest.raises(ipc.Refused):
        client.accept_response(response)


def test_static_error_roundtrip_and_version_refusal():
    client, server = pair(), pair()
    request = client.request('status.get', {})
    accepted = server.accept_request(request)
    response = server.response(accepted, code='UNAVAILABLE')
    assert client.accept_response(response)['error']['code'] == 'UNAVAILABLE'
    bad = copy.deepcopy(request)
    bad['protocol'] = 'studiotwin.gateway.v2'
    bad['mac'] = client._mac({k: v for k, v in bad.items() if k != 'mac'}, 'request')
    with pytest.raises(ipc.VersionRefused) as error:
        server.accept_request(bad)
    refusal = error.value.envelope
    ipc.validate('gateway', 'VersionRefusalV1', refusal)
    assert refusal['error']['received'] == 'studiotwin.gateway.v2'


@pytest.mark.parametrize('field,value', [('mac', '0' * 64), ('method', 'balance.get'),
    ('params', {'approved': True}), ('extra', True), ('nonce', 'A' * 43)])
def test_request_tampering_is_rejected(field, value):
    request = pair().request('status.get', {})
    request[field] = value
    with pytest.raises(ipc.Refused):
        pair().accept_request(request)


def test_monotonic_replay_and_highwater_not_evicted():
    client, server = pair(), pair()
    first = client.request('status.get', {})
    second = client.request('status.get', {})
    server.accept_request(second)
    with pytest.raises(ipc.Refused, match='REPLAYED_NONCE'):
        server.accept_request(first)
    with pytest.raises(ipc.Refused, match='REPLAYED_NONCE'):
        server.accept_request(second)
    server.clear_pending()
    with pytest.raises(ipc.Refused, match='REPLAYED_NONCE'):
        server.accept_request(second)


@pytest.mark.parametrize('scope,generation,key', [('other', 0, KEY), ('setup', 1, KEY),
    ('setup', 0, b'x' * 32)])
def test_scope_generation_and_boot_bound(scope, generation, key):
    req = pair().request('status.get', {})
    with pytest.raises(ipc.Refused):
        ipc.Channel(key, scope=scope, generation=generation).accept_request(req)


def test_response_mac_requestid_method_and_closed_payload():
    client, server = pair(), pair()
    req = client.request('status.get', {})
    request = server.accept_request(req)
    good = server.response(request, code='UNAVAILABLE')
    bad = copy.deepcopy(good)
    bad['envelope']['requestId'] = 'rq_' + 'x' * 22
    with pytest.raises(ipc.Refused):
        client.accept_response(bad)
    assert client.pending
    bad_mac = copy.deepcopy(good)
    bad_mac['mac'] = '0' * 64
    with pytest.raises(ipc.Refused, match='BAD_MAC'):
        client.accept_response(bad_mac)
    wrong_id = copy.deepcopy(good['envelope'])
    wrong_id['requestId'] = 'rq_' + 'x' * 22
    with pytest.raises(ipc.Refused, match='MISMATCH'):
        client.accept_response(server.seal_response(wrong_id))
    assert client.pending
    with pytest.raises(ipc.Refused):
        server.response(request, payload={'secret': 'not-allowed'})
    assert client.accept_response(good)['ok'] is False
    # Correctly MACed wrong method/result remains forbidden, not merely bad-MAC.
    client, server = pair(), pair()
    request = server.accept_request(client.request('status.get', {}))
    wrong = {'protocol': ipc.PROTOCOL, 'requestId': request['requestId'], 'ok': True,
        'result': {'method': 'balance.get', 'payload': {'contract': 'studiotwin.dashboard.v1',
            'balance': {'state': 'known', 'credits': 12, 'asOfMs': 1}}}}
    with pytest.raises(ipc.Refused, match='MISMATCH'):
        client.accept_response(server.seal_response(wrong))


@pytest.mark.parametrize('method,params', [('status.get', {'assetId': 'x'}),
    ('assets.get', {}), ('uploads.putChunk', {'uploadId': 'x', 'offset': 0, 'bytes': [256]}),
    ('not-a-method', {})])
def test_method_specific_closed_params(method, params):
    with pytest.raises(ipc.Refused):
        pair().request(method, params)


def test_pending_bounded_and_expiry_keeps_nonce():
    now = [0]
    client, server = pair(clock=lambda: now[0], max_pending=1), pair(clock=lambda: now[0])
    first = client.request('status.get', {})
    with pytest.raises(ipc.Refused):
        client.request('status.get', {})
    now[0] = 120000
    with pytest.raises(ipc.Refused, match='STALE_REQUEST'):
        server.accept_request(first)
    client.clear_pending()
    second = client.request('status.get', {})
    assert second['nonce'] != first['nonce']


@pytest.mark.parametrize('host', ['0.0.0.0', '::', 'example.org', '127.0.0.1.evil', '192.168.1.1'])
def test_local_bind_guard(host):
    with pytest.raises(ipc.Refused):
        ipc.local_address(host)


@pytest.mark.parametrize('target', ['http://example.org/a', 'http://127.0.0.1:9999/a',
    'http://localhost:1234/a', 'https://127.0.0.1:1234/a', '//example.org/a',
    'http://user:pass@127.0.0.1:1234/a'])
def test_redirect_rejected_before_network(target):
    with pytest.raises(ipc.Refused):
        ipc.local_redirect('http://127.0.0.1:1234/', target)


def test_safe_redirect_and_literal_loopback():
    assert ipc.local_address('127.0.0.1') == '127.0.0.1'
    assert ipc.local_address('::1') == '::1'
    assert ipc.local_redirect('http://127.0.0.1:1234/', '/safe') == 'http://127.0.0.1:1234/safe'


def test_descriptor_permissions_no_symlink_and_real_local_server(tmp_path):
    async def exercise():
        async with ipc.LocalServer(tmp_path) as server:
            descriptor = tmp_path / 'gateway-ipc.json'
            assert descriptor.stat().st_mode & 0o777 == 0o600
            data = ipc.read_descriptor(descriptor)
            assert data['host'] == '127.0.0.1'
            client = ipc.Channel(bytes.fromhex(data['key']), scope='setup', generation=0)
            reader, writer = await asyncio.open_connection(data['host'], data['port'])
            request = client.request('status.get', {})
            writer.write(json.dumps(request).encode() + b'\n')
            await writer.drain()
            response = json.loads(await asyncio.wait_for(reader.readline(), 5))
            assert client.accept_response(response)['error']['code'] == 'UNAVAILABLE'
            writer.close()
            await writer.wait_closed()
            # Validly authenticated incompatible protocol must receive the frozen
            # refusal over the real wire, not just a dropped connection.
            reader, writer = await asyncio.open_connection(data['host'], data['port'])
            request = client.request('status.get', {})
            request['protocol'] = 'studiotwin.gateway.v2'
            request['mac'] = client._mac({k: v for k, v in request.items() if k != 'mac'}, 'request')
            writer.write(json.dumps(request).encode() + b'\n')
            await writer.drain()
            line = await asyncio.wait_for(reader.readline(), 5)
            assert line, 'authenticated version refusal must be sent'
            frame = json.loads(line)
            ipc.validate('gateway', 'VersionRefusalV1', frame['envelope'])
            assert frame['mac'] == client._mac(frame['envelope'], 'response')
            pending = copy.deepcopy(client.pending)
            with pytest.raises(ipc.VersionRefused) as refusal:
                client.accept_response(frame)
            assert refusal.value.envelope == frame['envelope']
            assert client.pending == pending
            writer.close()
            await writer.wait_closed()
            descriptor.chmod(0o644)
            with pytest.raises(ipc.Refused):
                ipc.read_descriptor(descriptor)
            descriptor.chmod(0o600)
            link = tmp_path / 'link'
            link.symlink_to(descriptor)
            with pytest.raises(ipc.Refused):
                ipc.read_descriptor(link)
        assert not descriptor.exists()
    asyncio.run(exercise())


def test_authenticated_version_refusal_is_typed_and_preserves_pending():
    client, server = pair(), pair()
    client.request('status.get', {})
    client.request('balance.get', {})
    pending = copy.deepcopy(client.pending)
    envelope = ipc.VersionRefused('studiotwin.gateway.v2').envelope
    frame = {'envelope': envelope, 'mac': server._mac(envelope, 'response')}
    with pytest.raises(ipc.VersionRefused) as error:
        client.accept_response(frame)
    assert error.value.envelope == envelope
    assert client.pending == pending
    frame['mac'] = '0' * 64
    with pytest.raises(ipc.Refused, match='BAD_MAC') as error:
        client.accept_response(frame)
    assert not isinstance(error.value, ipc.VersionRefused)
    frame['envelope']['error']['extra'] = True
    frame['mac'] = server._mac(frame['envelope'], 'response')
    with pytest.raises(ipc.Refused) as error:
        client.accept_response(frame)
    assert not isinstance(error.value, ipc.VersionRefused)
    assert client.pending == pending


def test_ipc_import_does_not_load_schema_dependencies():
    import subprocess
    result = subprocess.run([sys.executable, '-c',
        "import runpy, sys; runpy.run_path('gateway/ipc.py'); "
        "assert 'jsonschema' not in sys.modules; assert 'referencing' not in sys.modules"],
        cwd=ROOT, capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


class WindowsApiFixture:
    """Linux fd backing for the injectable Win32 seam, NOT native ACL proof."""
    def __init__(self):
        self.records = {}
        self.events = []
        self.owner = 'user'
        self.entries = [('user', 0x1f01ff)]
        self.protected = True
        self.reparse = False

    def open(self, path, *, directory=False, create=False, exclusive=False):
        import os
        self.events.append(('open', Path(path).name))
        if directory:
            Path(path).mkdir(parents=True, exist_ok=True)
        flags = os.O_RDONLY if directory else os.O_RDWR
        if create:
            flags |= os.O_CREAT
        if exclusive:
            flags |= os.O_EXCL
        fd = os.open(path, flags, 0o600)
        self.records[fd] = directory
        return fd

    def inspect(self, fd):
        import os
        self.events.append(('inspect', fd))
        return dict(owner=self.owner, user='user', protected=self.protected,
            entries=self.entries, reparse=self.reparse, directory=self.records[fd],
            size=os.fstat(fd).st_size)

    def secure(self, fd):
        self.events.append(('secure', fd))
        self.protected = True
        self.entries = [('user', 0x1f01ff)]

    def detach(self, fd):
        return fd

    def close(self, fd):
        import os
        self.events.append(('close', fd))
        os.close(fd)


@pytest.mark.parametrize('change', ['owner', 'foreign', 'unprotected', 'null', 'reparse'])
def test_windows_owner_acl_and_reparse_refusals(tmp_path, change):
    api = WindowsApiFixture()
    if change == 'owner': api.owner = 'other'
    if change == 'foreign': api.entries.append(('other', 1))
    if change == 'unprotected': api.protected = False
    if change == 'null': api.entries = None
    if change == 'reparse': api.reparse = True
    files = ipc.WindowsFiles(api=api)
    with pytest.raises(ipc.Refused, match='PRIVATE_STORAGE'):
        with files.directory(tmp_path):
            pytest.fail('unsafe directory accepted')
    assert api.events[-1][0] == 'close'


def test_windows_descriptor_and_real_loopback_with_acl_seam(tmp_path):
    api = WindowsApiFixture()
    files = ipc.WindowsFiles(api=api)
    async def exercise():
        async with ipc.LocalServer(tmp_path, windows=files):
            data = ipc.read_descriptor(tmp_path / 'gateway-ipc.json', windows=files)
            client = ipc.Channel(bytes.fromhex(data['key']), scope='setup', generation=0)
            reader, writer = await asyncio.open_connection(data['host'], data['port'])
            writer.write(ipc.encode(client.request('status.get', {})) + b'\n')
            await writer.drain()
            assert client.accept_response(ipc.decode(await reader.readline()))['error']['code'] == 'UNAVAILABLE'
            writer.close()
            await writer.wait_closed()
            api.entries.append(('other', 1))
            with pytest.raises(ipc.Refused):
                ipc.read_descriptor(tmp_path / 'gateway-ipc.json', windows=files)
            api.entries.pop()
        assert not (tmp_path / 'gateway-ipc.json').exists()
    asyncio.run(exercise())
    assert any(event[0] == 'inspect' for event in api.events)


@pytest.mark.parametrize('change', ['owner', 'foreign', 'null', 'reparse'])
def test_windows_file_acl_checked_before_detach(tmp_path, change):
    api = WindowsApiFixture()
    files = ipc.WindowsFiles(api=api)
    path = tmp_path / 'private.json'
    path.write_bytes(b'{}')
    if change == 'owner': api.owner = 'other'
    if change == 'foreign': api.entries.append(('other', 1))
    if change == 'null': api.entries = None
    if change == 'reparse': api.reparse = True
    with pytest.raises(ipc.Refused, match='PRIVATE_STORAGE'):
        files.open(path)
    assert api.events[-1][0] == 'close'
    assert path.read_bytes() == b'{}'


def test_windows_database_and_consumed_private_bootstrap(tmp_path):
    from s05_ipc.startup import open_database, gate_from_file
    api = WindowsApiFixture()
    files = ipc.WindowsFiles(api=api)
    api.protected = False  # translated PLUGIN_DATA can initially inherit permissions
    connection = open_database(tmp_path, windows=files)
    assert connection.execute('PRAGMA journal_mode').fetchone() == ('wal',)
    connection.close()
    assert any(event[0] == 'secure' for event in api.events)
    path = tmp_path / 'host-bootstrap.json'
    path.write_text(json.dumps(dict(key='6b' * 32, hostInstanceNonce='H' * 43,
        profileId='profile-a', connectionId='local')))
    gate = gate_from_file(path, windows=files)
    assert gate._key == KEY
    assert not path.exists()
    path.write_text('{}')
    api.owner = 'foreign'
    with pytest.raises(ValueError, match='bootstrap'):
        gate_from_file(path, windows=files)


def test_wire_limits_duplicate_keys_and_nonfinite():
    for wire in [b'{' + b'x' * 1048576, b'{"a":1,"a":2}', b'{"x":NaN}', b'[' * 100 + b']' * 100]:
        with pytest.raises(ipc.Refused):
            ipc.decode(wire)
