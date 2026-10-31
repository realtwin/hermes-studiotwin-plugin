"""V2 backend acceptance: real router, real loopback MCP and object storage."""
import base64
import importlib.util
import json
import sys
import tomllib
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests/fixtures'))
from fake_mcp.http import serve
from fake_mcp.state import FakeStudioTwin
from fake_mcp.scenarios import scenario


@pytest.fixture
def api(tmp_path, monkeypatch):
    import agent.secret_scope
    import hermes_cli.config
    home = tmp_path / 'home'
    home.mkdir()
    monkeypatch.setenv('HERMES_HOME', str(home / '.hermes'))
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: home))
    with serve() as h:
        settings = {'api_base_url': h.base}
        monkeypatch.setattr(agent.secret_scope, 'get_secret', lambda name: h.api_key)
        monkeypatch.setattr(hermes_cli.config, 'load_config_readonly', lambda: {'plugins': {'entries': {
            'hermes-studiotwin': {'settings': settings}}}})
        spec = importlib.util.spec_from_file_location('v01_api', ROOT / 'dashboard/plugin_api.py')
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        app = FastAPI()
        app.include_router(mod.router)
        with TestClient(app) as client:
            yield client, mod, h, settings


@pytest.mark.parametrize('raw', [False, True])
def test_account_credentials_json_is_not_media(api, raw):
    c, _, _, _ = api
    p = Path.home()/'.config'/'synthetic-service'/'credentials.json'
    p.parent.mkdir(parents=True)
    p.write_text('{"api_key":"SYNTHETIC_NOT_A_REAL_SECRET"}')
    assert c.get('/file', params={'path':str(p),'raw':raw}).status_code in (403,415)


@pytest.mark.parametrize('payload,allowed', [
    ({'clips':[], 'joints':[]}, True), ({'clips':[], 'frames':[]}, True),
    ({'clips':[]}, False), ([], False), ({'setting':True}, False),
    ({'clips':[], 'frames':[], 'api_key':'synthetic'}, False),
    ({'clips':[], 'frames':[{'client_secret':'synthetic'}]}, False),
    ({'clips':[], 'joints':[], 'password':'synthetic'}, False),
])
def test_home_json_requires_motion_payload(api, payload, allowed):
    c, _, _, _ = api
    p = Path.home()/'motion.json'
    p.write_text(json.dumps(payload))
    response = c.get('/file', params={'path':str(p)})
    assert response.status_code == 200 if allowed else response.status_code in (403,415)
    response = c.get('/file', params={'path':str(p)}, headers={'Range':'bytes=0-3'})
    assert response.status_code == 206 if allowed else response.status_code in (403,415)


def test_hidden_media_denied_and_trusted_json_roots_allowed(api):
    c, mod, _, _ = api
    hidden = Path.home()/'.private'/'image.png'
    hidden.parent.mkdir()
    hidden.write_bytes(b'png')
    assert c.get('/file', params={'path':str(hidden)}).status_code == 403
    for root in mod._allowed_roots()[:2]:
        root.mkdir(parents=True, exist_ok=True)
        p = root/'motion.json'
        p.write_text('{"trusted":true}')
        assert c.get('/file', params={'path':str(p),'raw':True}).status_code == 200
    ordinary = Path.home()/'image.png'
    ordinary.write_bytes(b'png')
    assert c.get('/file', params={'path':str(ordinary)}).status_code == 200


@pytest.mark.parametrize('name', ['Renamed concept reference', None, 'missing'])
@pytest.mark.parametrize('source', ['s3Uri', 'downloadUrl'])
def test_asset_display_name_need_not_be_filename(api, name, source, monkeypatch):
    c, _, h, _ = api
    aid = next(iter(h.fake.assets))
    resolve = h.fake._t_resolve_asset
    # Shape the wire response, not the fake's internal storage index: its
    # resolver needs s3Uri/name to locate the object before returning metadata.
    def resolve_response(args):
        result = resolve(args)
        row = json.loads(result.text)
        if name == 'missing':
            row.pop('name', None)
        else:
            row['name'] = name
        if source == 'downloadUrl':
            row.pop('s3Uri', None)
        result.text = json.dumps(row)
        return result
    monkeypatch.setattr(h.fake, '_t_resolve_asset', resolve_response)
    assert c.get('/assets/'+aid).status_code == 200
    response = c.get('/file', params={'asset':aid,'raw':True})
    assert response.status_code == 200, response.text
    assert response.headers['content-type'] == 'image/png'
    assert response.content.startswith(b'\x89PNG')
    before = len(h.requests)
    assert c.get('/file', params={'asset':aid,'raw':True}).content == response.content
    assert len(h.requests) == before
    assert c.get('/assets/'+aid).json()['local_path'].endswith('.png')


@pytest.mark.parametrize('direct_first', [True, False])
@pytest.mark.parametrize('direct', [{}, {'session_id':'asset-session'}])
def test_id_only_asset_provenance_does_not_hide_job_lineage(api, direct_first, direct):
    c, _, h, _ = api
    source, output = list(h.fake.assets)[:2]
    job = '00000001-0001-4000-8000-000000000001'
    records = [{'id':output, **direct}, {'id':job,'prompt':'owl','tool':'image-to-3d-mesh',
        'sourceAssetIds':[source],'outputAssetIds':[output]}]
    for record in records if direct_first else reversed(records):
        assert c.post('/provenance', json=record).status_code == 200
    response = c.get('/details', params={'id':output}).json()
    assert response['made_from'] == 'Made from owl'
    assert response['record']['tool'] == 'image-to-3d-mesh'
    assert all(response['record'][key] == value for key,value in direct.items())
    assert {'id':source,'relation':'source'} in response['parents']
    assert {'id':job,'relation':'job'} in response['parents']
    assert response['recorded']
    rows = c.get('/assets').json()['assets']
    assert next(r for r in rows if r['uuid'] == output)['made_from'] == 'Made from owl'


def test_manifest_host_contract(tmp_path):
    from hermes_cli.agent_plugins import load_agent_plugin
    from hermes_cli.plugin_validate import validate_plugin_dir
    from pm.plugin_declarations import read_python_declaration
    package = load_agent_plugin(ROOT, tmp_path / 'data')
    server = package.mcp_servers['studiotwin']
    assert package.version == '0.2.0'
    assert server['url'] == 'https://api.studiotwin.ai/mcp'
    assert server['headers'] == {'x-api-key': '${STUDIOTWIN_API_KEY}'}
    assert server['trust'] == 'untrusted' and server['timeout'] == 1500
    assert 'spend_limit' not in server
    assert len(server['tool_costs']) == 27
    assert not read_python_declaration(ROOT).pyproject_installs
    assert set(tomllib.loads((ROOT / 'pyproject.toml').read_text())) == {'project'}
    report = validate_plugin_dir(ROOT)
    assert report.ok, report.failures


def test_status_assets_resolve_and_cache(api):
    c, mod, h, settings = api
    status = c.get('/status').json()
    assert status['configured'] and status['balance'] == 500
    assert status['key_env'] == 'STUDIOTWIN_API_KEY'
    assert 'ffmpeg' in status['host']
    aid = next(iter(h.fake.assets))
    resolved = c.get('/assets/' + aid).json()
    assert 'X-Amz-Signature=' in resolved['downloadUrl'] and resolved['s3Uri'].startswith('s3://')
    r = c.get('/file', params={'asset': aid})
    assert r.status_code == 200, r.text
    data = base64.b64decode(r.json()['dataUrl'].split(',')[1])
    assert data.startswith(b'\x89PNG')
    before = len(h.requests)
    assert c.get('/file', params={'asset': aid, 'raw': 1}).content == data
    assert len(h.requests) == before
    assert c.get('/assets/' + aid).json()['local_path']
    assets = c.get('/assets', params={'type': 'image', 'limit': 2}).json()['assets']
    assert len(assets) <= 2 and len([a for a in assets if a['uuid'] == aid]) == 1
    assert c.get('/assets?type=not-a-type').status_code == 400
    settings['gallery_limit'] = 3
    assert c.get('/status').json()['settings']['gallery_limit'] == 3


@pytest.mark.parametrize('range_,status,expected', [(None,200,b'0123456789'),('bytes=2-5',206,b'2345'),
    ('bytes=-3',206,b'789'),('bytes=5-',206,b'56789'),('bytes=99-',416,None),('bytes=3-2',416,None),
    ('bytes=0-1,3-4',416,None),('bytes=-0',416,None)])
def test_file_ranges(api, range_, status, expected):
    c, mod, h, _ = api
    root = mod._data_root()
    root.mkdir(parents=True, exist_ok=True)
    p = root / 'clip.mp4'
    p.write_bytes(b'0123456789')
    r = c.get('/file', params={'path': str(p), 'raw': 1}, headers={'Range':range_} if range_ else {})
    assert r.status_code == status
    assert r.headers['accept-ranges'] == 'bytes'
    if expected is not None:
        assert r.content == expected
    if status == 206:
        assert r.headers['content-range'].endswith('/10')
    if status == 416:
        assert r.headers['content-range'] == 'bytes */10'


def test_local_file_and_validation_before_network(api, tmp_path):
    c, mod, h, _ = api
    root = mod._data_root()
    root.mkdir(parents=True)
    p = root / 'mesh.glb'
    p.write_bytes(b'glTF')
    r = c.get('/file', params={'path':str(p)}).json()
    assert r['mime'] == 'model/gltf-binary' and r['bytes'] == 4 and 'mtime' in r
    (root / 'secret.env').write_text('do-not-read')
    (root / 'link.glb').symlink_to(p)
    before = len(h.requests)
    for path in ['../bad.glb', str(root / '..' / 'mesh.glb'), str(root / 'secret.env'), str(root/'link.glb'), str(tmp_path/'outside.glb')]:
        assert c.get('/file', params={'path':path, 'asset':next(iter(h.fake.assets))}).status_code in (400,403,404,415)
    assert c.get('/file?asset=../../bad').status_code == 400
    assert c.get('/file', params={'asset':next(iter(h.fake.assets)), 'format':'exe'}).status_code == 400
    assert len(h.requests) == before


def test_jobs_aliases_active_cancel_and_delivery_urls(api):
    c, mod, h, _ = api
    def submit(tool='text-to-environment-map'):
        return json.loads(h.fake.call(tool, {'prompt':'dusk','textPrompt':'dusk','resolution':1024,'seed':1}).text)['jobId']
    jid = submit()
    assert c.get('/jobs?limit=1&offset=0').json()['jobs'][0]['uuid'] == jid
    assert c.get('/jobs/'+jid).json()['status'] == 'queued'
    assert c.get('/active', params={'tasks':jid}).json()['tasks'][0]['status'] == 'running'
    done = c.get('/task', params={'id':jid}).json()
    assert done['status'] == 'done' and done['progress'] == 100
    assert 'X-Amz-Signature=' in done['outputs']['environmentHDR']
    jid2 = submit('text-to-material')
    for _ in range(3):
        material = c.get('/task', params={'id':jid2}).json()
    assert material['outputs']['s3Uris']['normal'].startswith('s3://')
    assert c.get('/active', params={'tasks':jid}).json()['done'] == [jid]
    assert c.get('/actions', params={'id':jid,'type':'job'}).json()['actions'][0]['cost']==80
    assert c.get('/actions', params={'id':jid}).json()['actions'][0]['tool']=='environment-map-to-world'
    queued = submit()
    assert c.post('/jobs/'+queued+'/cancel').json()['status'] == 'cancelled'
    queued = submit()
    assert c.post('/cancel',json={'id':queued}).json()['status'] == 'cancelled'
    assert c.post('/cancel',json={'id':jid}).status_code == 409
    assert c.get('/jobs/nope').status_code == 400


def test_concepts(api):
    c, _, h, _ = api
    concept = json.loads(h.fake.call('studiotwin_conceptlab_create', {'conceptType':'object','name':'Hero'}).text)
    cid = concept['uuid']
    assert c.get('/concepts?limit=1&offset=0').json()['concepts'][0]['uuid'] == cid
    assert c.get('/concepts/'+cid).json()['name'] == 'Hero'
    assert c.get('/concepts/'+cid+'/status').json()['lifecycleStatus'] == 'draft'


def test_upload_local_multipart_cloud_and_no_post_secrets(api):
    c, mod, h, _ = api
    local = c.post('/upload', json={'filename':'wind.wav','data':base64.b64encode(b'RIFFlocal').decode()})
    assert local.status_code == 200, local.text
    assert Path(local.json()['path']).read_bytes() == b'RIFFlocal'
    assert h.fake.uploads == {}
    for route in ['/uploads','/upload?cloud=true']:
        r = c.post(route, files={'file':('ref.png',b'\x89PNGuploaded','image/png')})
        assert r.status_code == 200, r.text
        assert r.json()['assets'][0]['uuid'] in h.fake.assets
        assert not any(x in r.text for x in ['Policy','X-Amz-Signature','STCANARY_UPLOAD_POST'])
    assert all(not r['has_api_key'] for r in h.requests if r['path'].startswith('/storage'))
    before = len(h.requests)
    assert c.post('/uploads',json={'filename':'../../bad.png','data':'YQ=='}).status_code == 400
    assert c.post('/uploads',json={'filename':'bad.exe','data':'YQ=='}).status_code == 415
    assert len(h.requests) == before


def test_provenance_merge_labels_and_actions(api):
    c, _, h, _ = api
    a,b = list(h.fake.assets)[:2]
    jid = '00000001-0001-4000-8000-000000000001'
    record = {'id':jid,'tool':'image-to-3d-mesh','prompt':'owl','sourceAssetIds':[a],'outputAssetIds':[b],
        'conceptId':a}
    assert c.post('/provenance',json=record).status_code == 200
    assert c.post('/provenance',json={'id':jid}).status_code == 200
    assert c.get('/details',params={'id':jid}).json()['record']['prompt'] == 'owl'
    assert c.get('/provenance',params={'id':b}).json()['parents']
    assets = c.get('/assets').json()['assets']
    assert next(x for x in assets if x['uuid']==b)['made_from']
    actions = c.get('/actions',params={'id':b,'type':'3d_model'}).json()['actions']
    assert actions and all('cost' in x and 'message' in x for x in actions)
    assert all(b in x['message'] for x in actions)


def test_secrets_and_settings_resolved_per_request(api, monkeypatch):
    import agent.secret_scope
    c, _, h, settings = api
    monkeypatch.setattr(agent.secret_scope,'get_secret',lambda name:None)
    before=len(h.requests)
    assert not c.get('/status').json()['configured']
    assert len(h.requests)==before
    monkeypatch.setattr(agent.secret_scope,'get_secret',lambda name:h.api_key)
    settings['api_base_url']='http://evil.invalid'
    assert c.get('/status').status_code == 400
    assert len(h.requests)==before


@pytest.mark.parametrize('mode,expected',[('http_redirect_same_origin',200),('http_redirect_foreign',502),('http_error_body',502),('http_rate_limited',502)])
def test_transport_redirect_and_error_guards(api, mode, expected):
    c, _, _, settings = api
    import agent.secret_scope
    with serve(FakeStudioTwin(scenario(mode))) as h:
        settings['api_base_url']=h.base
        # harness keys are deterministic across instances
        r=c.get('/jobs')
        assert r.status_code==expected, r.text
        assert all(x['path'] in ('/mcp','/mcp-moved') for x in h.requests)
        assert h.api_key not in r.text and 'Policy' not in r.text


@pytest.mark.parametrize('fmt,magic', [('mp3', b'ID3'),('wav', b'RIFF'),('ogg', b'OggS'),('flac', b'fLaC')])
def test_ffmpeg_conversions_and_converted_ranges(api, fmt, magic):
    import shutil
    if not shutil.which('ffmpeg'):
        pytest.skip('ffmpeg unavailable')
    c, mod, _, _ = api
    folder=mod._data_root()
    folder.mkdir(parents=True)
    source=folder/('tone.mp3' if fmt=='wav' else 'tone.wav')
    fixture='audio/tone-44k.mp3' if fmt=='wav' else 'audio/tone-48k.wav'
    source.write_bytes((ROOT/'tests/fixtures/media'/fixture).read_bytes())
    r=c.get('/file',params={'path':str(source),'format':fmt})
    assert r.status_code==200, r.text
    data=base64.b64decode(r.json()['dataUrl'].split(',')[1])
    assert data.startswith(magic)
    part=c.get('/file',params={'path':str(source),'format':fmt},headers={'Range':'bytes=0-3'})
    assert part.status_code==206 and part.content==data[:4]
    assert not list((folder/'conversions').iterdir()) if fmt!='wav' else True


def test_missing_ffmpeg_and_bad_conversion_preflight(api,monkeypatch):
    c,mod,h,_=api
    folder=mod._data_root()
    folder.mkdir(parents=True)
    p=folder/'tone.wav'
    p.write_bytes(b'RIFF')
    monkeypatch.setattr(mod.shutil,'which',lambda _:None)
    assert c.get('/file',params={'path':str(p),'format':'mp3'}).status_code==409
    assert c.get('/status').json()['host']['conversions']==[]


def test_profile_storage_and_credentials_switch_together(api,monkeypatch,tmp_path):
    import agent.secret_scope
    c,mod,h,_=api
    first_root=mod._data_root()
    aid=next(iter(h.fake.assets))
    assert c.get('/file',params={'asset':aid}).status_code==200
    monkeypatch.setenv('HERMES_HOME',str(tmp_path/'second-profile'))
    monkeypatch.setattr(agent.secret_scope,'get_secret',lambda _:None)
    assert mod._data_root()!=first_root
    assert c.get('/assets').json()['assets']==[]
    assert not c.get('/status').json()['configured']
    monkeypatch.setattr(agent.secret_scope,'get_secret',lambda _:'wrong-key')
    assert c.get('/jobs').status_code==502
    monkeypatch.setattr(agent.secret_scope,'get_secret',lambda _:h.api_key)
    assert c.get('/jobs').status_code==200


def test_http_sse_and_session_upload(api):
    c,_,_,settings=api
    with serve(FakeStudioTwin(scenario('http_sse'))) as h:
        settings['api_base_url']=h.base
        assert c.get('/status').json()['balance']==500
        r=c.post('/uploads',json={'filename':'ref.png','data':base64.b64encode(b'png').decode()})
        assert r.status_code==200, r.text
        assert r.json()['assets'][0]['uuid'] in h.fake.assets


def test_cache_symlink_preflight_and_local_gallery_index(api,tmp_path):
    c,mod,h,_=api
    root=mod._data_root()
    root.mkdir(parents=True)
    (root/'studio_cache').symlink_to(tmp_path,target_is_directory=True)
    before=len(h.requests)
    assert c.get('/file',params={'asset':next(iter(h.fake.assets))}).status_code==403
    assert len(h.requests)==before
    (root/'studio_cache').unlink()
    cache=root/'studio_cache'
    cache.mkdir()
    (cache/'unindexed.glb').write_bytes(b'glTF')
    assert any(r['name']=='unindexed.glb' for r in c.get('/assets').json()['assets'])


def test_upload_failure_has_no_policy_or_signature_and_never_completes(api,monkeypatch):
    from fake_mcp.http import _App
    from starlette.responses import PlainTextResponse
    c,_,h,_=api
    async def broken_storage(self,scope,receive,send):
        return await PlainTextResponse('Policy=STCANARY_UPLOAD_POST_POLICY_029475eaca X-Amz-Signature=SECRET',503)(scope,receive,send)
    monkeypatch.setattr(_App,'_storage',broken_storage)
    r=c.post('/uploads',files={'file':('x.png',b'png')})
    assert r.status_code==502
    assert 'Policy' not in r.text and 'Signature' not in r.text and 'SECRET' not in r.text
    assert not any(call['name']=='studiotwin_complete_asset_upload' for call in h.fake.calls)


def test_no_deleted_runtime_dependencies_or_unserializable_response_markers():
    import ast
    for path in (ROOT/'dashboard').glob('*.py'):
        text=path.read_text()
        assert all(marker not in text for marker in ('StreamingResponse','WebSocket','ipc_client','gateway.'))
        for node in ast.walk(ast.parse(text)):
            if isinstance(node,ast.ImportFrom):
                assert not any(marker in (node.module or '') for marker in ('redaction','classification'))


@pytest.mark.parametrize('storage,target',[(False,'https://foreign.invalid/mcp'),
    (False,'https://user:password@api.studiotwin.ai/mcp'),
    (True,'https://other-bucket.s3.amazonaws.com/upload')])
def test_foreign_redirect_never_reaches_target(api,storage,target):
    import httpx
    from fastapi import HTTPException
    _,mod,_,_=api
    hits=[]
    def respond(req):
        hits.append(str(req.url))
        return httpx.Response(307,headers={'location':target}) if len(hits)==1 else httpx.Response(200,content=b'leaked')
    with mod.client_module.StudioTwinClient('https://api.studiotwin.ai','synthetic-key') as client:
        client.http.close()
        client.http=httpx.Client(transport=httpx.MockTransport(respond))
        url='https://bucket.s3.amazonaws.com/upload' if storage else 'https://api.studiotwin.ai/mcp'
        with pytest.raises(HTTPException):
            client.request('POST',url,storage=storage,data={'Policy':'synthetic-policy'})
    assert hits==[url]


def test_upload_tar_derives_entries_without_extracting(api):
    c,_,h,_=api
    payload=(ROOT/'tests/fixtures/media/sequence/frames-4x16.tar').read_bytes()
    r=c.post('/uploads',files={'file':('frames.tar',payload)})
    assert r.status_code==200,r.text
    assert r.json()['assets'][0]['type']=='image_sequence'
    completed=next(x for x in h.fake.calls if x['name']=='studiotwin_complete_asset_upload')
    assert len(completed['args']['entries'])==4
    before=len(h.requests)
    hostile=(ROOT/'tests/fixtures/media/sequence/traversal-hostile.tar').read_bytes()
    assert c.post('/uploads',files={'file':('hostile.tar',hostile)}).status_code==400
    assert len(h.requests)==before
