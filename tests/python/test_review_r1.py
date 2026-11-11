"""Review repairs at the real HTTP boundary; cloud/storage are offline seams."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time

import pytest
from fastapi import HTTPException
from tests.python.test_plugin_api import api

JID = '000010b5-0001-4000-8000-000000000001'
AID = '000010b5-0001-4000-8000-000000000002'
FORMS = [('meshUrl','3d_model','.glb'), ('modelUrl','3d_model','.glb'),
         ('mesh','3d_model','.glb'), ('worldMesh','3d_model','.glb'),
         ('hdrUrl','environment','.hdr'), ('environmentHDR','environment','.hdr'),
         ('panoramaHDR','environment','.hdr'), ('imageUrl','image','.png'),
         ('audioUrl','audio','.wav'), ('audioClip','audio','.wav'), ('videoUrl','video','.mp4')]


def test_cloud_outage_preserves_local_with_explicit_partial_inventory(api, monkeypatch):
    c, m, _, _ = api
    local = Path.home() / 'local.glb'
    local.write_bytes(b'glTF')
    m._index().record(local, kind='3d_model')
    def outage(*_):
        raise HTTPException(502, 'do not echo provider details')
    monkeypatch.setattr(m, '_call', outage)
    r = c.get('/assets')
    assert r.status_code == 200
    body = r.json()
    assert body['configured'] and body['partial']
    assert body['cloud_status'] == 'unavailable'
    assert body['assets'][0]['path'] == str(local)
    assert body['total'] == 1 and body['next_offset'] is None
    assert 'do not echo' not in r.text
    monkeypatch.setattr(m, '_api_key', lambda: None)
    assert c.get('/assets').json()['cloud_status'] == 'not_configured'


@pytest.mark.parametrize('key,kind,ext', FORMS)
def test_output_action_intersection_and_job_identity(api, monkeypatch, key, kind, ext):
    c, m, _, _ = api
    url = 'https://fixture.invalid/output' + ext
    monkeypatch.setattr(m, '_job', lambda _: {'status':'done', 'outputs':{key:url}})
    class Storage:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def request(self, *_, **__): return {}, b'offline media'
    monkeypatch.setattr(m, '_client', Storage)
    output = c.get(f'/jobs/{JID}/output')
    assert output.status_code == 200, output.text
    assert output.json()['type'] == kind
    assert output.json()['jobId'] == JID
    actions = c.get('/actions', params={'id':JID,'type':'job'}).json()
    assert actions['type'] == kind
    if kind not in ('audio','video'):
        assert actions['actions']
    for action in actions['actions']:
        assert f'StudioTwin job {JID}' in action['message']
        assert f'asset {JID}' not in action['message']
        assert 'resolve' in action['message'].lower()
        assert 'approve' in action['message'] and 'studiotwin_estimate_cost' in action['message']


@pytest.mark.parametrize('reference', ['assetId', 'assetIds', 'outputAssetIds'])
def test_asset_backed_job_uses_actual_asset_identity(api, monkeypatch, reference):
    c, m, _, _ = api
    row = {'status':'done', 'outputs':{reference:AID if reference == 'assetId' else [AID]}}
    monkeypatch.setattr(m, '_job', lambda _: row)
    monkeypatch.setattr(m, '_call', lambda *_: {'uuid':AID,'type':'3d_model','name':'mesh.glb'})
    actions = c.get('/actions', params={'id':JID,'type':'job'}).json()
    assert actions['type'] == '3d_model' and actions['actions']
    for a in actions['actions']:
        assert f'asset {AID}' in a['message'] and f'asset {JID}' not in a['message']
    output = c.get(f'/jobs/{JID}/output')
    assert output.status_code == 200 and output.json()['uuid'] == AID
    assert output.json()['jobId'] == JID


def test_job_cache_sequential_concurrent_rotated_expired_changed_and_missing(api, monkeypatch):
    c, m, _, _ = api
    state = {'url':'https://fixture.invalid/one.glb?X-Amz-Signature=first', 'reads':0, 'expired':False}
    monkeypatch.setattr(m, '_job', lambda _: {'status':'done','outputs':{'meshUrl':state['url']}})
    class Storage:
        def __enter__(self): return self
        def __exit__(self, *_): pass
        def request(self, *_, **__):
            state['reads'] += 1
            time.sleep(.03)
            if state['expired']: raise HTTPException(502, 'expired')
            return {}, b'glTF output'
    monkeypatch.setattr(m, '_client', Storage)
    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: c.get(f'/jobs/{JID}/output'), range(4)))
    assert all(r.status_code == 200 for r in responses)
    paths = {r.json()['path'] for r in responses}
    assert len(paths) == 1 and state['reads'] == 1
    first = paths.pop()
    state['url'] = 'https://fixture.invalid/one.glb?X-Amz-Signature=rotated'
    state['expired'] = True
    assert c.get(f'/jobs/{JID}/output').json()['path'] == first
    assert state['reads'] == 1
    state['expired'] = False
    state['url'] = 'https://fixture.invalid/two.glb?versionId=2'
    changed = c.get(f'/jobs/{JID}/output').json()['path']
    assert changed != first and state['reads'] == 2
    state['url'] = 'https://fixture.invalid/two.glb?versionId=3'
    versioned = c.get(f'/jobs/{JID}/output').json()['path']
    assert versioned != changed and state['reads'] == 3
    Path(versioned).unlink()
    assert c.get(f'/jobs/{JID}/output').json()['path'] != versioned
    assert state['reads'] == 4
    assert len(m._index().rows()) == 4


def test_nonterminal_job_never_downloads_or_offers_actions(api, monkeypatch):
    c, m, _, _ = api
    monkeypatch.setattr(m, '_job', lambda _: {'status':'running','outputs':{'meshUrl':'https://fixture.invalid/x.glb'}})
    assert c.get(f'/jobs/{JID}/output').status_code == 409
    assert c.get('/actions',params={'id':JID,'type':'job'}).json()['actions'] == []
