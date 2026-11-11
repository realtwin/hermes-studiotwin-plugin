# V09 inspector scroll remediation

Task: t_e585b4f8. Baseline: ec980629f0070c2bde0920aefbd0ad835fac6313.

## Scope

Move the inspector's `overflow: auto` after `...cardShell`. Ordinary card clipping remains unchanged in the shared token. No labels, roles, frozen files, backend, MCP transport or billing behavior changed. Rebuilt `desktop/plugin.js` is included.

## Regression evidence

`tests/visual/inspector-scroll.test.ts` imports the actual compiled production bundle through the existing SDK adapter. Two fresh browser cases open Library → crate.glb at 1000×700, light/dark. They require initially overflowing/clipped content, wheel the dialog without using focus/click/scrollIntoView first, require positive scrollTop and the complete Next section inside the dialog, hit-test the last action, then physically click it and verify one composer handoff and zero paid submissions.

- RED: `red.log`: both cases fail against the original committed bundle, scrollTop remains 0 after the wheel (poll timeout). This establishes sensitivity to the exact reported regression without mutating production CSS from the test.
- GREEN: `green.log`: both pass after the scoped source fix and production rebuild.
- `inspector-{light,dark}.json`: each after-wheel scrollTop=138, clientHeight=642, scrollHeight=780, Next bottom=631.0625 < dialog bottom=672, errors=[], paidSubmissions=[].
- `inspector-{light,dark}.png`: captured after wheel, before composer handoff; visually inspected both. Next text and both actions are fully visible, legible and unclipped. The top header is naturally above the scrolled viewport.

## Independently rerun gates

All commands run from the task worktree, without live/paid generation or deployment:

```sh
STUDIOTWIN_BLENDER_TEST=1 PYTHONPATH=/home/deploy/work/realtwin/hermes-studiotwin/reference/hermes-agent .venv/bin/pytest -q
STUDIOTWIN_WEBGL_TEST=1 STUDIOTWIN_CHROME=/opt/google/chrome/chrome npx vitest run
npm run typecheck
npm run build:desktop
.venv/bin/python tools/verify_v08_host_compat.py --output evidence/v09-inspector/host.json
```

- `pytest.log`: 194 passed, Blender enabled; pytest-asyncio deprecation warning retained.
- `vitest.log`: 180 passed across 14 files (178 existing + 2 new); existing Codicon adapter/deprecated loader warnings retained.
- `typecheck.log`: passed.
- `build.log`, `rebuild.log`, `bundle.sha256`: repeated build byte-identical, SHA256 ee86e2f15d23652cfe43107a6c275f6413dc15adeafce745df7eab80f3ab59bd.
- `host.json` / `host.log`: ok=true; reference validate and doctor pass, validation warnings=[], doctor findings=[]. Older independently installed launcher still rejects cost_unit/costs/timeout; raw failures retained, not substituted for the authoritative reference check.
- Frozen-file diff against cdd48c6 is empty for tests/scaffold, vite.config.ts, vitest.config.ts, src/sdk.d.ts, package.json and package-lock.json.

The full visual suite also ran as part of Vitest. Its incidental regenerated V08 screenshots were restored to keep this remediation limited to the requested inspector evidence.

## Limits and review

Browser proof uses the existing SDK test adapter, stubbed Codicon, and deterministic loopback provider fixtures, not native Hermes Desktop or live cloud generation. No installation, deployment, publication, merge or paid call was performed. Same-card Salt review is required; implementation evidence is not release approval.

To regenerate inspector captures:

```sh
STUDIOTWIN_INSPECTOR_EVIDENCE=evidence/v09-inspector STUDIOTWIN_WEBGL_TEST=1 STUDIOTWIN_CHROME=/opt/google/chrome/chrome npx vitest run tests/visual/inspector-scroll.test.ts
```
