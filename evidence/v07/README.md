# V07 bundle, bundled skill and catalog documentation

## Delivered

- `src/plugin.tsx` assembles all eight V02–V06 registration helpers and exports the plugin for default-export hosts. A namespace SDK optional `registerPlugin` call supports registration-door hosts as well.
- Namespace SDK value imports throughout `src/`; safe area fallbacks use the actual pinned host strings, not illustrative `chat.*`/`app.*` strings. Hosts missing tool-media support retain built-in players rather than receiving unsupported contributions.
- Committed `desktop/plugin.js` built by `npm run build:desktop` (alias of the unchanged Vite build). Its external imports are exactly `@hermes/plugin-sdk`, `react`, `react/jsx-runtime`; no unbundled dependencies, dynamic imports, node imports, eval or Function constructor.
- Six tool-media renderers, nine directives including the previously missing `studiotwin-concept`, `/studiotwin`, sidebar navigation, six palette entries and two status chips.
- `skills/studiotwin/SKILL.md` 0.2.0: all 45 captured tools, live-schema routing, cost/approval policy, Concept lifecycle, exact directives, all four real helper CLIs, delivery/provenance and a host-aware notification poller.
- README and after-install: direct remote MCP setup, capabilities, all nine declared settings, cost/data/storage/process disclosures and honest limitations.

## Verification and sensitivity

Before commit:

- `npm run build:desktop` succeeded.
- `npm run typecheck` succeeded.
- `PYTHONPATH=<reference Hermes> .venv/bin/pytest -q`: 179 passed, 1 optional Blender test skipped.
- `STUDIOTWIN_WEBGL_TEST=1 STUDIOTWIN_CHROME=/opt/google/chrome/chrome npx vitest run`: 111 passed, no skips.
- `PYTHONPATH=<reference Hermes> .venv/bin/python tools/verify_v07.py`: `ok=true`, `warnings=[]`, one discovered `studiotwin` skill version 0.2.0 and existing Desktop artifact.

All mandatory commands are repeated on committed HEAD before Kanban completion; final logs and exact commit go in the task handoff and ignored `.verification/` directory.

`tests/bundle/plugin-bundle.test.ts` serves the production bundle byte-for-byte to Chromium with an import map. Only React/Query and SDK host modules are fixtures; the plugin is NOT rebundled against a stub (which could hide missing ESM exports). Tests exercise full SDK and missing area/registerPlugin exports; register default export; render all six modalities through real directives and own-tool media renderers; decode real fixture files through the real backend; render task/job/Concept cards and chrome; invoke palette actions; and check foreign-tool fallback, no browser cloud requests and no paid submission/debit. Backend is the real FastAPI router/direct MCP client over loopback FakeStudioTwin and storage. This is not a live Hermes Desktop installation.

Three Python cases execute the documented wake adapter with the real direct HTTP client against seeded completed/failed/cancelled loopback jobs. They verify exit 0 for completion, nonzero for failure/cancellation and no paid generation. This does not claim a live messaging wake or paid provider result.

RED: `bundle-red.txt` shows the compiled-artifact test failing before `desktop/plugin.js` existed. `tools/check_v07_mutations.py` proves a missing SDK named export fails Chromium ESM linking, and omitting `registerTaskCards(ctx)` fails the registration inventory. It restores original source and artifact bytes in `finally`; both faults were detected with exit 1. The old V05 inventory expectation was extended by exactly `studiotwin-concept`, reflecting the newly required directive rather than relaxing an assertion.

## Host-contract decisions

- The frozen `tests/scaffold/scaffold.test.ts`, `vite.config.ts`, `vitest.config.ts`, `src/sdk.d.ts` are unchanged. Scaffold's import graph still does not load `src/`.
- The pinned portable host auto-discovers `skills/*/SKILL.md`. Adding the task's requested top-level `"skills": ["skills"]` produces `ignored unknown top-level field: skills` and breaks the required zero-diagnostics/zero-warnings gate. Therefore no ignored manifest field is shipped. Real host discovery, not a placeholder declaration, is verified by `tools/verify_v07.py`; this deviation is recorded on the task.
- Both official sibling `after-install.md` files are absent at the reference checkout. New post-install content follows the catalog guidance rather than claiming to copy nonexistent files.
- No local MCP server/proxy, TCP IPC, URL-redaction service, opaque-handle table, custom credit reservations or artificial 200-credit cap was added.

## Inherited gaps routed separately

Follow-up triage: `t_9408178b` (Tris).

- `src/cards/next-actions.ts` has stale illustrative image workflow prices. V07 does not claim these are live estimates; the skill requires estimation/approval. They need a narrow follow-up.
- Captured current `openai-gpt-image-2-v4-fn` differs from legacy `openai-gpt-image-1-v1-fn` viewer routing; the docs preserve and distinguish both identifiers instead of guessing compatibility. Provider naming/ownership needs a follow-up audit.
- `inline_cards`, `auto_rotate`, `gallery_limit` remain declared but not wired across the UI. Workspace inspectors use configured `webgl_limit`; inline viewers retain the four-context default. Docs disclose this rather than falsely claiming live support. Settings wiring is separate from this assembly/import audit.
- `npm audit` reports three inherited development-tool findings: one moderate, two critical, in the frozen Vitest/mocker/tinypool graph. These packages are not shipped in the production bundle. Existing Tris disposition in `t_d6dee7c0` and `t_28a28cfe` is not reopened; no dependency/scaffold migration was performed.

No paid generation, live-profile install, publication/push, full catalog submission, authenticated cloud call, live messaging delivery or release approval was performed. Salt's pre-created review child is released by implementation completion.
