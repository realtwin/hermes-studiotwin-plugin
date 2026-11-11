"""Run the no-spend release gates sequentially on an explicitly pinned isolated host.

Bootstrap separately: clone the selected Hermes release, `uv sync --frozen
--no-default-groups --project HOST`, then install requirements-test.txt into that
DISPOSABLE host venv with `uv pip install --python HOST/.venv/bin/python -r ...`.
Run this script with that interpreter and Node >=24 on PATH. No live host launcher
is used. Reports, temporary homes and screenshots go outside the source checkout.
This proves source-host admission and offline journeys, not native Desktop or cloud.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
FFMPEG_SHA256 = '771831e48242e0dfb9640a73dabbf29c6d2188bcf217f65909c9e2567696e180'


def check_ffmpeg(binary: Path) -> str:
    with binary.open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if digest != FFMPEG_SHA256:
        raise ValueError(f'FFmpeg SHA-256 mismatch: expected {FFMPEG_SHA256}, got {digest}')
    return digest


def check_host(host: Path, sha: str) -> str:
    if not re.fullmatch(r'[a-f0-9]{40}', sha):
        raise ValueError('host revision must be a full lowercase 40-character SHA')
    actual = subprocess.check_output(['git', '-C', str(host), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != sha:
        raise ValueError(f'host SHA mismatch: expected {sha}, got {actual}')
    if subprocess.check_output(['git', '-C', str(host), 'status', '--porcelain', '--untracked-files=no'], text=True).strip():
        raise ValueError('host checkout has tracked modifications')
    return actual


def check_clean_source(root: Path) -> None:
    status = subprocess.check_output(['git', 'status', '--porcelain'], cwd=root, text=True).strip()
    if status:
        raise ValueError(f'source checkout is dirty: {status}')


def run_step(name: str, command: list[str], cwd: Path, env: dict, output: Path) -> dict:
    log = output / f'{name}.log'
    start = time.monotonic()
    with log.open('w') as stream:
        try:
            result = subprocess.run(command, cwd=cwd, env=env, stdout=stream,
                                    stderr=subprocess.STDOUT, timeout=1800, check=False)
            code = result.returncode
        except (OSError, subprocess.TimeoutExpired) as exc:
            stream.write(f'\n{type(exc).__name__}: {exc}\n')
            code = -1
    return {'name': name, 'argv': command, 'returncode': code,
            'status': 'PASS' if code == 0 else 'FAIL', 'log': str(log),
            'seconds': round(time.monotonic() - start, 3)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--host-root', type=Path, required=True)
    parser.add_argument('--host-sha', required=True)
    parser.add_argument('--ffmpeg-bin', type=Path, required=True,
                        help='Directory holding fixture-parity FFmpeg and ffprobe')
    parser.add_argument('--output', type=Path, required=True,
                        help='New evidence directory OUTSIDE this checkout')
    args = parser.parse_args()
    host, output = args.host_root.resolve(), args.output.resolve()
    if output.is_relative_to(ROOT):
        parser.error('evidence must be outside source checkout')
    output.mkdir(parents=True, exist_ok=False)
    report = {'ok': False, 'steps': [], 'limitations': [
        'No paid/live service call or native Desktop acceptance.',
        'Portable plugin.json has no requires_hermes field; tested host is not an inferred historical minimum.',
    ]}
    try:
        report['host_sha'] = check_host(host, args.host_sha)
        report['ffmpeg_sha256'] = check_ffmpeg(args.ffmpeg_bin / 'ffmpeg')
        report['source_sha'] = subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip()
        report['source_dirty'] = subprocess.check_output(['git', 'status', '--porcelain'], cwd=ROOT, text=True).strip()
        check_clean_source(ROOT)
        report['python'] = sys.version
        node = subprocess.check_output(['node', '--version'], text=True).strip()
        if int(node.lstrip('v').split('.')[0]) < 24:
            raise ValueError(f'Node >=24 required, got {node}')
        report['node'] = node
        # Credentials and live profile selectors never enter child processes.
        env = {k: os.environ[k] for k in ('PATH', 'LANG', 'LC_ALL', 'SYSTEMROOT',
               'PLAYWRIGHT_BROWSERS_PATH') if k in os.environ}
        scratch = output / 'scratch'
        scratch.mkdir()
        # Chrome creates a Unix singleton socket under TMPDIR. A long evidence
        # path overflows sockaddr_un; keep temporary files in the caller's short,
        # managed scratch root instead. tempfile callers create unique children.
        temp_root = os.environ.get('TMPDIR')
        if not temp_root or not Path(temp_root).is_dir():
            raise ValueError('TMPDIR must name an existing short managed scratch directory')
        report['temporary_root'] = temp_root
        env.update(HOME=str(scratch / 'home'), HERMES_HOME=str(scratch / 'hermes'),
                   TMPDIR=temp_root, XDG_CACHE_HOME=str(scratch / 'cache'),
                   XDG_CONFIG_HOME=str(scratch / 'config'), XDG_DATA_HOME=str(scratch / 'data'),
                   HERMES_BUNDLED_PLUGINS=str(scratch / 'bundled'), HERMES_ENABLE_PROJECT_PLUGINS='0',
                   PYTHONPATH=str(host), HERMES_REFERENCE_ROOT=str(host),
                   HERMES_HOST_DEPENDENCIES=str(Path(sys.executable).parent.parent / 'lib' / f'python{sys.version_info.major}.{sys.version_info.minor}' / 'site-packages'),
                   PATH=os.pathsep.join((str(args.ffmpeg_bin.resolve()), str(Path(sys.executable).parent), env.get('PATH', ''))),
                   WORKSPACE_TEST_PYTHON=sys.executable,
                   V08_EVIDENCE_DIR=str(output / 'visual'),
                   V06_SCREENSHOT_DIR=str(output / 'workspace'),
                   STUDIOTWIN_INSPECTOR_EVIDENCE=str(output / 'inspector'),
                   STUDIOTWIN_MULTIVIEW_EVIDENCE=str(output / 'multiview'),
                   PYTHONDONTWRITEBYTECODE='1', NO_COLOR='1', TERM='dumb')
        # Playwright's default cache normally lives under HOME; retain only its
        # public browser binary location, never profile credentials or config.
        if 'PLAYWRIGHT_BROWSERS_PATH' not in env:
            env['PLAYWRIGHT_BROWSERS_PATH'] = str(Path.home() / '.cache/ms-playwright')
        Path(env['HOME']).mkdir()
        report['ffmpeg_version'] = subprocess.check_output([str(args.ffmpeg_bin / 'ffmpeg'), '-version'], text=True).splitlines()[0]
        report['blender_version'] = subprocess.check_output(['blender', '--version'], text=True).splitlines()[0]
        vitest = str(ROOT / 'node_modules/.bin/vitest')
        commands = [
            ('typecheck', ['npm', 'run', 'typecheck'], {}),
            ('build', ['npm', 'run', 'build:desktop'], {}),
            ('default-vitest', [vitest, 'run', '--reporter=default', '--reporter=json', f'--outputFile.json={output / "default-vitest.json"}'], {}),
            ('extended-vitest', [vitest, 'run', '--reporter=default', '--reporter=json', f'--outputFile.json={output / "extended-vitest.json"}'], {'STUDIOTWIN_WEBGL_TEST': '1', 'STUDIOTWIN_EXPOSURE_EVIDENCE': str(output / 'exposure')}),
            ('python-blender', [sys.executable, '-m', 'pytest', '-q', f'--junitxml={output / "python.xml"}'], {'STUDIOTWIN_BLENDER_TEST': '1'}),
            ('host', [sys.executable, str(ROOT / 'tools/verify_v08_host_compat.py'), '--host-root', str(host), '--python', sys.executable, '--dependency-path', env['HERMES_HOST_DEPENDENCIES'], '--hermes', str(Path(sys.executable).parent / 'hermes'), '--output', str(output / 'host.json')], {}),
        ]
        bundle = ROOT / 'desktop/plugin.js'
        for name, command, extra in commands:
            report['steps'].append(run_step(name, command, ROOT, {**env, **extra}, output))
            (output / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
        first = hashlib.sha256(bundle.read_bytes()).hexdigest()
        step = run_step('deterministic-build', ['npm', 'run', 'build:desktop'], ROOT, env, output)
        second = hashlib.sha256(bundle.read_bytes()).hexdigest()
        step['bundle_sha256'] = second
        if first != second:
            step.update(status='FAIL', reason='bundle changed between builds')
        report['steps'].append(step)
        check_clean_source(ROOT)
        report['source_clean_after'] = True
        report['ok'] = all(row['status'] == 'PASS' for row in report['steps'])
    except Exception as exc:
        report['preflight_error'] = f'{type(exc).__name__}: {exc}'
    (output / 'summary.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report, indent=2))
    return 0 if report['ok'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
