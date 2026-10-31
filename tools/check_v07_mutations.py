"""Prove V07 regressions are detected, always restoring the exact source/bundle.
Run with no other builds/tests concurrently. Uses only loopback Chromium fixtures.
"""
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / '.verification'
OUT.mkdir(exist_ok=True)
BUNDLE = ROOT / 'desktop/plugin.js'
ENTRY = ROOT / 'src/plugin.tsx'
original_bundle, original_entry = BUNDLE.read_bytes(), ENTRY.read_bytes()


def check(name, selection, must_contain):
    command = ['npx', 'vitest', 'run', 'tests/bundle/plugin-bundle.test.ts', '-t', selection]
    result = subprocess.run(command, cwd=ROOT, capture_output=True, text=True, timeout=120)
    log = result.stdout + result.stderr + f'\nexit_code={result.returncode}\n'
    (OUT / (name + '.txt')).write_text(log)
    assert result.returncode == 1 and must_contain in log, log
    print(f'{name}: detected (exit 1)')


try:
    # This compiles and parses but fails to ESM-link on the older SDK. Loading
    # the unchanged artifact in Chromium, not rebundling with a stub, catches it.
    BUNDLE.write_bytes(original_bundle + b'\nimport {registerPlugin as unsafeRegistration} from "@hermes/plugin-sdk";\n')
    check('mutation-named-sdk-export', 'missing area/registration exports', 'does not provide an export named')
    BUNDLE.write_bytes(original_bundle)
    # An accidentally omitted assembly call must fail contribution inventory.
    source = original_entry.decode()
    assert source.count('    registerTaskCards(ctx)') == 1
    ENTRY.write_text(source.replace('    registerTaskCards(ctx)', '    // mutation: omitted task cards'))
    subprocess.run(['npm', 'run', 'build:desktop'], cwd=ROOT, check=True, capture_output=True, text=True)
    check('mutation-missing-task-registration', 'full SDK', 'to deeply equal')
finally:
    ENTRY.write_bytes(original_entry)
    BUNDLE.write_bytes(original_bundle)
print('Restored exact original source and artifact.')
