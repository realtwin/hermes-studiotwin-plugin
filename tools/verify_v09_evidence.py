"""Summarize gates and verify the frozen V09 contract."""
import json
import re
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
subprocess.run(['git', 'diff', '--exit-code', 'cdd48c6', '--', 'tests/scaffold', 'vite.config.ts', 'vitest.config.ts', 'src/sdk.d.ts', 'package.json', 'package-lock.json'], cwd=root, check=True)
host = json.loads((root / 'evidence/v09/host-compat.json').read_text())
assert host['ok'] and host['api']['validation']['warnings'] == []
pytest = (root / 'evidence/v09/pytest.log').read_text()
vitest = (root / 'evidence/v09/vitest.log').read_text()
assert re.search(r'194 passed', pytest)
assert re.search(r'Tests\s+178 passed', vitest)
captures = json.loads((root / 'evidence/v09/capture-check.json').read_text())
assert captures['captures'] == 30 and not captures['errors'] and not captures['consoleErrors'] and not captures['overflow']
print(json.dumps({'python_tests':194, 'vitest_tests':178, 'frozen_files_unchanged':True, 'host_ok':host['ok'], 'host_warnings':host['api']['validation']['warnings'], 'host_cli_checks':host['cli_checks'], 'host_limitations':host['limitations'], 'visual':captures}, indent=2))
