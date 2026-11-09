"""Run isolated negative controls for pure contracts and consuming DOM boundaries."""
from pathlib import Path
import subprocess
root = Path(__file__).resolve().parents[2]
mutants = [
 ('task-consumer', 'src/cards/task-card.tsx', 'data-task-phase={state.phase}', 'data-task-phase="loading"', 'tests/workspace/task-states.test.ts'),
 ('inspector-consumer', 'src/pages/asset-inspector.tsx', 'data-inspector-state={inspectorState.phase}', 'data-inspector-state="ready"', 'tests/workspace/inspector-states.test.ts'),
 ('stage-error-retained', 'src/lib/state-machines.ts', "state.phase === 'error' || state.phase === 'audit' || state.phase === 'poster'", "state.phase === 'audit' || state.phase === 'poster'", 'tests/workspace/state-machines.test.ts'),
 ('partial-capture-retained', 'src/lib/state-machines.ts', "{ phase: 'partial_error', capture: state.capture, message: event.message }", "{ phase: 'error', message: event.message }", 'tests/workspace/state-machines.test.ts'),
]
for name, path, old, new, test in mutants:
 p = root / path
 saved = p.read_bytes()
 try:
  text = saved.decode()
  assert old in text, name
  p.write_text(text.replace(old, new))
  run = subprocess.run(['npx','vitest','run',test],cwd=root,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
  (root / f'evidence/v13/mutation-{name}.log').write_text(run.stdout)
  assert run.returncode != 0 and 'AssertionError' in run.stdout and 'Unhandled Errors' not in run.stdout, name
  print(name, 'assertion RED')
 finally:
  p.write_bytes(saved)
run = subprocess.run(['npx','vitest','run','tests/workspace/state-machines.test.ts','tests/workspace/task-states.test.ts','tests/workspace/inspector-states.test.ts','tests/workspace/media-upload-states.test.ts','tests/workspace/stage-states.test.ts'],cwd=root,text=True,stdout=subprocess.PIPE,stderr=subprocess.STDOUT)
(root / 'evidence/v13/new-tests-green.log').write_text(run.stdout)
assert run.returncode == 0
print('All restored: GREEN')
