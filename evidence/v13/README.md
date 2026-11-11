# V13 — explicit UI lifecycles, v0.3.2

Implementation handoff for `feat/v13-explicit-state-machines-ux-dx-ax`.
Base: `173334f6cf6ef565a3185b4f5067867335360d0f`.

## Delivered

- One dependency-free `src/lib/state-machines.ts` with `phase`-discriminated lifecycle contracts, pure stage/multiview transition functions, derived task state, canonical job normalization, inspector resolution and stage projections.
- Model, environment and material viewers use one pooled-stage hook. Lease release preserves failed/audit outcomes and captured eviction posters; retired async work cannot update the replacement stage. Existing hook fields/props retained; `phase` added.
- Multiview explicitly distinguishes rendering, local staging, staged success, capture failure and partial staging failure. Partial failure retains sheet preview/download, while Reskin requires the staged path. Single synchronous state ref also prevents duplicate requests before React rerenders.
- Task and Jobs consumers share canonical job status normalization; unknown provider status defaults to queued instead of throwing. Cancellation warnings are nonterminal. Existing `jobStatus` export and task markers retained.
- Inspector exposes effective target/modality, job-output resolution and a visible cloud-detail resolution warning without discarding the selected fallback.
- Upload state carries filename/destination. Audio decode/conversion and video/sequence load states are explicit; loading video has a status indicator rather than an empty video element.
- Python job completion/active constants are shared by progress, active-task membership and action availability. `executing`, `processing`, `draft` remain active; `success` is completed.
- Version is `0.3.2` in plugin, Python project and dashboard manifests. `package.json`/`package-lock.json` unchanged; Python metadata remains `[project]`-only. No transport, billing, redaction or credit-cap changes.

## Verification (actual execution)

| Gate | Result | Evidence |
|---|---|---|
| New pure + DOM tests | **88 passed** | `new-tests-green.log` |
| Default full Vitest | **329 passed, 38 opt-in skipped** | `vitest.log` |
| Full Vitest with WebGL enabled | **366 passed, 1 inherited failure** | `vitest-webgl-final.log` |
| Full pytest with real Blender enabled | **251 passed, 1 inherited failure; no skips** | `pytest.log` |
| TypeScript | **passed** | `typecheck.log` |
| Host plugin validation | **Validation passed** | `validate.log` |
| Desktop bundle | **two builds byte-identical** | `build.log`, `build-sha256-{first,second}.txt` |

Bundle SHA-256: `80068b61425acfba05a89f5fcfd564ac563c60d2b3ba9ef5c4f24a5a203697f6`.

The existing Workspace theme invariant passed in both full Vitest runs. Browser tests use the real Chromium/SwiftShader paths; new stage DOM tests replace GPU construction only and exercise the real hook/pool/viewer/REST staging code. Test-generated old screenshot paths were restored instead of adding unrelated golden churn. No live paid generation, plugin installation, merge, publication or deployment was performed.

### Known baseline failures — not hidden or weakened

1. `tests/fixtures/test_fixture_foundation.py::test_media_generator_reproduces_every_file_byte_for_byte`: regenerated MP3/MP4 and their manifest hashes differ on this runtime (ffmpeg `6.1.1-3ubuntu5`). Fixture generator, fixtures and test are byte-identical to base; isolated `fixture-baseline.log` reproduces the same failure. The exact codec/toolchain cause is **not yet established**. No golden files regenerated.
2. Opt-in `tests/viewers/env-material.test.ts:265`: changing exposure via range-input `.fill('2')` produces the same canvas bytes. `env-webgl-base.log` reproduces the **same assertion** with all four original stage/model sources restored to the pinned base, and restores current source in `finally`. Do not confuse the earlier mixed-source baseline attempt (toolbar timeout, overwritten by the valid run) with the final base evidence. No render assertion weakened.

Follow-up investigation: `t_f71e29e2` (Sulfur, isolated scratch; must not edit Salt's shared review worktree). These limitations mean the extended suites are **not fully green**, even though no new failure was observed. Salt review remains required (`t_5dc2a7e4`).

## RED / GREEN / sensitivity

- Before implementation: pure contracts **3 assertion failures** (`machines-red.log`), task consumers **16 failures** (`task-red.log`), inspector **7 failures** (`inspector-red.log`), audio/video/upload **9 failures** (`media-upload-red.log`), Python vocabulary **5 failures** (`job-python-red.log`).
- Restored current implementation: all **88** new tests green (`new-tests-green.log`). Later matrix additions cover passive/terminal transition legality and the full normalization vocabulary.
- Six stage negative controls each fail assertions, with restored GREEN runs: model/env/material phase projection, late-load fence, snapshot retention, multiview phase. See `stage-mutation-*.log` and `stage-restored-*.log`.
- Four additional contract negative controls fail assertions: task phase consumer, inspector phase consumer, stage error retention, multiview partial-capture retention (`mutation-*.log`). `contract-mutations.py` restores every modified file in `finally`.
- Media/upload original-source negative control: **9 failures** (`media-upload-mutation.log`). Python classification mutation: **4 failures** (`job-python-mutation.log`).

Intermediate `*-initial`, `*-attempt`, `*-blocked` and dependency logs intentionally retain failed setup/integration attempts; they are not the final gate result.

## Reproduce

From the V13 worktree:

```sh
npm run typecheck
npx vitest run
STUDIOTWIN_WEBGL_TEST=1 npx vitest run
npm run build:desktop
hermes plugins validate .
```

The historical v09 `.venv` no longer exists here. Python verification used isolated `uv run --no-project` dependencies, not the active Hermes interpreter (which has no pytest):

```sh
PYTHONPATH=/home/deploy/work/realtwin/hermes-studiotwin/reference/hermes-agent \
STUDIOTWIN_BLENDER_TEST=1 \
/home/deploy/.hermes/tools/uv-0.13.5-linux-x64/uv run --no-project \
  --with pytest --with fastapi --with httpx --with python-multipart \
  --with pyyaml --with platformdirs --with rich --with python-dotenv \
  --with pydantic --with mcp --with tomli-w --with packaging \
  --with pillow --with ruamel-yaml python -m pytest -q
```

Blender observed: `4.2.3 LTS`. Mutation/baseline scripts require exclusive access to their documented source paths; do not run them concurrently with reviewers. They restore only their named files, never stash/reset the whole repository.
