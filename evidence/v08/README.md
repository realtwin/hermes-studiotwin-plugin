# V08 — Visual QA and host compatibility evidence

Current screenshots, contact sheets and visual manifests were refreshed by V09. See `../v09/README.md` for the design-system changes, current test counts and review scope. The remainder of this report records the original V08 verification.

V08 implementation and integration gates pass. Salt-approved V08c commit `fc014aa9d0d0eb113401e6f797a2bf4af17107d1` was merged into `feat/v08-visual-qa-host-compat`. The previous missing rig-audit acceptance failure is resolved through production code, not test-injected UI. Final independent review belongs to existing child `t_7b4f6945`; this report is not release approval.

## What was exercised

`tests/visual/visual-qa.test.ts` mounts production `desktop/plugin.js` byte-for-byte through an import map in real headless Google Chromium (`/opt/google/chrome/chrome`). Host-owned React, React Query, SDK atoms, registration and primitive controls are a test host adapter, not a running Hermes Desktop application. Sidebar and palette shells display actual registered contributions; these are not screenshots of native Desktop chrome.

API and media requests go through the real `dashboard/plugin_api.py` router to a loopback HTTP `FakeStudioTwin`. Deterministic fixtures are uploaded through the real local `/upload` route, including `model/rig-audit.json`; its returned path is passed as the production directive's `audit=` attribute. Provider-shaped audit data is a deterministic fixture, not a live provider audit. Job state is seeded on the fake server without generation or wallet operations. No real credentials, live-profile installs or paid generations are used. Browser cloud requests are blocked.

The 1440×1100 CSS viewport uses device scale 2. Screenshots are 2880 pixels wide and 2200–2740 pixels high. Full-page workspace captures include content below the viewport. Each capture asserts no horizontal overflow, nonempty canvas dimensions and distinct foreground/background colors. Every light/dark pair has different computed foreground and background colors. Exact measurements and filenames are in `visual-manifest.json`.

## Visual and interaction results

- Mesh: static GLB decode, 12-triangle badge, shading selection, orbit drag, auto-rotate toggle and format menu.
- Rigged animation: GLB decode, Wave and Idle options, clip selection and timeline scrub; visible `Rig audit: passed · 2 joints` from the uploaded audit, separately asserted `Rig inspection (local): 2 joints · 1 skinned meshes · 2 clips`. Both themes pass. Local mesh inspection never manufactures the audit verdict.
- Audio: real WAV decode, nonempty waveform canvas pixels, loop state, play/pause and WAV/MP3/OGG/FLAC conversion menu visibility. This visual suite does not execute each conversion; existing audio tests cover those paths.
- Environment: Radiance HDR decode, EV slider, spherical sticker overlay selection and selected-sticker output.
- Material: four real map files, sphere/cube/rounded-plane selection, channel selection and disabled unavailable displacement.
- Image/Concept: decoded fixture images, before/after slider and real backend `Made from` provenance. Source images are deterministic 64×64 fixtures; high-resolution screenshot capture is not proof of a high-resolution provider generation or visibly different edit.
- Video: real MP4 decode, exact-frame stepping forward/back to zero, timeline scrub and PNG frame-capture download.
- Progress: same seeded job polled queued → running → completed, morphing into the image viewer and exposing backend Next actions.
- Workspace: Library, Jobs, Concepts and Upload in both themes; live credits chip, actual registered sidebar and six palette commands. Palette Jobs action selects Jobs; sidebar navigates to `/studiotwin`. Active-job chip registration/interactions are also covered by the existing workspace suite.
- Mixed WebGL pool: six model/environment/material cards loaded sequentially while all remain mounted. Exactly four live canvases and two real model/panorama snapshots remain in each theme.
- Final browser evidence: zero page errors, zero console errors, zero horizontal overflow, zero blocked cloud requests, zero paid submissions and zero wallet debits; no acceptance findings.

All 30 refreshed captures were inspected using eight contact sheets. Fixture content and expected controls render, light/dark chrome differs, and the provider audit and separate local inspection are visible. Tiny synthetic image/video fixtures are intentionally pixelated when enlarged. Long synthetic filenames wrap within library tiles. No real keys, credential values, user data or live hostnames were observed. Contact sheets are navigation aids; originals are authoritative.

## Screenshot manifest

Every basename has `-light.png` and `-dark.png` under `screenshots/`:

| Basename | Surface |
| --- | --- |
| `3d-model` | Static mesh |
| `animation-rigged` | Animation, provider audit and local inspection |
| `audio-sfx` | WAV waveform and conversion menu |
| `env-360-stickers` | HDR panorama and sticker overlay |
| `pbr-material` | Combined PBR preview |
| `image-concept-compare` | Image comparison and provenance |
| `video-player` | Video and exact-frame controls |
| `task-progress-card` | Completed morph and Next actions |
| `workspace-library` | Library, chips, sidebar, palette |
| `workspace-jobs` | Jobs and chrome |
| `workspace-concepts` | Concept history/detail and chrome |
| `workspace-upload` | Upload and chrome |
| `task-progress-queued` | Supplementary queued state |
| `task-progress-running` | Supplementary running state |
| `webgl-pool-six` | Supplementary context-budget proof |

Total: 24 requested captures plus 6 supplementary captures = 30 unique PNGs, programmatically checked against the manifest and disk. `visual-manifest.json` and `visual-partial.json` retain layout, styles, findings and browser errors.

## Host admission

`tools/verify_v08_host_compat.py` copies the payload into disposable `HERMES_HOME` under `TMPDIR`, excludes inherited credentials/profile selectors, uses a dummy key and deletes the home afterwards. It checks reference APIs, PM declaration, runtime skill/MCP registration and router import, then independently invokes reference and installed CLIs.

Per Tris's explicit ruling, the authoritative host is `/home/deploy/work/realtwin/hermes-studiotwin/reference/hermes-agent`. Reference validation reports `ok=true`, `warnings=[]`; all six checks pass; isolation tier `portable`, `host_ready=true`; `pyproject_installs=false`; skill `studiotwin` and MCP `studiotwin` register; dashboard APIRouter imports; doctor API and CLI pass. Both reference CLI commands exit 0. The pinned doctor parser does not support `--json`; actual invocation is `plugins doctor TARGET --ci`, covered by a parser-rejection regression test.

The older installed `/home/deploy/.local/bin/hermes` is independently exercised and rejects `cost_unit`, `costs` and `timeout`. Its failures remain verbatim in `host-compat.json`; installed-host compatibility is NOT claimed. Production pricing/timeout declarations were not stripped.

The suggested `/opt/openclaw/claude-code/.hermes/hermes-agent/.hermes/py` directory is absent. Dependencies were installed under `$TMPDIR/v08-host-dependencies` for the managed-Python probe. Normal gates use workspace `.venv`; no live runtime environment was modified.

```sh
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=/home/deploy/work/realtwin/hermes-studiotwin/reference/hermes-agent:$TMPDIR/v08-host-dependencies \
/home/deploy/.hermes/tools/python-*/bin/python3 tools/verify_v08_host_compat.py \
  --dependency-path "$TMPDIR/v08-host-dependencies" \
  --hermes /home/deploy/.local/bin/hermes \
  --output evidence/v08/host-compat.json
```

`host-compat-tests.log` retains the earlier 14-test focused run: malformed manifests, buildable declarations, credential exclusion, real CLI invocation and authority-gating tests. All are included again in the full Python gates.

## Full gates and exact-HEAD reproduction

```sh
STUDIOTWIN_BLENDER_TEST=1 PYTHONPATH=/home/deploy/work/realtwin/hermes-studiotwin/reference/hermes-agent .venv/bin/pytest -q
STUDIOTWIN_WEBGL_TEST=1 STUDIOTWIN_CHROME=/opt/google/chrome/chrome npx vitest run
npm run typecheck
npm run build:desktop
git diff --exit-code -- desktop/plugin.js
```

Integration run: 194 Python tests passed with Blender enabled; 176 Vitest tests passed across 12 files with real Chromium enabled; typecheck passed; desktop build passed with zero bundle diff. Frozen scaffold/config/SDK/package files are unchanged. `pytest.log`, `vitest.log`, `typecheck.log`, `build.log` and `bundle-diff.log` hold actual output. Known non-failing diagnostics: unset asyncio fixture-loop-scope deprecation and node-side RGBELoader deprecation (not browser console errors).

Final committed HEAD is rerun with `V08_EVIDENCE_DIR=.verification/exact-head-final-visual` to preserve tracked evidence. Actual exact-HEAD outputs are `.verification/exact-head-final-{pytest,vitest,typecheck,build,host}.log` and `.verification/exact-head-final-host.json`; the lifecycle handoff records the exact SHA and results. No source or tracked evidence changes are made after that run.

## Regression evidence

The prior QA checkpoint `f9c0570644b580b7c72bcba96e6a93efe6a69339` failed its production audit requirement (147 Vitest pass / 1 missing-badge failure). The integration adds only real audit input and stricter badge/local-inspection assertions to V08 visual source. Production remediation is the independently approved V08c merge. V08c's 28 focused tests cover malformed/missing/unfetchable/separate audit data and real result envelopes; its review handoff records RED and envelope-unwrapping mutation evidence. No production source was edited directly in this V08 lane.
