"""S11 client tests exercise real authenticated loopback bytes; never hosted I/O."""
import asyncio
import copy
import importlib
import json
import os
from pathlib import Path
import sys
import types

import pytest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
if 's11_dashboard' not in sys.modules:
    pkg = types.ModuleType('s11_dashboard')
    pkg.__path__ = [str(ROOT / 'dashboard')]
    sys.modules[pkg.__name__] = pkg
D = importlib.import_module('s11_dashboard.ipc_client')
I, C, R = D.ipc, D.classification, D.redaction
SCOPE = 'a' * 64
NAME = 'text-to-environment-map'
TOOLS = json.loads((ROOT / 'tests/fixtures/tools-list-2026-10-30.json').read_text())['tools']
CLASS = C.Classification(TOOLS)
FORM = CLASS.input_schema(NAME, C.RELEASE['tools'][NAME]['schemaHash'], scope_id=SCOPE, generation=1, sensitive_values=()).to_json()
HASH = FORM['schemaHash']


class Peer:
    """Offline future scoped IPC peer using S05's actual Channel/MAC/parser."""
    def __init__(self, root, mutate=None, *, scope=SCOPE, generation=1):
        self.root, self.mutate = root, mutate
        self.channel = I.Channel(b'k' * 32, scope=scope, generation=generation)
        self.requests = []
        self.failures = []

    async def __aenter__(self):
        self.root.mkdir(mode=0o700, exist_ok=True)
        self.server = await asyncio.start_server(self.serve, '127.0.0.1', 0)
        port = self.server.sockets[0].getsockname()[1]
        self.descriptor = self.root / 'gateway-ipc.json'
        self.descriptor.write_text(json.dumps({'host':'127.0.0.1', 'port':port, 'key':(b'k'*32).hex()}))
        self.descriptor.chmod(0o600)
        return self

    async def __aexit__(self, *_):
        self.server.close()
        await self.server.wait_closed()

    async def serve(self, reader, writer):
        try:
            req = self.channel.accept_request(I.decode(await reader.readline()))
            self.requests.append(req)
            if req['method'] == 'capabilities.inputSchema':
                frame = self.channel.response(req, payload=copy.deepcopy(FORM))
            else:
                frame = self.channel.response(req, code='UNAVAILABLE')
            if self.mutate:
                changed = self.mutate(frame, req)
                if changed is not None:
                    frame = changed
            writer.write(I.encode(frame) + b'\n')
            await writer.drain()
        except Exception as e:
            self.failures.append(type(e).__name__)
        finally:
            writer.close()
            await writer.wait_closed()


def client(peer, *, current=None, secrets=()):
    return D.DashboardIpcClient(peer.root, scope_id=SCOPE, generation=1,
        current_binding=current or (lambda:(SCOPE,1)), sensitive_values=lambda:secrets)


def test_real_loopback_form_and_retained_monotonic_nonce(tmp_path):
    async def run():
        async with Peer(tmp_path/'data') as peer:
            c = client(peer)
            for _ in range(3):
                result = await c.request('capabilities.inputSchema', {'tool':NAME,'schemaHash':HASH})
                assert result.to_json()['result']['payload'] == FORM
                assert (result.scope_id,result.generation) == (SCOPE,1)
            nonces = [int.from_bytes(__import__('base64').urlsafe_b64decode(r['nonce']+'='),'big') for r in peer.requests]
            assert nonces == [1,2,3]
            assert not c._channel.pending
            assert not peer.failures
    asyncio.run(run())


def test_actual_s05_setup_listener_and_closed_error(tmp_path):
    async def run():
        async with I.LocalServer(tmp_path/'data') as server:
            c = D.DashboardIpcClient(server.data, scope_id='0'*64, generation=0,
                current_binding=lambda:('0'*64,0), sensitive_values=lambda:())
            result = (await c.request('status.get', {})).to_json()
            assert result['ok'] is False and result['error']['code'] == 'UNAVAILABLE'
    asyncio.run(run())


@pytest.mark.parametrize('params', [{'approved':True}, {'tool':NAME,'schemaHash':HASH,'scopeId':SCOPE},
    {'tool':NAME,'schemaHash':'x'*64}, {'tool':NAME+'\n','schemaHash':HASH}])
def test_invalid_outbound_never_connects(tmp_path, params):
    async def run():
        async with Peer(tmp_path/'data') as peer:
            with pytest.raises(R.BoundaryRefused):
                await client(peer).request('capabilities.inputSchema', params)
            assert peer.requests == []
    asyncio.run(run())


@pytest.mark.parametrize('kind', ['bad_mac','request_id','method','generation','registered_secret','unclosed'])
def test_complete_inbound_authentication_binding_and_mediation(tmp_path, kind):
    def mutate(frame, req):
        if kind == 'bad_mac':
            frame['mac'] = '0'*64
            return frame
        env = frame['envelope']
        if kind == 'request_id': env['requestId'] = 'rq_'+'x'*22
        if kind == 'method':
            env['result'] = {'method':'balance.get','payload':{'contract':'studiotwin.dashboard.v1',
                'balance':{'state':'unknown'}}}
        if kind == 'generation':
            return I.Channel(b'k'*32, scope=SCOPE, generation=2).seal_response(env)
        if kind == 'registered_secret': env['result']['payload']['inputSchema']['description'] = 'plain-opaque-sensitive-value'
        if kind == 'unclosed': env['result']['payload']['extra'] = True
        # Seal deliberately malformed shapes without the producer validator.
        return {'envelope':env,'mac':peer.channel._mac(env,'response')}
    async def run():
        nonlocal peer
        async with Peer(tmp_path/'data',mutate) as peer:
            with pytest.raises(R.BoundaryRefused) as error:
                await client(peer,secrets=('plain-opaque-sensitive-value',)).request(
                    'capabilities.inputSchema',{'tool':NAME,'schemaHash':HASH})
            assert str(error.value) == 'UNSAFE_PAYLOAD'
            assert error.value.__context__ is None and error.value.__cause__ is None
            assert len(peer.requests) == 1
    peer = None
    asyncio.run(run())


@pytest.mark.parametrize('phase', ['before','during'])
def test_rotation_refuses_without_replay(tmp_path, phase):
    current = [SCOPE,1]
    def mutate(frame, req):
        current[1] = 2
        return frame
    async def run():
        async with Peer(tmp_path/'data',mutate if phase=='during' else None) as peer:
            c = client(peer,current=lambda:tuple(current))
            if phase == 'before': current[1] = 2
            with pytest.raises(R.BoundaryRefused):
                await c.request('status.get',{})
            assert len(peer.requests) == (0 if phase=='before' else 1)
    asyncio.run(run())


def test_descriptor_replacement_never_resets_nonce_or_uses_new_endpoint(tmp_path):
    async def run():
        async with Peer(tmp_path/'data') as peer:
            c = client(peer)
            await c.request('status.get',{})
            raw = I.decode(peer.descriptor.read_bytes())
            raw['port'] = 1
            peer.descriptor.write_bytes(I.encode(raw))
            with pytest.raises(R.BoundaryRefused):
                await c.request('status.get',{})
            assert len(peer.requests) == 1
            assert c._channel._sent == 1
    asyncio.run(run())


def test_outbound_quote_raw_candidate_rejected_before_forwarding(tmp_path):
    async def run():
        async with Peer(tmp_path/'data') as peer:
            for inputs in ({'prompt':'s3://private/secret'}, {'api_key':'value'}, {'prompt':'registered-sensitive-text'}):
                with pytest.raises(R.BoundaryRefused):
                    await client(peer,secrets=('registered-sensitive-text',)).request('operations.quote',
                        {'contract':'studiotwin.dashboard.v1','tool':NAME,'schemaHash':HASH,'inputs':inputs})
            assert not peer.requests
    asyncio.run(run())


CONTRACT = 'studiotwin.dashboard.v1'
A, B, JOB, CONCEPT = [f'00000000-0000-0000-0000-{n:012d}' for n in range(1,5)]


def record_request(sources=None, outputs=None, job=JOB):
    return dict(contract=CONTRACT, jobId=job, tool=NAME, inputFingerprint=HASH,
                sourceAssetIds=[A] if sources is None else sources,
                outputAssetIds=[B] if outputs is None else outputs)


def make_store(tmp_path, *, secrets=()):
    module = importlib.import_module('s11_dashboard.store')
    binding = [SCOPE, 1]
    now = [100.0]
    store = module.DashboardStore(tmp_path/'db', current_binding=lambda:tuple(binding),
        sensitive_values=lambda:secrets, clock=lambda:now[0])
    store.activate(*binding)
    return store, binding, now


def test_sqlite_restart_retention_purge_and_binding(tmp_path):
    s, binding, now = make_store(tmp_path)
    value = dict(contract=CONTRACT, root=A, nodes=[dict(kind='asset',id=A,depth=0)], edges=[], truncated=False)
    s.put('lineage', A, value, scope_id=SCOPE, generation=1)
    assert s.get('lineage', A, scope_id=SCOPE, generation=1).to_json() == value
    s.close()
    s, binding, now = make_store(tmp_path)
    assert s.stats(scope_id=SCOPE,generation=1)['metadata'] == 1
    binding[:] = ['b'*64,2]
    s.activate(*binding)
    assert s.get('lineage',A,scope_id=binding[0],generation=2) is None
    with pytest.raises(R.BoundaryRefused): s.get('lineage',A,scope_id=SCOPE,generation=1)
    binding[:] = [SCOPE,3]
    s.activate(*binding)
    assert s.get('lineage',A,scope_id=SCOPE,generation=3) is None
    with pytest.raises(R.BoundaryRefused): s.activate(SCOPE,1)
    s.put('lineage',A,value,scope_id=SCOPE,generation=3)
    now[0] += 30*86400
    assert s.get('lineage',A,scope_id=SCOPE,generation=3) is None
    s.put('lineage',A,value,scope_id=SCOPE,generation=3)
    assert s.purge(scope_id=SCOPE,generation=3)['metadata'] == 1
    assert s.stats(scope_id=SCOPE,generation=3)['metadata'] == 0
    s.close()


@pytest.mark.parametrize('bad', ['https://signed.invalid/?token=secret','STCANARY_STORE_PRIVATE','opaque-private-secret'])
def test_store_refuses_before_sql_sink(tmp_path,bad):
    s, _, _ = make_store(tmp_path,secrets=('opaque-private-secret',))
    before = s.connection.total_changes
    with pytest.raises(R.BoundaryRefused):
        s.put('lineage',A,dict(contract=CONTRACT,root=A,nodes=[],edges=[],truncated=False,extra=bad),scope_id=SCOPE,generation=1)
    assert s.connection.total_changes == before
    with pytest.raises(R.BoundaryRefused): s.put('anything',bad,{},scope_id=SCOPE,generation=1)
    s.close()
    assert bad.encode() not in (tmp_path/'db'/'studiotwin.sqlite3').read_bytes()


def test_provenance_internal_attribution_and_closed_merged_wire(tmp_path):
    P = importlib.import_module('s11_dashboard.provenance_store')
    s, binding, _ = make_store(tmp_path)
    p = P.ProvenanceStore(s)
    result = p.record(record_request(), scope_id=SCOPE,generation=1,concept_id=CONCEPT)
    assert result.to_json()['edgeCount'] == 2
    server = dict(contract=CONTRACT,root=B,nodes=[dict(kind='asset',id=A,depth=-2),dict(kind='job',id=JOB,depth=-1),dict(kind='asset',id=B,depth=0)],
                  edges=[dict(parent=A,child=JOB,relation='generated-from'),dict(parent=JOB,child=B,relation='output-of')],truncated=False)
    p.merge_server(server,scope_id=SCOPE,generation=1)
    wire = p.lineage(B,scope_id=SCOPE,generation=1).to_json()
    assert len(wire['edges']) == 2 and len(wire['nodes']) == 3
    assert {r['source'] for r in p.records(scope_id=SCOPE,generation=1)} == {'local-recorded','server-reported'}
    assert any(r['concept_id'] == CONCEPT for r in p.records(scope_id=SCOPE,generation=1))
    assert all(set(n)=={'kind','id','depth'} for n in wire['nodes'])
    binding[:] = ['b'*64,2]; s.activate(*binding)
    assert p.lineage(B,scope_id=binding[0],generation=2).to_json()['nodes'] == []
    with pytest.raises(R.BoundaryRefused): p.record(record_request(),scope_id=SCOPE,generation=1)
    s.close()


def test_lineage_dag_cycles_and_limits(tmp_path):
    P = importlib.import_module('s11_dashboard.provenance_store')
    s, _, _ = make_store(tmp_path)
    p = P.ProvenanceStore(s)
    p.record(record_request(),scope_id=SCOPE,generation=1)
    before = p.records(scope_id=SCOPE,generation=1)
    with pytest.raises(R.BoundaryRefused):
        p.record(record_request([B],[A],job=CONCEPT),scope_id=SCOPE,generation=1)
    assert p.records(scope_id=SCOPE,generation=1) == before
    for n in range(10,75):
        p.record(record_request([B],[f'00000000-0000-0000-0001-{n:012d}'],job=f'00000000-0000-0000-0002-{n:012d}'),scope_id=SCOPE,generation=1)
    wire = p.lineage(B,scope_id=SCOPE,generation=1).to_json()
    assert len(wire['nodes']) == 100 and wire['truncated']
    assert len(wire['edges']) <= 400
    assert all(-12 <= n['depth'] <=12 for n in wire['nodes'])
    assert all(e['parent'] in {n['id'] for n in wire['nodes']} and e['child'] in {n['id'] for n in wire['nodes']} for e in wire['edges'])
    s.close()


def make_proxy(tmp_path, *, binding=None):
    P = importlib.import_module('s11_dashboard.proxy')
    H = importlib.import_module(I.__package__+'.handles')
    M = importlib.import_module(I.__package__+'.media_cache')
    S = importlib.import_module('s11_dashboard.sandbox')
    handles = H.HandleStore()
    cache = M.MediaCache(tmp_path/'hermes-studiotwin',handles)
    data = b'\x89PNG\r\n\x1a\n'+b'x'*160000
    item = cache.put(scope_id=SCOPE,generation=1,data=data,mime='image/png',kind='image',extension='.png')
    binding = binding if binding is not None else [SCOPE,1]
    proxy = P.MediaProxy(handles,cache,S.FileSandbox(plugin_root=cache.root),current_binding=lambda:tuple(binding),sensitive_values=lambda:())
    return proxy,item,data,binding


@pytest.mark.parametrize('header,start,end',[(None,0,160007),('bytes=0-0',0,0),('bytes=8-15',8,15),('bytes=160000-',160000,160007),('bytes=-5',160003,160007),('bytes=0-999999',0,160007)])
def test_proxy_actual_checked_fd_range_and_bounded_chunks(tmp_path,header,start,end):
    p,item,data,_ = make_proxy(tmp_path)
    lease = p.prepare(handle=item.handle,scope_id=SCOPE,generation=1,session='session',range_header=header)
    assert lease.status == (200 if header is None else 206)
    assert lease.headers['Accept-Ranges'] == 'bytes'
    assert lease.headers['X-Content-Type-Options'] == 'nosniff'
    assert lease.headers['Content-Type'] == 'image/png'
    assert int(lease.headers['Content-Length']) == end-start+1
    chunks = list(lease.chunks())
    assert max(map(len,chunks)) <= 65536
    assert b''.join(chunks) == data[start:end+1]
    assert lease.closed


@pytest.mark.parametrize('header',['bytes=160008-','bytes=9-8','bytes=-0','bytes=0-1,4-5','bytes=a-b','items=0-1','bytes='+'9'*100+'-'])
def test_proxy_range_rejection_no_stream_leak(tmp_path,header):
    p,item,_,_ = make_proxy(tmp_path)
    P = importlib.import_module('s11_dashboard.proxy')
    with pytest.raises(P.ProxyRefused) as e:
        p.prepare(handle=item.handle,scope_id=SCOPE,generation=1,session='session',range_header=header)
    assert e.value.status == 416
    assert e.value.headers['Content-Range'] == 'bytes */160008'
    assert p.active_streams == 0


def test_proxy_scope_purpose_expiry_rotation_and_concurrency(tmp_path):
    p,item,data,binding = make_proxy(tmp_path)
    P = importlib.import_module('s11_dashboard.proxy')
    with pytest.raises(P.ProxyRefused):
        p.prepare(handle=item.handle,scope_id='b'*64,generation=1,session='session')
    token = p.handles.mint(scope_id=SCOPE,generation=1,purpose='transfer',kind='image',role='media',mime='image/png',size=len(data),target={'localPath':item.path})
    with pytest.raises(P.ProxyRefused):
        p.prepare(handle=token,scope_id=SCOPE,generation=1,session='session')
    one = p.prepare(handle=item.handle,scope_id=SCOPE,generation=1,session='session')
    two = p.prepare(path=item.path,scope_id=SCOPE,generation=1,session='session')
    with pytest.raises(P.ProxyRefused) as e:
        p.prepare(handle=item.handle,scope_id=SCOPE,generation=1,session='session')
    assert e.value.status == 429
    two.close()
    p.handles.revoke(item.handle)
    assert list(one.chunks()) == []
    assert one.closed and p.active_streams == 0
    old = p.prepare(path=item.path,scope_id=SCOPE,generation=1,session='session')
    binding[:] = ['b'*64,2]
    assert list(old.chunks()) == []
    assert p.active_streams == 0


def test_proxy_does_not_fetch_upstream_targets_or_echo_failures(tmp_path,monkeypatch):
    p,item,data,_ = make_proxy(tmp_path)
    P = importlib.import_module('s11_dashboard.proxy')
    token = p.handles.mint(scope_id=SCOPE,generation=1,purpose='resource',kind='image',role='media',mime='image/png',size=len(data),target={'url':'https://foreign.invalid/?secret=value'})
    with pytest.raises(P.ProxyRefused) as e:
        p.prepare(handle=token,scope_id=SCOPE,generation=1,session='session')
    assert str(e.value)=='Media unavailable.' and e.value.__context__ is None
    def fail(*a,**kw): raise RuntimeError('STCANARY_PROXY_PRIVATE')
    monkeypatch.setattr(p.cache,'open',fail)
    with pytest.raises(P.ProxyRefused) as e:
        p.prepare(handle=item.handle,scope_id=SCOPE,generation=1,session='session')
    assert e.value.__context__ is None and 'STCANARY' not in str(e.value)
    assert p.active_streams == 0
