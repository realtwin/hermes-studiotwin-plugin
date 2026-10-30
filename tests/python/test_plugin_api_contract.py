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


def test_real_s08_wrapped_semantic_boundary_is_invoked(tmp_path,monkeypatch):
    calls = []
    real = C.validate_input_schema_response_v1
    def spy(candidate,**kw):
        calls.append((candidate.get('result',{}).get('method'),kw.get('wrapped',False)))
        return real(candidate,**kw)
    monkeypatch.setattr(C,'validate_input_schema_response_v1',spy)
    async def run():
        async with Peer(tmp_path/'data') as peer:
            await client(peer).request('capabilities.inputSchema',{'tool':NAME,'schemaHash':HASH})
    asyncio.run(run())
    assert ('capabilities.inputSchema',True) in calls


def test_callback_failure_does_not_escape_secret_exception_context(tmp_path):
    def current():
        raise RuntimeError('STCANARY_CALLBACK_SECRET')
    async def run():
        async with Peer(tmp_path/'data') as peer:
            with pytest.raises(R.BoundaryRefused) as e:
                client(peer,current=current)
            assert e.value.__context__ is None and str(e.value)=='UNSAFE_PAYLOAD'
    asyncio.run(run())


# HTTP tests use real ASGI and authenticated S05 TCP, not direct route calls.
from contextlib import asynccontextmanager
import httpx


@asynccontextmanager
async def http_backend(tmp_path, payloads=None, *, clock=None):
    API = __import__('importlib').import_module('s11_dashboard.plugin_api')
    from fastapi import FastAPI
    from tests.python.test_dashboard_core import make_store, make_proxy, TOOLS
    store,binding,now = make_store(tmp_path)
    proxy,item,data,_ = make_proxy(tmp_path,binding=binding)
    def respond(frame,req):
        payload = (payloads or {}).get(req['method'])
        if payload is None: return frame
        return peer.channel.response(req,payload=copy.deepcopy(payload))
    async with Peer(tmp_path/'ipc',respond) as peer:
        ipc_client = D.DashboardIpcClient(peer.root,scope_id=SCOPE,generation=1,current_binding=lambda:tuple(binding),sensitive_values=lambda:(),catalog=C.Classification(TOOLS))
        # Explicitly fake host auth adapter; never inferred by production.
        def authenticate(request):
            if request.headers.get('x-test-session') != 'admitted': return None
            return ('session','csrf-private-token')
        backend = API.Backend(ipc_client,store,proxy,current_binding=lambda:tuple(binding),sensitive_values=lambda:(),
            authenticate=authenticate,allowed_hosts={'127.0.0.1:8000'},allowed_origins={'http://127.0.0.1:8000'},
            catalog=ipc_client._catalog,clock=clock)
        app = FastAPI()
        app.state.studiotwin = backend
        app.include_router(API.router,prefix='/api/plugins/hermes-studiotwin')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://127.0.0.1:8000/api/plugins/hermes-studiotwin',
            headers={'X-StudioTwin-Contract':'studiotwin.dashboard.v1','X-Test-Session':'admitted','Origin':'http://127.0.0.1:8000','X-StudioTwin-CSRF':'csrf-private-token'}) as http:
            yield API,backend,http,peer,store,binding,item,data
    store.close()


def test_http_status_capabilities_and_cf8_over_actual_ipc(tmp_path):
    from tests.python.test_dashboard_core import CONTRACT
    status = dict(contract=CONTRACT,environment='fake',configured=False,featureFlags=dict(hostedRead=False,hostedMutation=False,paid=False,conceptPaid=False),balance={'state':'unknown'},activeCount=0,publishedTiers=['setup'])
    capabilities = dict(contract=CONTRACT,etag='"offline"',publishedTiers=['setup'],tools=[])
    async def run():
        async with http_backend(tmp_path,{'status.get':status,'capabilities.list':capabilities}) as (_,b,h,p,*_):
            for path,expected in [('/status',status),('/capabilities',capabilities),('/capabilities/'+NAME+'/input-schema?schemaHash='+HASH,FORM)]:
                response = await h.get(path)
                assert response.status_code == 200, response.text
                assert response.json() == expected
                assert response.headers['X-StudioTwin-Contract'] == CONTRACT
            assert [r['method'] for r in p.requests] == ['status.get','capabilities.list','capabilities.inputSchema']
    asyncio.run(run())


def test_http_local_file_ranges_and_provenance(tmp_path):
    from tests.python.test_dashboard_core import record_request, B
    async def run():
        async with http_backend(tmp_path) as (_,b,h,p,s,binding,item,data):
            response = await h.get('/local/file',params={'handle':item.handle},headers={'Range':'bytes=0-7'})
            assert response.status_code == 206 and response.content == data[:8]
            response = await h.get('/local/file',params={'handle':item.handle},headers={'Range':'bytes=999999-'})
            assert response.status_code == 416
            assert response.headers['Content-Range'] == 'bytes */160008'
            response = await h.post('/provenance',json=record_request())
            assert response.status_code == 200 and response.json()['edgeCount'] == 2
            response = await h.get('/lineage/'+B)
            assert response.status_code == 200 and len(response.json()['edges']) == 2
            assert all(r['method']=='lineage.get' for r in p.requests)
    asyncio.run(run())


def test_module_path_loading_and_exact_frozen_s11_route_inventory():
    import importlib.util
    import sys
    from tests.python.test_dashboard_core import ROOT
    spec = importlib.util.spec_from_file_location('hermes_dashboard_plugin_studiotwin_probe',ROOT/'dashboard/plugin_api.py')
    mod = importlib.util.module_from_spec(spec); sys.modules[spec.name]=mod
    spec.loader.exec_module(mod)
    contract = __import__('json').loads((ROOT/'contracts/dashboard-v1.openapi.json').read_text())
    expected = {(method.upper(),path) for path,methods in contract['paths'].items() for method,row in methods.items() if isinstance(row,dict) and row.get('x-studiotwin-owner')=='S11'}
    actual = {(method,r.path) for r in mod.router.routes for method in r.methods}
    assert actual == expected
    assert not (ROOT/'dashboard/router.py').exists()

