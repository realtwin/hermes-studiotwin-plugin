"""HTTP-boundary regression for input-heavy MCP metadata, without paid calls."""
import importlib.util
import json
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]


@pytest.mark.parametrize('wire', ['text', 'structured', 'sse'])
@pytest.mark.parametrize('route,tool', [('/jobs?limit=24&offset=0', 'studiotwin_list_my_jobs'),
    ('/jobs/11111111-1111-4111-8111-111111111111', 'studiotwin_get_job_status')])
def test_oversized_input_does_not_hide_jobs(monkeypatch, wire, route, tool):
    spec = importlib.util.spec_from_file_location('payload_api', ROOT / 'dashboard/plugin_api.py')
    api = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(api)
    url = 'https://assets.studiotwin.ai/model.glb?X-Amz-Signature=preserve-exact'
    bad = {'uuid': '11111111-1111-4111-8111-111111111111', 'status': 'failed',
           'inputs': {'prompt': 'keep me', 'images': [{'url': 'data:image/png;base64,' + 'A' * (9 * 1024 * 1024)}]},
           'outputs': {'meshUrl': url}}
    good = {'uuid': '22222222-2222-4222-8222-222222222222', 'status': 'done', 'inputs': {'image': 's3://bucket/key'}}
    value = [bad, good] if 'list' in tool else bad
    def handler(request):
        body = json.loads(request.content) if request.method == 'POST' else {}
        if body.get('method') == 'notifications/initialized' or request.method == 'DELETE':
            return httpx.Response(202)
        result = {'protocolVersion': '2025-06-18'}
        if body.get('method') == 'tools/call':
            assert body['params']['name'] == tool
            result = ({'structuredContent': value} if wire == 'structured' else
                      {'content': [{'type': 'text', 'text': json.dumps(value)}]})
        data = json.dumps({'jsonrpc': '2.0', 'id': body['id'], 'result': result}).encode()
        return httpx.Response(200, content=(b'data: ' + data + b'\n\n') if wire == 'sse' else data,
                              headers={'content-type': 'text/event-stream' if wire == 'sse' else 'application/json'})
    def client():
        c = api.client_module.StudioTwinClient('https://api.studiotwin.ai', 'fixture-only')
        c.http.close()
        c.http = httpx.Client(transport=httpx.MockTransport(handler))
        return c
    monkeypatch.setattr(api, '_client', client)
    app = FastAPI()
    app.include_router(api.router)
    with TestClient(app) as http:
        response = http.get(route)
    assert response.status_code == 200, response.text[:200]
    rows = response.json()['jobs'] if 'list' in tool else [response.json()]
    assert len(rows) == (2 if 'list' in tool else 1)
    assert rows[0]['uuid'] == bad['uuid'] and rows[0]['status'] == 'failed'
    assert rows[0]['inputs_truncated'] is True
    assert rows[0]['inputs']['prompt'] == 'keep me'
    assert rows[0]['outputs']['meshUrl'] == url
    if len(rows) == 2:
        assert rows[1] == good
    assert len(response.content) < 65536
