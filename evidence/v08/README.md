# V08 — QA evidence; blocked on production rig-audit wiring

V08 is NOT complete. The real-Chromium suite intentionally fails because the production animation card has no required rig-audit badge. The assertion is retained, not skipped or replaced with harness-generated UI. Resolution is routed to Tris in task `t_1b7536c9`; final Salt review `t_7b4f6945` must remain gated until this acceptance failure is resolved.

## What was exercised

`tests/visual/visual-qa.test.ts` mounts the production `desktop/plugin.js` byte-for-byte through an import map in real headless Google Chromium (`/opt/google/chrome/chrome`). Host-owned React, React Query, SDK atoms, registration and primitive controls are a test host adapter, not a running Hermes Desktop application. The sidebar and palette shells display the actual registered contributions; they are not screenshots of native Desktop chrome.

All API and media requests go through the real `dashboard/plugin_api.py` router to a loopback HTTP `FakeStudioTwin`. Existing deterministic fixtures are uploaded through the real local `/upload` route. Job state is seeded on the fake server without generation or wallet operations. No fabricated HTTP API responses, real credentials, live-profile installs, or paid generations are used. The browser rejects cloud origins.

The 1440×1100 CSS viewport uses device scale 2. Screenshots are 2880 pixels wide, at least 2200 pixels high; full-page workspace captures include content below the viewport. Each capture asserts no horizontal overflow, nonempty canvas dimensions, and distinct background/foreground colors. Corresponding light/dark captures have different computed foreground and background colors. Exact measurements and filenames are in `visual-manifest.json`.

## Visual / interaction results

- Mesh: static GLB decode, 12-triangle badge, shading selection, orbit drag, auto-rotate toggle and format menu.
- Rigged animation: GLB decode, Wave and Idle options, clip selection and timeline scrub. Bone/clip stats render. REQUIRED RIG-AUDIT BADGE IS MISSING in both themes.
- Audio: real WAV decode, nonempty waveform canvas pixels, loop state, play/pause, and WAV/MP3/OGG/FLAC conversion menu visibility. This suite does not execute each conversion; existing audio tests cover download/conversion paths.
- Environment: real Radiance HDR decode, EV slider, spherical sticker overlay selection and selected-sticker output.
- Material: four actual map files, sphere/cube/rounded-plane selection, channel selection, unavailable displacement disabled.
- Image/Concept: decoded fixture images, before/after slider and real backend `Made from` provenance. The deterministic source images are 64×64; this is viewer/interaction evidence, not proof of a high-resolution provider generation or a visibly different edit.
- Video: real MP4 decode, enabled exact-frame stepping forward/back to time zero, timeline scrub and PNG frame-capture download.
- Progress: same seeded job observed through real polling queued → running → completed, morphs into the image viewer and exposes backend Next actions.
- Workspace: Library, Jobs, Concepts and Upload in both themes, live credit chip, actual registered sidebar contribution and six palette commands. Palette Jobs action selects the Jobs tab; sidebar navigates to `/studiotwin`.
- Mixed WebGL pool: six model/environment/material cards loaded sequentially while all remain mounted. Exactly four live canvases and two real model/panorama snapshot images remain, in each theme. Pool captures and computed canvas dimensions are retained.
- Final browser evidence: zero page errors, zero console errors, zero blocked cloud requests, zero paid submissions and zero wallet debits. The one failing assertion is the missing audit badge.

All 30 captures were visually inspected through eight contact sheets. Viewers render recognizable fixture content, light/dark chrome is distinct, and the expected controls are visible. The rig-audit badge is visibly absent. Tiny synthetic image/video fixtures are deliberately pixelated when enlarged. No real keys, credential fields, user data or live host names were observed. Library/job IDs and filenames are synthetic. Contact sheets are navigation aids; originals are authoritative.

## Screenshot manifest

Each basename below has both `-light.png` and `-dark.png` under `screenshots/`:

| Basename | Surface |
| --- | --- |
| `3d-model` | Static mesh |
| `animation-rigged` | Rigged animation, missing audit badge |
| `audio-sfx` | WAV waveform and conversion menu |
| `env-360-stickers` | HDR panorama and sticker overlay |
| `pbr-material` | Combined PBR material preview |
| `image-concept-compare` | Image comparison and provenance |
| `video-player` | Scrubbed video and exact-frame controls |
| `task-progress-card` | Completed task morph and Next actions |
| `workspace-library` | Library, chips, sidebar, palette |
| `workspace-jobs` | Jobs tab and chrome |
| `workspace-concepts` | Concept history/detail and chrome |
| `workspace-upload` | Upload tab and chrome |
| `task-progress-queued` | Additional queued-state evidence |
| `task-progress-running` | Additional running-state evidence |
| `webgl-pool-six` | Additional mixed-pool budget evidence |

Total: 24 requested captures plus 6 supplementary captures = 30 unique PNGs. `visual-manifest.json` and `visual-partial.json` preserve computed styles, layout, findings and browser errors even when the acceptance assertion fails.

## Host admission

`tools/verify_v08_host_compat.py` copies the plugin payload to a disposable `HERMES_HOME` under `TMPDIR`, excludes inherited credentials/profile selectors, uses a dummy key and deletes the home afterwards. It checks the actual reference APIs, PM declaration reader, runtime skill/MCP registration and dashboard router import, then separately invokes the reference and installed CLIs.

Per Tris's explicit task ruling, the authoritative host is `/home/deploy/work/realtwin/hermes-studiotwin/reference/hermes-agent`. The older installed `/home/deploy/.local/bin/hermes` remains independently exercised and its failures remain verbatim in `host-compat.json`: it rejects `cost_unit`, `costs` and `timeout`. This report does NOT claim installed-host compatibility. No production cost or timeout declarations were removed.

Authoritative results: validation `ok=true`, `warnings=[]`; manifest, Python, MCP, Desktop, skills and isolation checks pass; isolation verdict `portable`, `host_ready=true`; `pyproject_installs=false`; runtime skill `studiotwin` and MCP `studiotwin` registered; dashboard APIRouter loadable; doctor API and CLI pass. Both reference CLI commands exit 0. The pinned doctor parser does not support `--json`; its actual invocation is `plugins doctor TARGET --ci`, verified by a parser-rejection regression test.

The suggested `/opt/openclaw/claude-code/.hermes/hermes-agent/.hermes/py` directory is absent here. Explicit disposable dependencies were installed under `$TMPDIR/v08-host-dependencies` for the managed-Python probe. A workspace-owned `.venv` was subsequently provisioned for all normal tests; no live runtime environment was modified.

Reproduce host probe (the managed interpreter path contains a wildcard intentionally):

```sh
PYTHONDONTWRITEBYTECODE=1 \
PYTHONPATH=/home/deploy/work/realtwin/hermes-studiotwin/reference/hermes-agent:$TMPDIR/v08-host-dependencies \
/home/deploy/.hermes/tools/python-*/bin/python3 tools/verify_v08_host_compat.py \
  --dependency-path "$TMPDIR/v08-host-dependencies" \
  --hermes /home/deploy/.local/bin/hermes \
  --output evidence/v08/host-compat.json
```

`host-compat-tests.log`: 14 tests passed, including deliberately malformed manifests, buildable Python declarations, credential exclusion, real CLI invocation and authority-gating unit tests. The full pytest run also includes these tests using the workspace interpreter.

## Full gates and remaining work

Commands executed against this QA source and unchanged production bundle:

```sh
STUDIOTWIN_BLENDER_TEST=1 PYTHONPATH=/home/deploy/work/realtwin/hermes-studiotwin/reference/hermes-agent .venv/bin/pytest -q
STUDIOTWIN_WEBGL_TEST=1 STUDIOTWIN_CHROME=/opt/google/chrome/chrome npx vitest run
npm run typecheck
npm run build:desktop
git diff --exit-code -- desktop/plugin.js
```

- Python: 194 passed, including Blender-enabled tests (`pytest.log`). Pytest emits an unset asyncio fixture-loop-scope deprecation warning.
- Vitest: 147 passed, 1 failed; only V08's real production rig-audit badge assertion fails (`vitest.log`). Existing RGBELoader deprecation is emitted in the node unit test, not as a browser console error.
- Typecheck: passed (`typecheck.log`).
- Desktop build: passed, zero diff in `desktop/plugin.js` (`build.log`, `bundle-diff.log`).
- Frozen scaffold, build configs, SDK declaration and package manifests remain unchanged.

These are RED acceptance results, not successful V08 completion. The QA checkpoint is committed separately from any production remediation. Resolve the missing audit through a real production metadata/inspection path (never fabricate a passing audit), then rerun all gates and host verification on the final committed HEAD, recapture/inspect evidence, and complete V08 to release the pre-created Salt review. No successful exact-HEAD acceptance or release approval is claimed.
