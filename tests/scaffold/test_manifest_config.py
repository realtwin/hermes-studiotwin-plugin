"""Portable v2 manifest contracts against the real pinned Hermes host.

These replace the retired S01 assertions requiring a local stdio gateway. Node
runner, license and dotted pytest-filename checks remain independently exercised.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
from hermes_cli.agent_plugins import AgentPluginError, load_agent_plugin, manifest_config_schema
from hermes_cli.plugin_validate import ValidationReport, _check_config_spec
from hermes_cli.plugins_settings import _field_type, secret_env_name
from pm.plugin_declarations import read_python_declaration

ROOT = Path(__file__).resolve().parents[2]
CORE = Path('/home/deploy/work/realtwin/hermes-studiotwin/reference/hermes-agent')
UPSTREAM = Path('/home/deploy/work/realtwin/hermes-studiotwin/reference/hermes-official-plugins')
UPSTREAM_SHA = '1e326ddd28ae261821d7714d106fe114999a0bba'


def _manifests():
    return tuple(json.loads((ROOT / name).read_text()) for name in ('plugin.json','mcp.json'))


def _package(tmp_path, plugin=None, mcp=None):
    p,m = _manifests()
    root = tmp_path / 'plugin'
    root.mkdir()
    (root/'plugin.json').write_text(json.dumps(plugin or p))
    (root/'mcp.json').write_text(json.dumps(mcp or m))
    return load_agent_plugin(root,tmp_path/'data')


def test_reference_host_and_remote_transport(tmp_path):
    import hermes_cli.agent_plugins as host
    assert Path(host.__file__).resolve() == CORE/'hermes_cli/agent_plugins.py'
    package = _package(tmp_path)
    assert package.name == 'hermes-studiotwin' and package.version == '0.3.2'
    assert package.diagnostics == ()
    assert set(package.mcp_servers) == {'studiotwin'}
    s = package.mcp_servers['studiotwin']
    assert s['url'] == 'https://api.studiotwin.ai/mcp'
    assert s['strict_redirect_headers'] is True
    assert not {'command','args','cwd','env','spend_limit'} & s.keys()
    assert s['trust'] == 'untrusted' and s['timeout'] == 1500 and s['cost_unit'] == 'credits'


def test_cost_table_matches_capture_without_inventing_fixed_variable_prices(tmp_path):
    tools = json.loads((ROOT/'tests/fixtures/tools-list-2026-10-30.json').read_text())['tools']
    expected = {t['name'] for t in tools[:24]} | {
        'studiotwin_conceptlab_create_and_generate','studiotwin_conceptlab_generate','studiotwin_conceptlab_edit'}
    costs = _package(tmp_path).mcp_servers['studiotwin']['tool_costs']
    assert set(costs) == expected and len(costs) == 27
    # Capture includes the free rig-check among its 24 generation tools. Do not
    # turn its published zero into a positive price just to call all 27 paid.
    for t in tools[:24]:
        fixed = re.search(r'Costs (\d+) credits',t['description'])
        if fixed:
            assert costs[t['name']] == int(fixed[1])
        else:
            value = costs[t['name']]
            assert isinstance(value,dict) and 'studiotwin_estimate_cost' in value['note']
            assert 'not a provider maximum' in value['note']


def test_settings_types_and_defaults():
    schema = manifest_config_schema(_manifests()[0])
    assert set(schema) == {'api_key','api_base_url','show_credits','inline_cards','auto_rotate',
                           'webgl_limit','gallery_limit','blender_handoff','blender_path'}
    assert _field_type(schema['api_key']) == 'secret'
    assert secret_env_name('hermes-studiotwin','api_key',schema['api_key']) == 'STUDIOTWIN_API_KEY'
    assert schema['api_base_url']['default'] == 'https://api.studiotwin.ai'
    assert schema['blender_handoff']['choices'] == ['ask','always','never']
    assert schema['webgl_limit']['default'] == 4 and schema['gallery_limit']['default'] == 24
    report = ValidationReport()
    _check_config_spec(report,{'config_schema':schema})
    assert report.ok, report.failures
    assert all(s.get('description') for s in schema.values())


def test_remote_headers_interpolate_only_calling_profile_secret(tmp_path, monkeypatch):
    from agent.secret_scope import reset_secret_scope, set_secret_scope
    from tools.mcp_tool_config import _interpolate_env_vars
    monkeypatch.delenv('STUDIOTWIN_API_KEY',raising=False)
    server = _package(tmp_path).mcp_servers['studiotwin']
    for key in ('synthetic-profile-a','synthetic-profile-b'):
        token = set_secret_scope({'STUDIOTWIN_API_KEY':key},profile_home=str(tmp_path/key))
        try:
            assert _interpolate_env_vars(server)['headers']['x-api-key'] == key
        finally:
            reset_secret_scope(token)
        assert key not in json.dumps(server)


@pytest.mark.parametrize('url',['http://evil.invalid/mcp','https://user:password@evil.invalid/mcp','file:///etc/passwd'])
def test_host_rejects_unsafe_remote_url(tmp_path,url):
    p,m = _manifests()
    m['mcpServers']['studiotwin']['url'] = url
    with pytest.raises(AgentPluginError):
        _package(tmp_path,mcp=m)


def test_host_rejects_widened_trust(tmp_path):
    p,_ = _manifests()
    p['extensions']['com.nousresearch.hermes']['servers']['studiotwin']['trust']='trusted'
    with pytest.raises(AgentPluginError):
        _package(tmp_path,plugin=p)


def test_non_buildable_python_dependency_declaration():
    doc = tomllib.loads((ROOT/'pyproject.toml').read_text())
    assert set(doc) == {'project'}
    assert doc['project']['dependencies'] == ['httpx>=0.27,<1']
    assert doc['project']['requires-python'] == '>=3.11'
    assert read_python_declaration(ROOT).pyproject_installs is False


def test_node_project_and_lock_pin_the_serial_vitest_runner():
    package = json.loads((ROOT/'package.json').read_text())
    lock = json.loads((ROOT/'package-lock.json').read_text())
    deps = {**package.get('dependencies',{}),**package['devDependencies']}
    assert package['engines']['node'] == '>=24.0.0'
    assert deps['vitest'] == '3.2.7' and lock['lockfileVersion'] == 3
    for name,spec in deps.items():
        assert spec[0].isdigit() and lock['packages'][f'node_modules/{name}']['version'] == spec
    assert 'jest' not in json.dumps(package)


def test_pytest_dotted_filename_collection(tmp_path):
    (tmp_path/'tests/docs').mkdir(parents=True)
    shutil.copy(ROOT/'pytest.ini',tmp_path/'pytest.ini')
    (tmp_path/'tests/docs/release.test.py').write_text('def test_release_probe():\n    assert True\n')
    for args in (['tests/docs/release.test.py'],['tests']):
        result = subprocess.run([sys.executable,'-B','-m','pytest',*args,'-q'],cwd=tmp_path,
                                env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'},capture_output=True,text=True)
        assert result.returncode == 0, result.stdout+result.stderr
        assert '1 passed' in result.stdout


@pytest.mark.parametrize(('target','upstream','year'),[
    ('licenses/MESHY-LICENSE','meshy/LICENSE','2025'),
    ('licenses/ELEVENLABS-SFX-LICENSE','elevenlabs-sound-effects/LICENSE','2026'),
    ('licenses/ELEVENLABS-MUSIC-LICENSE','elevenlabs-music/LICENSE','2026')])
def test_licenses_preserve_upstream_copyright(target,upstream,year):
    ours = (ROOT/target).read_bytes()
    assert f'Copyright (c) {year} Nous Research'.encode() in ours
    assert ours.startswith(b'MIT License')
    if UPSTREAM.is_dir():
        assert hashlib.sha256(ours).digest() == hashlib.sha256((UPSTREAM/upstream).read_bytes()).digest()
    assert f'retained | {target} | {upstream}@{UPSTREAM_SHA} | verbatim | MIT, Copyright (c) {year} Nous Research' in (ROOT/'NOTICE').read_text()


def test_no_other_provider_runtime_or_local_gateway():
    text = json.dumps(_manifests()).lower()
    assert all(marker not in text for marker in ('meshy','elevenlabs','npx','gateway','spend_limit'))
