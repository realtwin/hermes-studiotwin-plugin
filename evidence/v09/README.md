# V09 — StudioTwin design system and UI polish

Implementation is complete on `feat/v09-ui-polish`, based on `cdd48c6`. Independent approval belongs to the existing Salt child `t_9ff1edbe`; this document is not release approval.

## Delivered

- Shared scoped inline primitives in `src/lib/ui-tokens.ts`: card headers/body/footer, translucent toolbars, tabular HUD/stats, themed selects/ranges, accent tabs/pills, status/modality/credit badges, cache-name cleanup, poster tiles and Next drawers. No global stylesheet injection.
- Cohesive headers and modality badges on model/motion, environment, material, image/Concept, video, audio and task-progress cards. Audio's actual card UI lives in `audio-viewer.tsx`, so its thin registration adapter is unchanged.
- Themed model controls/stats and animation transport; recessed audio waveform with transport/conversion controls; environment exposure/sticker FOV pills and working auto-rotate/reset (animation frame cancelled on disposal); material geometry/channel pills synchronized with the preserved accessible selects; image comparison/inspection with zoom presets and pan; video transport/timeline; status-coded job progress and completed-media transition.
- Workspace header/connection/balance, active segmented tabs, responsive Library cards with full-width inspect targets and preserved raw accessible names, horizontal Jobs, responsive two-column Concepts/history/workflows, Local/Cloud upload modes and centered drop hero, and status chips.
- All existing source tests remain untouched. In particular frozen scaffold/config/SDK/package files are byte-unchanged from the base. No backend, MCP, billing, cost approval, credential, redaction or transport changes.

## Design/compatibility decisions

Surfaces inherit host theme colors rather than carrying fixed dark fallback colors into a light workspace. Shadows use host variables and theme-aware color-mix. Active foreground falls back to the host background (light text on a dark-blue light-theme accent; dark text on a pale-blue dark-theme accent), instead of forcing white on both accents. Semantic emerald/amber/rose status fallback tints remain centrally defined; host overrides take priority. Glass HUD text/background use stable readable fallbacks and optional host overrides.

Material native selects remain visible alongside pill shortcuts to preserve keyboard/accessibility contracts and existing exact-label interactions. Library inspect buttons have their original exact raw `aria-label`; cache-prefixed files display clean titles and short IDs, with the full raw value also retained as a subdued subtitle. Provider asset names made entirely of hashes remain provider filenames, not invented semantic titles.

## Verification

- Blender-enabled Python suite: 194 passed (`pytest.log`).
- Real Chromium/WebGL Vitest suite: 178 passed across 13 files, comprising all 176 pre-existing tests plus two V09 tests (`vitest.log`).
- Typecheck and desktop build passed (`typecheck.log`, `build.log`).
- Host admission passed against the authoritative reference checkout: API/runtime checks, CLI validate, CLI doctor, `warnings=[]` (`host-compat.json`). The older installed launcher still fails its old schema checks, as in V08; its complete output is retained, not hidden.
- Regenerated all 30 PNGs and eight light/dark contact sheets in `evidence/v08` from the compiled production bundle. Manifest/disk counts match. Zero browser page errors, console errors or horizontal overflow; no paid submissions. `tools/v09_contact_sheets.py` checks capture completeness and reproduces contact sheets.
- Inspected all eight baseline sheets and all eight refreshed sheets using vision. Shared header hierarchy, clearly accented active controls, status colors, transport spacing, Concepts split layout and upload hero are visible in both themes. Library and Concepts have intentionally scrollable content. Small deterministic source media are visibly synthetic; no claim of a real paid provider generation or production Desktop session is made.
- `tools/verify_v09_evidence.py` verifies frozen files, counts, successful gates and manifests.

## Failure and sensitivity evidence

`polish-red.log` records the new production-bundle test failing because the Cube pill was absent before implementation. `polish-green.log` records it passing after implementation. The new test exercises both themes' computed active styles, exact raw filename access, responsive Concepts at 480 px, real material pill/select synchronization and environment rotate/reset controls. A deliberately disabled active-style branch caused both the pure token assertion and real-browser computed-background assertion to fail (`mutation-active.log`). The mutation was restored before final gates and screenshots.

`vitest-first.log`, `vitest-second.log`, and `vitest-third.log` preserve setup/compatibility failures and the subsequent all-existing-tests pass. The waveform border was moved to a wrapper after the real seek-precision test caught a geometry shift; no seek assertion was weakened. Isolated workspace Python dependencies and Node modules were installed because initial symlinks/dependencies were absent. No live profile runtime was modified.

## Reproduction

Run from this worktree:

    STUDIOTWIN_BLENDER_TEST=1 PYTHONPATH=/home/deploy/work/realtwin/hermes-studiotwin/reference/hermes-agent .venv/bin/pytest -q
    STUDIOTWIN_WEBGL_TEST=1 STUDIOTWIN_CHROME=/opt/google/chrome/chrome npx vitest run
    npm run typecheck
    npm run build:desktop
    .venv/bin/python tools/v09_contact_sheets.py
    .venv/bin/python tools/verify_v09_evidence.py
    PYTHONPATH=/home/deploy/work/realtwin/hermes-studiotwin/reference/hermes-agent .venv/bin/python tools/verify_v08_host_compat.py --dependency-path "$PWD/.venv/lib/python3.14/site-packages" --output .verification/v09-host.json

For exact committed-HEAD reruns, set `V08_EVIDENCE_DIR=.verification/v09-exact-head-visual` so tracked screenshots are not rewritten. Exact-head logs live under `.verification/` and the lifecycle handoff records their SHA/results. The rebuilt `desktop/plugin.js` must have zero git diff.

The browser harness imports the real compiled bundle and calls the real dashboard router with deterministic loopback provider fixtures. It is not the native Hermes Desktop shell: SDK Codicon glyphs are stubbed by that adapter, even though production JSX uses Codicon. No live API key, cloud generation, live installation or paid transaction was used.
