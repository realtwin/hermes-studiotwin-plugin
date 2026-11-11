"""Release runner preflight must reject mismatched tools before running suites."""
import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]


def runner():
    spec = importlib.util.spec_from_file_location('verify_release', ROOT / 'tools/verify_release.py')
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_release_preflight_rejects_wrong_ffmpeg(tmp_path):
    with pytest.raises(ValueError, match='FFmpeg SHA-256'):
        runner().check_ffmpeg(Path(sys.executable))


def test_release_preflight_requires_exact_host_revision(tmp_path):
    with pytest.raises(ValueError, match='40-character'):
        runner().check_host(tmp_path, 'main')


def test_release_preflight_rejects_wrong_host_checkout():
    with pytest.raises(ValueError, match='host SHA'):
        runner().check_host(ROOT, '0' * 40)


def test_release_rejects_source_drift(monkeypatch):
    mod = runner()
    monkeypatch.setattr(mod.subprocess, 'check_output', lambda *args, **kwargs: ' M desktop/plugin.js\n')
    with pytest.raises(ValueError, match='source checkout is dirty'):
        mod.check_clean_source(ROOT)


def test_release_subprocess_failure_is_preserved(tmp_path):
    mod = runner()
    script = tmp_path / 'fail.py'
    script.write_text('print("expected negative control")\nraise SystemExit(7)\n')
    result = mod.run_step('negative', [sys.executable, str(script)], tmp_path, {}, tmp_path)
    assert result['status'] == 'FAIL' and result['returncode'] == 7
    assert 'expected negative control' in Path(result['log']).read_text()
