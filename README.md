# hermes-studiotwin

StudioTwin creative suite for Hermes, built as one Agent Plugins v1 package. The design lives at
`/home/deploy/work/realtwin/studiotwin-platform/handoffs/hermes-studiotwin-plugin/DESIGN.md`. Build slices are listed in
`slice-scopes.json`.

This is the S01 scaffold. It holds manifests, locks, runner configuration, licenses, the
vendoring inventory and the slice-ownership checker. There is no gateway, backend or Desktop
code yet, so the plugin cannot run.

## Toolchain

- Python 3.11 or newer, managed by uv 0.12.3 or newer (`uv sync --frozen`).
- Node 24 or newer with npm (`npm ci`). Node 24 LTS is the recommended runtime for Desktop. The scaffold was verified on Node 26.7.0.

## Checks

```sh
npm ci && uv sync --frozen
env PYTHONPATH=/home/deploy/work/realtwin/hermes-studiotwin/reference/hermes-agent \
  uv run pytest tests/scaffold/test_manifest_config.py tests/scaffold/test_slice_scope_coverage.py -q
npm exec -- vitest run tests/scaffold/scaffold.test.ts --pool=forks --poolOptions.forks.singleFork=true
python3 tools/check-slice-scopes.py
```

Each slice runs only its own command from `slice-scopes.json`, one suite at a time.
