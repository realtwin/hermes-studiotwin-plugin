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
