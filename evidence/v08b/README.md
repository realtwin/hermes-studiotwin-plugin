# V08b — reactive Desktop settings wiring

Base: V08a c66dfccd52662308e12d14482cc1e81a8920a75a. Branch: feat/v08b-settings-wiring. The reviewed implementation SHA is the commit containing this file; exact-HEAD logs are generated after committing, under ignored `.verification/v08b-*`.

## Behavior and scope

- `src/cards/settings.ts` shares the existing scope-keyed `/status` React Query cache with workspace/chrome. Boolean validation and finite integer clamping use manifest defaults: inline_cards=true, auto_rotate=true, webgl_limit=4 (1–4), gallery_limit=24 (1–100).
- A deduplicated settings-changed subscription invalidates only the current scope's `/status`. Scoped REST/query helpers retain their original profile/connection revocation behavior. Missing/failed settings use defaults; no credentials reach the browser.
- `src/cards/inline-settings.tsx` decorates the production entrypoint's transcript registrations with mounted components, not registration-time snapshots. All six tool-media renderers restore the host fallback when disabled. All nine directive registrations restore plain directive source text. The workspace, sidebar, palette and statusbar use the original context, not this gate.
- The inline boundary supplies live webgl_limit to model/environment/material cards and auto_rotate to model cards. Model viewers follow auto_rotate until manually toggled, then preserve a local override across settings updates. Workspace model and animation previews receive the same setting.
- Concepts and Jobs request/paginate using gallery_limit and reset offset on a size change. Complete Library paging remains exactly 100 rows per request and reads all pages before filtering. All-page active-job counting is unchanged. No separate recent-assets strip exists in this workspace.
- README, after-install and the bundled StudioTwin workflow document the actual boundaries. Historical V07 evidence remains unchanged.

## Verification and regression sensitivity

- `red.txt`: new defaults/clamping tests initially failed because the settings module did not exist.
- `vitest-precommit.txt`: the first integration run caught the frozen scaffold's root-file whitelist. Shared modules were moved into the existing `src/cards/` directory; scaffold/config/package/SDK files were not changed. This log also records a test selector correction (asset buttons are named `crate.glb`, not `Inspect crate.glb`).
- `vitest-green.txt` (despite its provisional filename, this is a failing intermediate run): Chromium exposed a real settings-refresh regression. The old chrome handler invalidated every workspace query; model detail then changed from its cloud source to a newly cached local path and disposed the active viewer. Settings now invalidate only `/status`; tool-complete still refreshes workspace data. The new workspace test exercises initial auto-rotate, settings refresh and manual override on that same live cloud model.
- Pool-test selectors include poster alt text after eviction; the real UI exposes `Panorama poster Load environment` / `Model preview Click to load 3D`, not the pre-load exact name. The assertions still require one evicted poster and one live canvas/toolbar after activating two viewers at limit=1.
- `mutation-limit.txt`: replacing configured inline webgl_limit with 4 failed the Chromium bundle test (no environment eviction); reverted.
- `mutation-inline.txt`: removing the inline_cards gate failed the Chromium bundle test (both mounted model fallbacks absent); reverted.
- `vitest-final-precommit.txt`: 147 passed across 10 files, with WebGL enabled and no skips. Includes committed-artifact import with full/older SDK fixtures, model/env/material pool limits, model initial rotation and local override, all disabled media/directive fallbacks, recent Concepts/Jobs page sizes, and complete-library tests beyond 100 rows / late-page error handling.
- `pytest-precommit.txt`: 179 passed, 1 optional Blender skip.
- Typecheck and reference-host `validate_plugin_dir` passed (ok=true, warnings=[], StudioTwin skill 0.2.0 discovered, zero diagnostics).

Exact-HEAD verification commands (logs retained locally for the reviewer):

```
PYTHONPATH=/home/deploy/work/realtwin/hermes-studiotwin/reference/hermes-agent .venv/bin/pytest -q
STUDIOTWIN_WEBGL_TEST=1 STUDIOTWIN_CHROME=/opt/google/chrome/chrome npx vitest run
npm run typecheck
npm run build:desktop && git diff --exit-code -- desktop/plugin.js
PYTHONPATH=/home/deploy/work/realtwin/hermes-studiotwin/reference/hermes-agent .venv/bin/python tools/verify_v07.py
git diff --exit-code c66dfcc HEAD -- tests/scaffold vite.config.ts vitest.config.ts src/sdk.d.ts package.json package-lock.json
```

## Completed task/job remediation (t_093d28cc)

Salt B1 correctly identified a missing nested path: `TaskCard` discarded the boundary's viewer options, and `CompletedMedia` created a model with defaults. Both now explicitly forward `auto_rotate` and `webgl_limit` into `ModelCard`, for both 3d_model and animation outputs. The viewer's existing per-instance manual override is unchanged.

The byte-for-byte Desktop-bundle Chromium test now seeds a completed task/3d_model and job/animation through the existing loopback fixture (no generation submission). For each, it loads a direct companion model first, then mounts/loads the completed preview. It asserts configured rotation=false, one-context eviction in both directions, event-driven rotation=true, and manual rotation=false surviving subsequent false/true settings events. Disabling inline cards also removes the completed preview.

- `completed-model-red.txt`: original bundle fails on completed preview rotation (expected false, received true).
- `completed-model-mutation-limit.txt`: forwarding rotation but forcing the completed model limit to four fails because the companion is not evicted. Mutation reverted. Mounting the nested card only after the companion is live is important: simultaneous mounts can mask the wrong limit by effect ordering.
- `completed-model-green.txt`: four bundle tests pass with the final source and rebuilt artifact; typecheck also passes.
- Test config writes now wait for the preceding status refresh to settle, then verify the event-updated active query. This avoids rapid fixture writes racing an initial data-less in-flight query; no mocked settings/cache injection or production query bypass is used.

Remediation exact-HEAD verification logs are generated after committing under ignored `.verification/v08b-remediation-*`, using the same commands above. Frozen paths remain unchanged. This remediation requires Salt review before approval.

## Limitations / next gate

Chromium runs the real committed Desktop artifact against host SDK fixtures and a real loopback router/MCP/storage backend, not an installed live Desktop. Reference-host admission is not validation against current upstream main. No paid generation, authenticated cloud requests, live install, push, publish, merge or release authorization. Salt review t_33f9c62e is the next gate.
