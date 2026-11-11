"""No-spend V08 admission proof against a real Hermes checkout and CLI.

Run with a disposable interpreter containing the host dependencies. Nothing is
installed or enabled in a live profile. All child homes and caches are temporary.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HOST = ROOT.parents[1] / 'reference' / 'hermes-agent'
DUMMY_KEY = 'v08-host-compat-dummy-not-a-real-key'
# Explicit dependency location, never an inherited PYTHONPATH or live profile.
HOST_DEPENDENCIES = Path('/opt/openclaw/claude-code/.hermes/hermes-agent/.hermes/py')
IGNORE = shutil.ignore_patterns('.git', '.venv', 'node_modules', '__pycache__',
                               '.pytest_cache', '.verification', 'evidence', '*.pyc')


def copy_plugin(source: Path, destination: Path) -> Path:
    """Copy actual payload, not dependency trees or prior evidence."""
    shutil.copytree(source, destination, ignore=IGNORE)
    return destination


def isolated_env(base: Path, host_root: Path,
                 dependencies: Path = HOST_DEPENDENCIES) -> dict[str, str]:
    # Deliberately do not inherit credentials, active-profile selectors or Python paths.
    env = {key: os.environ[key] for key in ('PATH', 'LANG', 'LC_ALL', 'SYSTEMROOT')
           if key in os.environ}
    for name in ('home', 'tmp', 'hermes', 'bundled', 'cache', 'config', 'data'):
        (base / name).mkdir(parents=True, exist_ok=True)
    env.update(HOME=str(base / 'home'), TMPDIR=str(base / 'tmp'),
               HERMES_HOME=str(base / 'hermes'),
               HERMES_BUNDLED_PLUGINS=str(base / 'bundled'),
               HERMES_ENABLE_PROJECT_PLUGINS='0',
               XDG_CACHE_HOME=str(base / 'cache'), XDG_CONFIG_HOME=str(base / 'config'),
               XDG_DATA_HOME=str(base / 'data'),
               PYTHONPATH=os.pathsep.join((str(host_root), str(dependencies))),
               PYTHONDONTWRITEBYTECODE='1', STUDIOTWIN_API_KEY=DUMMY_KEY,
               NO_COLOR='1', TERM='dumb')
    return env


def run_command(argv: list[str], env: dict[str, str], cwd: Path) -> dict:
    try:
        result = subprocess.run(argv, env=env, cwd=cwd, text=True,
                                capture_output=True, timeout=180, check=False)
        return {'argv': argv, 'returncode': result.returncode,
                'stdout': result.stdout, 'stderr': result.stderr}
    except (OSError, subprocess.TimeoutExpired) as exc:
        return {'argv': argv, 'returncode': -1, 'stdout': '',
                'stderr': f'{type(exc).__name__}: {exc}'}


def probe(plugin: Path) -> dict:
    """Executed only in a fresh child with the reference checkout on PYTHONPATH."""
    import hermes_cli.plugin_validate as validator
    from hermes_cli.agent_plugins import load_agent_plugin
    from hermes_cli.plugin_dev import doctor_plugin
    from hermes_cli.plugins import PluginManager
    from pm.plugin_declarations import read_python_declaration

    validation = validator.validate_plugin_dir(plugin).to_dict()
    declaration = read_python_declaration(plugin)
    package = load_agent_plugin(plugin, Path(os.environ['HERMES_HOME']) / 'plugin-data')
    doctor = doctor_plugin(plugin)
    manager = PluginManager()
    try:
        manifests = manager._scan_directory(plugin.parent, source='user')
        assert len(manifests) == 1, 'expected one installed plugin'
        manager._load_plugin(manifests[0])
        record = manager._plugins.get(manifests[0].key or manifests[0].name)
        loaded = bool(record and record.enabled and not record.error)
        registered_skills = manager.list_plugin_skills(manifests[0].key or manifests[0].name)
        registered_mcp = manager.get_portable_mcp_servers()
    finally:
        manager.unload()
    # The dashboard host also imports this backend by file path, without a package.
    spec = importlib.util.spec_from_file_location('hermes_dashboard_plugin_hermes_studiotwin',
                                                plugin / 'dashboard' / 'plugin_api.py')
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from fastapi import APIRouter
    routes = sorted(route.path for route in module.router.routes)
    isolation = validation.get('isolation', {})
    servers = package.mcp_servers
    mcp = servers.get('studiotwin', {})
    checks = {
        'manifest': validation.get('ok') is True and not package.diagnostics,
        'python': declaration.pyproject_installs is False,
        'mcp': (mcp.get('url') == 'https://api.studiotwin.ai/mcp'
                and mcp.get('headers', {}).get('x-api-key') == '${STUDIOTWIN_API_KEY}'
                and mcp.get('strict_redirect_headers') is True
                and mcp.get('trust') == 'untrusted'),
        'desktop': (plugin / 'desktop' / 'plugin.js').is_file(),
        'skills': [skill.name for skill in package.skills] == ['studiotwin'],
        'isolation': isolation.get('host_ready') is True and isolation.get('verdict') == 'portable',
        'runtime_loaded': loaded and registered_skills == ['studiotwin']
                          and any(config == mcp for config in registered_mcp.values()),
        'dashboard': isinstance(module.router, APIRouter) and bool(routes),
        'doctor': doctor.ok and not doctor.findings,
    }
    return {'ok': all(checks.values()) and validation.get('warnings') == [],
            'checks': checks, 'validation': validation,
            'python_declaration': {'pyproject_installs': declaration.pyproject_installs,
                                   'requirements': list(declaration.install_requirements)},
            'doctor': {'ok': doctor.ok, 'kind': getattr(doctor.manifest, 'kind', None),
                       'findings': [vars(item) for item in doctor.findings],
                       'text': doctor.format_text()},
            'skills': [skill.name for skill in package.skills],
            'mcp_servers': sorted(servers), 'dashboard_routes': routes,
            'host_module': str(Path(validator.__file__).resolve())}


def cli_checks(group: dict) -> dict[str, bool]:
    """Require real validation JSON and the reference doctor's success message."""
    try:
        validation = json.loads(group['validate']['stdout'])
    except (ValueError, TypeError):
        validation = {}
    doctor = group['doctor']
    return {
        'validate': (group['validate']['returncode'] == 0
                     and isinstance(validation, dict)
                     and validation.get('ok') is True
                     and validation.get('warnings') == []),
        'doctor': (doctor['returncode'] == 0
                   and 'OK: runtime discovery' in doctor['stdout']
                   and 'ERROR:' not in doctor['stdout']
                   and 'WARN:' not in doctor['stdout']),
    }


def verify(root: Path = ROOT, host_root: Path = DEFAULT_HOST,
           python: str = sys.executable, hermes: str = 'hermes',
           dependencies: Path = HOST_DEPENDENCIES) -> dict:
    root, host_root = root.resolve(), host_root.resolve()
    if not os.environ.get('TMPDIR'):
        raise RuntimeError('TMPDIR must name the disposable scratch directory')
    with tempfile.TemporaryDirectory(prefix='v08-host-', dir=os.environ['TMPDIR']) as temp:
        base = Path(temp)
        env = isolated_env(base, host_root, dependencies)
        plugin = copy_plugin(root, Path(env['HERMES_HOME']) / 'plugins' / 'hermes-studiotwin')
        api = run_command([python, str(Path(__file__).resolve()), '--probe', str(plugin)], env, base)
        try:
            details = json.loads(api['stdout']) if api['stdout'].strip() else {}
        except json.JSONDecodeError:
            details = {}
        commands = {}
        for label, prefix in (('reference', [python, '-m', 'hermes_cli.main']),
                              ('installed', [hermes])):
            commands[label] = {
                'validate': run_command(prefix + ['plugins', 'validate', str(plugin), '--json'], env, base),
                'doctor': run_command(prefix + ['plugins', 'doctor', str(plugin), '--ci'], env, base),
            }
        checks = {label: cli_checks(group) for label, group in commands.items()}
        # The checkout is authoritative. The independently installed launcher can
        # lag its schema; retain every failure without making it an admission gate.
        limitations = []
        if not all(checks['installed'].values()):
            limitations.append({
                'source': 'installed', 'authoritative': False,
                'message': 'Installed Hermes CLI did not pass; see unmodified command output. '
                           'Its schema may reject cost_unit, costs, and timeout.',
            })
        return {'ok': (api['returncode'] == 0 and details.get('ok') is True
                       and all(checks['reference'].values())), 'api': details,
                'cli_checks': checks, 'limitations': limitations,
                'authoritative_source': 'reference',
                'doctor_invocation': 'plugins doctor TARGET --ci (no --json: unsupported by reference parser)',
                'api_process': api, 'commands': commands, 'host_root': str(host_root),
                'dependency_path': str(dependencies),
                'scratch_home': env['HERMES_HOME'], 'scratch_removed_on_return': True,
                'credential_mode': 'dummy-only; inherited credentials excluded'}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    parser.add_argument('--host-root', type=Path, default=DEFAULT_HOST)
    parser.add_argument('--python', default=sys.executable)
    parser.add_argument('--dependency-path', type=Path, default=HOST_DEPENDENCIES,
                        help='Explicit host dependency directory (may be disposable scratch storage)')
    parser.add_argument('--hermes', default=shutil.which('hermes') or 'hermes')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--probe', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    value = probe(args.probe) if args.probe else verify(
        args.root, args.host_root, args.python, args.hermes, args.dependency_path)
    text = json.dumps(value, indent=2) + '\n'
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(text, encoding='utf-8')
    print(text, end='')
    return 0 if value['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
