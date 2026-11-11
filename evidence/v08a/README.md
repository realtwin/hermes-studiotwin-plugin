# V08a — captured-catalog alignment

Base: Salt-approved V07 `cf7ce72fbb3392c2a93305396b75a457bf9249bd`.
Branch: `feat/v08a-catalog-alignment`; worktree: `/home/deploy/work/realtwin/hermes-studiotwin/worktrees/v08a`.
The final exact commit SHA and exact-HEAD verification results are in the task t_e79ffed5 handoff (avoids a self-referential commit identifier here).

## Delivered behavior

- `src/cards/action-costs.ts` owns one small exported map, checked against `tests/fixtures/contracts/tools-list-summary.v1.json`. Image next costs are `[null, 25, null, 25, null]`. Fixed labels are `n cr`; variable/Concept-paid actions say `estimate in chat` and their composer message says `estimate first`, without a price number.
- Environment/material action labels now use that same map. Their existing prices already matched the fixture; no price was changed there. All three families retain exact-input estimation with `studiotwin_estimate_cost`, explicit approval and local-upload consent. No card fetches estimates or submits generation.
- The image viewer recognizes both current `openai-gpt-image-2-v4-fn` and legacy `openai-gpt-image-1-v1-fn`, plus Concept tools. Discover the live schema and do not call the legacy identifier.
- `tool-names.ts` supplies shared de-duplicated bare/canonical-hyphen/canonical-underscore/single-prefix-underscore aliases for image/video/env/material registrations. Render callbacks retain their own tool-name filters. The model wildcard registration is unchanged.
- Env accepts only env images/HDR/EXR or JSON results; material accepts only material images/JSON/ZIP results; video only video; image only image; model only file-kind supported model formats/JSON. The explicit model file-kind check prevents a misclassified image/video from being hijacked by its filename.

## Falsifiable coverage

`tests/viewers/catalog-routing.test.ts` enumerates every captured generation tool and Concept-paid tool, retained image/read-only Concept names, terminal and foreign negative controls. It independently enumerates four alias forms and twelve kind/name cases, invokes all five render callbacks and asserts exact ownership (one expected renderer, or none for unsupported media). This tests direct callback refusal as well as explicit registration coverage. The model wildcard is separately asserted unchanged; direct model callback checks do not imply that the host dispatches bare model names through that wildcard. Audio remains its existing independent renderer and is not claimed by these five.

All map entries, image action costs/labels/messages and every env/material action label are grounded in fixture `fixedCost`, including null. No backend estimate is fetched by any next action.

RED evidence:
- `red.txt`: original current-image-name and numeric Concept-edit assertions fail. The first new routing-suite attempt also exposed a missing SDK Button test double; corrected before collecting the substantive routing RED below.
- `routing-red.txt`: original implementation fails 17 tests: missing video aliases, env/material consuming unrelated media, missing current image name, stale pricing.
- `mutation-price.txt`: restoring mesh cost 30 makes fixture comparison fail (exit 1).
- `mutation-alias.txt`: removing canonical hyphen-prefixed alias makes routing assertions fail (exit 1).
- Both mutations were reverted before final build/verification.

Integration corrections, not hidden failures:
- `vitest-precommit.txt` records an old env browser assertion requiring the pre-V08a sentence. Updated it to require the new explicit estimator-tool wording, retaining approval assertion.
- `vitest-green.txt` records the bundle browser fixture incorrectly tagging GLB as `image`. Corrected the fixture to SDK `file` (no SDK/scaffold changes), retaining real model load and WebGL rendering assertions. This exercises the new restrictive model filter rather than bypassing it.

## Verification and reproducibility

Precommit successful runs: `pytest-precommit.txt` has 179 passed / 1 optional Blender skip; `vitest-green-final.txt` has 144 passed across 9 files, no skips, including real Chromium/WebGL. Typecheck and host validation passed. Exact-committed-HEAD verification is repeated after committing these files, with outputs under ignored `.verification/v08a-*`; the durable board handoff records its SHA/results.

Commands from this worktree (dependencies reused from V07, not installed live):

    PYTHONPATH=/home/deploy/work/realtwin/hermes-studiotwin/reference/hermes-agent .venv/bin/pytest -q
    STUDIOTWIN_WEBGL_TEST=1 STUDIOTWIN_CHROME=/opt/google/chrome/chrome npx vitest run
    npm run typecheck
    npm run build:desktop && git diff --exit-code -- desktop/plugin.js
    PYTHONPATH=/home/deploy/work/realtwin/hermes-studiotwin/reference/hermes-agent .venv/bin/python tools/verify_v07.py

`verify_v07.py` exercises `validate_plugin_dir`, zero warnings/diagnostics and actual portable skill discovery. The rebuilt bundle SHA256 is `9a8026c592b7d9f901ca8898c15578dbcc783c3deae4dd72045ca8b44e9ee7f5`; a second precommit rebuild produced identical bytes. Bundler identifier allocation creates a broad generated-file diff; handwritten changes remain narrow.

Frozen paths (`tests/scaffold/*`, Vite/Vitest configs, `src/sdk.d.ts`, package/lock files) have no diff from the approved base. No paid calls, authenticated cloud calls, live installation, push, publish or release approval. Existing settings limitations are left for V08b. Salt's independent review is the next graph phase.
