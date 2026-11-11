"""Reproduce V01 host admission, offline suites and regression-sensitivity checks.

Run with the isolated test interpreter and reference Hermes checkout on PYTHONPATH:
    .venv/bin/python -B tools/verify_v01.py
Never calls the real StudioTwin service. Mutations operate on disposable copies.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVIDENCE = ROOT / 'evidence/v01'


def run(name, command, cwd=ROOT):
    result = subprocess.run(command, cwd=cwd, env={**os.environ,'PYTHONDONTWRITEBYTECODE':'1'},
                            capture_output=True,text=True,timeout=180)
    text = '$ ' + ' '.join(map(str,command))+'\n'+result.stdout+result.stderr+f'\nexit_code={result.returncode}\n'
    (EVIDENCE/(name+'.txt')).write_text(text)
    print(text)
    return result.returncode


def main():
    EVIDENCE.mkdir(parents=True,exist_ok=True)
    from hermes_cli.agent_plugins import load_agent_plugin
    from hermes_cli.plugin_validate import validate_plugin_dir
    from pm.plugin_declarations import read_python_declaration
    working = ROOT / '.verification'
    working.mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=working) as tmp:
        package=load_agent_plugin(ROOT,Path(tmp)/'data')
        report=validate_plugin_dir(ROOT)
        output={**report.to_dict(),'host_module':sys.modules['hermes_cli.agent_plugins'].__file__,
                'version':package.version,'pyproject_installs':read_python_declaration(ROOT).pyproject_installs,
                'server':package.mcp_servers['studiotwin']}
        (EVIDENCE/'host-validation.json').write_text(json.dumps(output,indent=2))
        print(json.dumps(output,indent=2))
        assert report.ok and not output['pyproject_installs']
    assert run('pytest',[sys.executable,'-B','-m','pytest','-q','--tb=short'])==0
    assert run('node-scaffold',['npm','run','test:scaffold'])==0
    mutations=[
        ('range-ignored','dashboard/proxy.py',
         'start, end, status = byte_range(range_header, size)',
         'start, end, status = byte_range(None, size)', 'file_ranges'),
        ('redirect-guard-removed','dashboard/studiotwin_client.py',
         "if response.status_code not in (307,308) or not allowed(target) or origin(target) != initial_origin:",
         'if False:', 'foreign_redirect_never_reaches_target'),
    ]
    for name,relative,old,new,selection in mutations:
        with tempfile.TemporaryDirectory(dir=working) as tmp:
            copy=Path(tmp)/'plugin'
            shutil.copytree(ROOT,copy,ignore=shutil.ignore_patterns('.git','.venv','node_modules','.verification','evidence','__pycache__'))
            target=copy/relative
            text=target.read_text()
            assert text.count(old)==1
            target.write_text(text.replace(old,new))
            # Redirect mutation must remove both checks, not leave the per-hop
            # preflight to correctly reject the next request.
            if name=='redirect-guard-removed':
                text=target.read_text()
                old_check='if not allowed(url):'
                assert text.count(old_check)==1
                target.write_text(text.replace(old_check,'if False:'))
            code=run('mutation-'+name,[sys.executable,'-B','-m','pytest','-q',
                'tests/python/test_plugin_api.py','-k',selection,'--tb=short'],copy)
            assert code==1, f'{name}: expected assertion failures, got exit {code}'
    print('V01: suites green; both production mutations detected.')


if __name__=='__main__':
    main()
