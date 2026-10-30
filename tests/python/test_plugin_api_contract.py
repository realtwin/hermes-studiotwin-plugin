"""S11 whole wrapped-envelope CF8 regressions (not a schema oracle)."""
import asyncio
import copy

import pytest
from tests.python.test_dashboard_core import D, I, R, C, Peer, client, FORM, NAME, HASH, SCOPE


def unsafe_schema(case):
    field = {'name':'prompt','required':True,'schema':{'kind':'string'}}
    schema = {'kind':'object','fields':[field]}
    if case == 'duplicate': schema['fields'].append(copy.deepcopy(field))
    if case == 'default': field['schema']['defaultValue'] = 10
    if case == 'bounds': field['schema'].update(minLength=20,maxLength=10)
    if case == 'choices': field['schema']['choices'] = [True]
    if case == 'html': field['schema']['description'] = '<script>alert(1)</script>'
    if case == 'secret_name': field['name'] = 'api_key'
    if case == 'canary': field['schema']['description'] = 'STCANARY_PRIVATE_FIELD'
    if case == 'depth':
        for _ in range(9): schema = {'kind':'array','items':schema}
    if case == 'nodes':
        schema['fields'] = [{'name':f'group{i}','required':False,'schema':{'kind':'object','fields':[
            {'name':f'f{j}','required':False,'schema':{'kind':'string'}} for j in range(64)]}} for i in range(5)]
    if case == 'bytes':
        schema['fields'] = [{'name':f'f{j}','required':False,'schema':{'kind':'string','description':'z'*4000}} for j in range(20)]
    return schema


@pytest.mark.parametrize('case',['duplicate','default','bounds','choices','html','secret_name','canary','depth','nodes','bytes'])
def test_cf8_real_wrapped_receive_rejects_unsafe_whole_form(tmp_path, case):
    def mutate(frame, req):
        env = frame['envelope']
        env['result']['payload']['inputSchema'] = unsafe_schema(case)
        # Deliberately sign structurally valid malicious payloads as the future
        # gateway peer: authentication alone is not semantic validation.
        return {'envelope':env,'mac':peer.channel._mac(env,'response')}
    async def run():
        nonlocal peer
        async with Peer(tmp_path/'data',mutate) as peer:
            with pytest.raises(R.BoundaryRefused) as e:
                await client(peer).request('capabilities.inputSchema',{'tool':NAME,'schemaHash':HASH})
            assert str(e.value) == 'UNSAFE_PAYLOAD'
            assert e.value.__context__ is None
            assert len(peer.requests) == 1
    peer = None
    asyncio.run(run())


@pytest.mark.parametrize('case',['other_tool','other_hash','unclassified','projection_drift'])
def test_schema_reply_must_match_outstanding_release_projection(tmp_path, case):
    def mutate(frame, req):
        env = frame['envelope']
        payload = env['result']['payload']
        if case == 'other_tool': payload['tool'] = 'text-to-motion'
        if case == 'other_hash': payload['schemaHash'] = '0'*64
        if case == 'unclassified': payload['classification'] = 'discovered_unclassified'
        if case == 'projection_drift': payload['inputSchema'] = {'kind':'object','fields':[]}
        return {'envelope':env,'mac':peer.channel._mac(env,'response')}
    async def run():
        nonlocal peer
        async with Peer(tmp_path/'data',mutate) as peer:
            with pytest.raises(R.BoundaryRefused):
                await client(peer).request('capabilities.inputSchema',{'tool':NAME,'schemaHash':HASH})
    peer = None
    asyncio.run(run())


def test_real_s06_complete_boundary_is_used_both_directions(tmp_path, monkeypatch):
    refs = []
    real = R.validate_mediated_v1
    def spy(ref, candidate, **kw):
        refs.append(ref)
        return real(ref,candidate,**kw)
    monkeypatch.setattr(R,'validate_mediated_v1',spy)
    async def run():
        async with Peer(tmp_path/'data') as peer:
            await client(peer).request('capabilities.inputSchema',{'tool':NAME,'schemaHash':HASH})
    asyncio.run(run())
    assert 'host_gateway#/$defs/IpcRequestV1' in refs
    assert 'host_gateway#/$defs/IpcResponseV1' in refs


def test_no_foreign_hostname_dns_or_connect_on_unsafe_descriptor(tmp_path, monkeypatch):
    root = tmp_path/'data'
    root.mkdir(mode=0o700)
    path = root/'gateway-ipc.json'
    path.write_text('{"host":"example.invalid","port":443,"key":"'+'a'*64+'"}')
    path.chmod(0o600)
    calls = []
    async def tripwire(*args,**kw):
        calls.append(1)
        raise AssertionError('network reached')
    monkeypatch.setattr(asyncio,'open_connection',tripwire)
    with pytest.raises(R.BoundaryRefused):
        D.DashboardIpcClient(root,scope_id=SCOPE,generation=1,current_binding=lambda:(SCOPE,1),sensitive_values=lambda:())
    assert not calls
