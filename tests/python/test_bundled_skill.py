"""Exercise the bundled wake adapter through real loopback HTTP, never cloud.
Only the documented endpoint and host secret boundary are test seams.
"""
from pathlib import Path
import re
import sys
import time

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tests/fixtures'))
from fake_mcp.http import serve
from fake_mcp.state import FakeStudioTwin, Job


@pytest.mark.parametrize(('status', 'exit_code'), [('done', 0), ('failed', 1), ('cancelled', 1)])
def test_documented_chat_wake_adapter_polls_original_job(monkeypatch, capsys, status, exit_code):
    import agent.secret_scope
    fake = FakeStudioTwin()
    jid = '000010b5-0001-4000-8000-000000000001'
    fake.jobs[jid] = Job(uuid=jid, function_name='image-to-3d-mesh', inputs={},
                        estimate=25, cost=25, provider='fixture', created_ms=fake.clock_ms,
                        schedule=(status,), status=status, outputs={'mesh': 's3://fixture/result.glb'})
    text = (ROOT / 'skills/studiotwin/SKILL.md').read_text()
    snippets = re.findall(r'```python\n(.*?)```', text, re.S)
    assert len(snippets) == 1
    with serve(fake) as remote:
        monkeypatch.setattr(agent.secret_scope, 'get_secret', lambda name: remote.api_key)
        monkeypatch.setattr(sys, 'argv', ['-', str(ROOT), jid])
        monkeypatch.setattr(time, 'sleep', lambda seconds: pytest.fail('terminal job must not wait'))
        snippet = snippets[0].replace('https://api.studiotwin.ai', remote.base)
        with pytest.raises(SystemExit) as stopped:
            exec(compile(snippet, '<bundled wake adapter>', 'exec'), {'__name__': '__main__'})
        assert stopped.value.code == exit_code
    output = capsys.readouterr().out
    assert jid in output
    assert fake.balance == 500
    assert fake.vp_submissions == []
    assert not [row for row in fake.ledger if row.get('event') == 'debit']
    calls = [row for row in fake.calls if row.get('name') == 'studiotwin_get_job_status']
    assert len(calls) == 1
