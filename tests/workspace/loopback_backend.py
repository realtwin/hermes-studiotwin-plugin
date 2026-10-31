"""V06 browser backend: real plugin router -> real HTTP MCP -> FakeStudioTwin.

Only host-owned configuration/secret/home boundaries are replaced. Every address is
loopback and the key is a fixture canary. No paid generation is submitted, even to
the fake: jobs are seeded directly. A private temporary home is always removed.
"""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import socket
import sys
import tempfile
import types

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests/fixtures'))

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
import uvicorn
from fake_mcp.http import serve
from fake_mcp.state import FakeStudioTwin, Job


def host_module(name, **attrs):
    module = types.ModuleType(name)
    module.__dict__.update(attrs)
    sys.modules[name] = module
    if '.' in name:
        parent, child = name.rsplit('.', 1)
        if parent not in sys.modules:
            host_module(parent)
        setattr(sys.modules[parent], child, module)


def main():
    with tempfile.TemporaryDirectory(prefix='v06-workspace-', dir=os.environ.get('TMPDIR')) as directory:
        home = Path(directory)
        os.environ['HERMES_HOME'] = str(home / '.hermes')
        Path.home = classmethod(lambda cls: home)
        fake = FakeStudioTwin()
        parent, mesh = list(fake.assets)[:2]
        second = fake._new_asset('hero-iteration.png', 'image', 'user', media_rel='image/concept-64.png')['uuid']
        concept = json.loads(fake.call('studiotwin_conceptlab_create', {'conceptType': 'object', 'name': 'Hero study'}).text)['uuid']
        for aid in (parent, second):
            fake.call('studiotwin_conceptlab_attach_asset', {'conceptId': concept, 'assetId': aid, 'makeActive': True})
        # Direct state seeds, not generation tools: the fixture wallet stays at 500.
        ids = {}
        for index, state in enumerate(('queued', 'done', 'failed', 'cancelled'), 1):
            jid = f'000010b5-{index:04x}-4000-8000-{index:012x}'
            job = Job(uuid=jid, function_name='openai-gpt-image-2-v4-fn', inputs={'prompt': 'Seeded workspace image'},
                      estimate=6, cost=6, provider='fixture', created_ms=fake.clock_ms, schedule=(state,))
            job.status = state
            fake.jobs[jid] = job
            ids[state] = jid
        with serve(fake) as remote:
            fake.jobs[ids['done']].outputs = {'imageUrl': fake.signed_url(fake.assets[parent]['s3Uri'].split('/', 3)[3])}
            host_module('agent.secret_scope', get_secret=lambda name: remote.api_key if settings['configured'] else None)
            settings = {'configured': True, 'show_credits': True}
            host_module('hermes_cli.config', load_config_readonly=lambda: {'plugins': {'entries': {
                'hermes-studiotwin': {'settings': {'api_base_url': remote.base, 'show_credits': settings['show_credits']}}}}})
            host_module('hermes_constants', get_hermes_home=lambda: home / '.hermes')
            spec = importlib.util.spec_from_file_location('workspace_plugin_api', ROOT / 'dashboard/plugin_api.py')
            api = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(api)
            api._provenance().record(mesh, {'id': mesh, 'prompt': 'Fixture reference', 'sourceAssetIds': [parent], 'session_id': 'origin-chat'})
            # Typed cached material metadata exercises the existing local index contract;
            # it does not claim the provider's generic image list includes PBR map roles.
            import shutil
            cached = home / 'cached'
            cached.mkdir()
            maps = {}
            for channel in ('albedo', 'normal', 'roughness', 'metalness'):
                path = cached / f'pbr-{channel}.png'
                shutil.copyfile(ROOT / f'tests/fixtures/media/material/pbr-{channel}.png', path)
                maps[channel] = {'path': str(path)}
            api.store.write_json(api._index().path, [{'path': maps['albedo']['path'], 'type': 'texture', 'maps': maps}])
            fake._new_asset('studio.hdr', 'image', 'generated', media_rel='env/equirect-64x32.hdr')
            app = FastAPI()
            app.include_router(api.router, prefix='/api/plugins/hermes-studiotwin')
            requests = []

            @app.middleware('http')
            async def track(request: Request, call_next):
                if request.url.path.startswith('/api/'):
                    requests.append({'method': request.method, 'path': request.url.path, 'query': request.url.query})
                return await call_next(request)

            @app.get('/')
            def index():
                return HTMLResponse('<style>:root{--ui-text-primary:#ddd;--ui-text-secondary:#aaa;--ui-bg-card:#222;--ui-stroke-secondary:#555;--ui-accent:#58a}body{background:#181818;color:#ddd;font:14px system-ui}button,input{margin:4px}</style><div id="root"></div>')

            @app.get('/__test/state')
            def state():
                return {'parent': parent, 'mesh': mesh, 'concept': concept, 'jobs': ids,
                        'requests': requests, 'calls': fake.calls, 'storage_requests': remote.requests,
                        'upload_count': len(fake.uploads), 'balance': fake.balance,
                        'ledger': fake.ledger, 'submissions': fake.vp_submissions}

            @app.post('/__test/credits/{value}')
            def show_credits(value: str):
                settings['show_credits'] = value == 'true'
                return settings

            @app.post('/__test/configured/{value}')
            def configured(value: str):
                settings['configured'] = value == 'true'
                return settings

            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            print(json.dumps({'url': f'http://127.0.0.1:{port}'}), flush=True)
            uvicorn.run(app, host='127.0.0.1', port=port, log_level='warning', access_log=False)


if __name__ == '__main__':
    main()
