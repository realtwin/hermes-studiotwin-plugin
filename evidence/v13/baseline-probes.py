"""Read-only-baseline probes; restore exclusively owned source in finally."""
from pathlib import Path
import os
import subprocess
root = Path(__file__).resolve().parents[2]
os.chdir(root)
paths = ['src/viewers/env-lifecycle.ts', 'src/viewers/env-viewer.tsx', 'src/viewers/material-viewer.tsx', 'src/viewers/model-viewer.tsx']
saved = {p: Path(p).read_bytes() for p in paths}
base = '173334f6cf6ef565a3185b4f5067867335360d0f'
try:
    for p in paths:
        Path(p).write_bytes(subprocess.check_output(['git', 'show', base+':'+p]))
    with open('evidence/v13/env-webgl-base.log','w') as out:
        result = subprocess.run(['npx','vitest','run','tests/viewers/env-material.test.ts'],env={**os.environ,'STUDIOTWIN_WEBGL_TEST':'1'},stdout=out,stderr=subprocess.STDOUT)
    print('BASE env WebGL:', result.returncode)
finally:
    for p, data in saved.items(): Path(p).write_bytes(data)
