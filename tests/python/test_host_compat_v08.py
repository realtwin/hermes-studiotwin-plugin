"""Real-host V08 admission and negative packaging regressions (no remote calls)."""
from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('verify_v08_host_compat', ROOT / 'tools' / 'verify_v08_host_compat.py')
assert SPEC is not None and SPEC.loader is not None
verification = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(verification)
HOST = Path(os.environ.get('HERMES_REFERENCE_ROOT', str(verification.DEFAULT_HOST)))
DEPENDENCIES = Path(os.environ.get('HERMES_HOST_DEPENDENCIES', str(verification.HOST_DEPENDENCIES)))


@pytest.fixture
def sandbox():
    # Fail rather than silently skipping the actual host acceptance tests.
    assert (HOST / 'hermes_cli' / 'plugin_validate.py').is_file(), HOST
    assert os.environ.get('TMPDIR'), 'set TMPDIR to disposable scratch storage'
    with tempfile.TemporaryDirectory(prefix='v08-host-test-', dir=os.environ['TMPDIR']) as temp:
        base = Path(temp)
        env = verification.isolated_env(base, HOST, DEPENDENCIES)
        plugin = verification.copy_plugin(ROOT, Path(env['HERMES_HOME']) / 'plugins' / 'hermes-studiotwin')
        yield base, env, plugin
    assert not base.exists()


def run_probe(sandbox):
    base, env, plugin = sandbox
    return verification.run_command([sys.executable, str(ROOT / 'tools' / 'verify_v08_host_compat.py'),
                                     '--probe', str(plugin)], env, base)


def test_real_host_admission_and_runtime(sandbox):
    result = run_probe(sandbox)
    assert result['returncode'] == 0, result
    report = json.loads(result['stdout'])
    assert report['ok'] is True
    assert all(report['checks'].values()), report
    assert report['validation']['ok'] is True
    assert report['validation']['warnings'] == []
    assert report['validation']['isolation']['host_ready'] is True
    assert report['validation']['isolation']['verdict'] == 'portable'
    assert report['python_declaration']['pyproject_installs'] is False
    assert report['doctor']['ok'] is True
    assert report['doctor']['findings'] == []
    assert report['skills'] == ['studiotwin']
    assert report['mcp_servers'] == ['studiotwin']
    assert '/status' in report['dashboard_routes']
    assert Path(report['host_module']).is_relative_to(HOST.resolve())


def test_reference_cli_validate_and_doctor(sandbox):
    base, env, plugin = sandbox
    prefix = [sys.executable, '-m', 'hermes_cli.main', 'plugins']
    commands = {
        'validate': verification.run_command(prefix + ['validate', str(plugin), '--json'], env, base),
        # The inspected reference parser supports --ci, but NOT --json here.
        'doctor': verification.run_command(prefix + ['doctor', str(plugin), '--ci'], env, base),
    }
    assert all(verification.cli_checks(commands).values()), commands


def test_reference_doctor_rejects_unsupported_json_flag(sandbox):
    base, env, plugin = sandbox
    result = verification.run_command(
        [sys.executable, '-m', 'hermes_cli.main', 'plugins', 'doctor', str(plugin), '--ci', '--json'],
        env, base)
    assert result['returncode'] == 2, result
    assert 'unrecognized arguments: --json' in result['stderr'], result


@pytest.mark.parametrize('corruption', ['invalid-json', 'missing-name', 'unknown-server-field'])
def test_real_host_rejects_corrupted_manifest(sandbox, corruption):
    _, _, plugin = sandbox
    manifest = plugin / 'plugin.json'
    data = json.loads(manifest.read_text())
    if corruption == 'invalid-json':
        manifest.write_text('{broken')
    else:
        if corruption == 'missing-name':
            del data['name']
        else:
            data['extensions']['com.nousresearch.hermes']['servers']['studiotwin']['not_supported'] = True
        manifest.write_text(json.dumps(data))
    result = run_probe(sandbox)
    assert result['returncode'] != 0, result
    if corruption == 'unknown-server-field':
        report = json.loads(result['stdout'])
        assert report['validation']['warnings']
        assert report['checks']['manifest'] is False
        assert report['ok'] is False
    else:
        assert 'AgentPluginError' in result['stderr'] or 'ValueError' in result['stderr'], result


@pytest.mark.parametrize('declaration', [
    '\n[build-system]\nrequires = ["setuptools"]\nbuild-backend = "setuptools.build_meta"\n',
    '\n[tool.uv]\npackage = true\n',
])
def test_real_host_buildable_pyproject_fails_compatibility(sandbox, declaration):
    _, _, plugin = sandbox
    project = plugin / 'pyproject.toml'
    project.write_text(project.read_text() + declaration)
    result = run_probe(sandbox)
    assert result['returncode'] != 0, result
    report = json.loads(result['stdout'])
    # Portable validation currently omits Python packaging checks; our separate
    # real PM declaration check must catch this multi-profile workspace hazard.
    assert report['python_declaration']['pyproject_installs'] is True
    assert report['checks']['python'] is False
    assert report['ok'] is False


def test_child_environment_drops_live_credentials(sandbox, monkeypatch):
    base, _, _ = sandbox
    monkeypatch.setenv('STUDIOTWIN_API_KEY', 'must-not-be-inherited')
    monkeypatch.setenv('OPENAI_API_KEY', 'must-not-be-inherited')
    monkeypatch.setenv('HERMES_PROFILE', 'live-profile')
    monkeypatch.setenv('PYTHONPATH', '/must-not-be-inherited')
    monkeypatch.setenv('HERMES_HOME', '/must-not-be-written')
    env = verification.isolated_env(base, HOST, DEPENDENCIES)
    assert env['STUDIOTWIN_API_KEY'] == verification.DUMMY_KEY
    assert 'OPENAI_API_KEY' not in env and 'HERMES_PROFILE' not in env
    assert Path(env['HERMES_HOME']).is_relative_to(base)
    assert Path(env['TMPDIR']).is_relative_to(base)
    assert env['PYTHONPATH'] == os.pathsep.join((str(HOST), str(DEPENDENCIES)))


def test_command_failure_is_evidence_not_success(sandbox):
    base, env, _ = sandbox
    result = verification.run_command([str(base / 'missing-hermes')], env, base)
    assert result['returncode'] == -1
    assert 'FileNotFoundError' in result['stderr']


@pytest.mark.parametrize(('api_ok', 'reference_ok', 'installed_ok', 'expected'), [
    (True, True, False, True),
    (True, True, True, True),
    (True, False, True, False),
    (False, True, True, False),
])
def test_only_reference_api_and_cli_gate_admission(
        monkeypatch, api_ok, reference_ok, installed_ok, expected):
    """Unit-level command doubles prove the authority ruling, not host admission."""
    def command_double(argv, env, cwd):
        if '--probe' in argv:
            ok, stdout = api_ok, json.dumps({'ok': api_ok})
        else:
            ok = reference_ok if argv[0] == sys.executable else installed_ok
            stdout = (json.dumps({'ok': ok, 'warnings': []}) if 'validate' in argv
                      else ('OK: runtime discovery' if ok else 'ERROR: rejected'))
        return {'argv': argv, 'returncode': 0 if ok else 1, 'stdout': stdout, 'stderr': ''}

    monkeypatch.setattr(verification, 'run_command', command_double)
    report = verification.verify(ROOT, HOST, sys.executable, '/installed/hermes', DEPENDENCIES)
    assert report['ok'] is expected
    assert report['authoritative_source'] == 'reference'
    assert bool(report['limitations']) is not installed_ok
    assert report['cli_checks']['installed']['validate'] is installed_ok
    assert not Path(report['scratch_home']).exists()
