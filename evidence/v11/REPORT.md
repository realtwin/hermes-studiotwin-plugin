# V11 Studio Craft & UX — implementation evidence

Branch: `feat/v11-studio-craft-polish`  
Base: `dbefdf6946762b89871022b89f9cdc112b6c8f04`  
Release metadata: `0.3.0` in `plugin.json`, `dashboard/manifest.json`, and `[project]` in `pyproject.toml`.

## Acceptance ledger

| Requirement | Implementation | Executed evidence |
|---|---|---|
| 1. Settings precedence | Desktop settings override legacy config per key; exact default-type validation retained. The base already read settings, but discarded legacy config. | New Python precedence/fallback/type test; regression mutation fails. |
| 2. Opaque inspector | Separate full-window scrim, outside-click close, opaque elevated surface, retained Escape/focus trap/scrolling. Image inspection uses the same opaque token; nested Escape no longer closes its parent inspector. | Production-bundle light/dark tests with **8%-opaque card tokens**, backdrop dismissal; existing inspector wheel-scroll tests. |
| 3. Names and modality | Trailing `@uuid` and leading cache prefix cleanup; S3 basenames and generated-ID fallback titles; HDR/EXR and panorama folders; PBR channel filename recognition. Original Library accessible names retained. Viewer source names are also cleaned so suffixes do not break decoder extension detection. | Five V11 data tests plus real cloud-shaped list/resolve browser responses, existing exact-name selectors. |
| 4. PBR siblings | Loaded complete library supplies same-directory, same-stem siblings; aliases map basecolor/albedo, normal/normals, metallic/metalness, height/heightmap. Explicit maps remain authoritative. | Inspects the **normal** sibling, loads the real MaterialViewer and verifies all five channels enabled; unit negative controls for other directories/stems. |
| 5. Library cards | Fixed-height modality poster, Codicon/badges/extension, clean opaque title row, short ID/date/size; viewport-admitted image thumbnails, at most first eight cloud images, no grid WebGL. | Real decoded PNG posters; library/filter/search/late-page tests and light/dark screenshots. |
| 6. Jobs | Friendly badge plus canonical function name, prompt and input/model/timing/rig/date metadata, lazy image preview, Copy ID and Reuse Prompt to captured originating chat. | Clipboard readback and exact composer payload; existing filters/cancel tests; three production-bundle V11 tests. |
| 6. Expanded output inspection | `/jobs/{jid}/output` resolves existing unindexed mesh/model/HDR/audio links through the **existing guarded storage reader**, exclusive cache save and local media route; negative rig-check results get an explicit metadata view. No generation or billing path added. | Backend exact-byte tests for GLB/HDR/WAV and unexpected-origin refusal; browser loads real model/environment canvases, audio waveform, and negative rig result. |
| 7. Concepts | Selectable neutral studio list cards with active indicator, type/date/version metadata when supplied; compact workflow action bar with unchanged exact button labels and credit badges. | Existing Concept history/version/composer tests; responsive 480px/two-column tests. |
| 8. Upload | One visible destination control rather than duplicated toggles; preserved Cloud upload checkbox. File input overlays a styled Choose file… label, preserving exact Reference file access. | Existing local file selection, explicit cloud drop, scope-switch and pre-network upload tests. |
| 9. Inspector/viewers | Clean title/icon/badges, ID copy, original download, metadata and prompt reuse. Redundant Material selects visually hidden but screen-reader/test accessible; removed from sequential tab order in favor of visible channel/geometry buttons. | Existing channel/geometry selectOption tests and real PBR canvas controls; production inspector screenshots. |
| 10. Version/build/gates | Metadata bumped without touching locked JS package files; bundled ESM rebuilt deterministically. | All gates below; package files unchanged; no build-system table. |

### Thumbnail cache regression caught during integration

Fetching cloud thumbnails populates the local media index. On the next library refresh, a managed cache filename previously replaced the original cloud name. Managed `studio_cache` entries now retain cloud name/type/extension/S3 metadata; explicitly named local project copies still retain their existing name override contract. Both contracts are tested. This also preserves exact Library button labels after profile refresh.

## Final execution

Environment (no dependency changes):

```sh
export PATH="/home/deploy/.hermes/tools/node-26.12.1-linux-x64/bin:/home/deploy/.hermes/tools/ffmpeg-9.0.1-linux-x64/bin:/home/deploy/.local/bin:/home/deploy/work/realtwin/hermes-studiotwin/worktrees/v09/.venv/bin:$PATH"
export PYTHONPATH=/home/deploy/work/realtwin/hermes-studiotwin/reference/hermes-agent
npm run typecheck
npm run build:desktop
npx vitest run
pytest
HERMES_HOME="$PWD/.verification/v11/validate-home" python -m hermes_cli.main plugins validate "$PWD"
```

The final validate command is the host interpreter equivalent of `hermes plugins validate`, using a disposable home to avoid launcher-managed environment preparation.

- **pytest:** 237 passed, 1 skipped (**238 collected**, original 235 plus 3).
- **Vitest:** 238 passed, 38 skipped (**276 collected**, original 268 plus 8); 19 test files passed, 1 skipped.
- **TypeScript:** exit 0.
- **Plugin validation:** `Validation passed.`; remote MCP trust untrusted, 27 costed tools, **no spend limit**.
- **Build determinism:** two successive builds matched byte for byte. SHA-256: `eed5c8aacad26fdf480674eede7b52b8e307a4229145b8227e93fd5163ad1193`.
- **Guardrails:** `git diff --exit-code -- package.json package-lock.json` and `git diff --check` pass. `pyproject.toml` remains `[project]`-only. No local MCP gateway, TCP IPC, URL redaction, opaque handles, reservation machinery, or artificial credit cap added.

Initial baseline failures were environment-dependent, not waived: the shell selected Node 22 (below the locked >=24 contract), pytest was absent from its PATH, and system FFmpeg 6 generated different MP3/MP4 fixture bytes. Node 26, the existing Python 3.14.7 test venv, and FFmpeg 9 fixed those conditions. Blender 4.2.3 is on PATH. The fixture generator's `--check` then matched all 18 files with zero differences. No fixtures or lockfiles were regenerated to make tests pass.

## Regression sensitivity

Tests/assertions were left intact while base implementations were temporarily restored, then original working bytes restored in `finally`:

- Backend mutation: **3 failures** (legacy settings fallback, managed thumbnail name preservation, missing job-output route).
- Data mutation: **4 failures**, 1 unaffected job metadata test passed (name stripping, cloud names, modality, sibling channels).
- Committed-bundle mutation: **3 failures** (cloud material/name surface, prompt reuse, unindexed output inspection).
- Full suites above passed again after restoration. Logs are alongside this report. Initial settings/data tests were also executed RED before implementation; an initial job test fixture omitted its required cost field, was corrected, and is **not** counted as valid RED evidence.

## Evidence scope and limitations

Screenshots under `screenshots/` were generated by **real Chromium loading the rebuilt production bundle**, real Three.js/media decoders and the plugin's real FastAPI backend against deterministic loopback StudioTwin/storage fixtures. Host SDK components are test shims (including no-op Codicons and basic SDK buttons), not the actual Desktop chrome. The material fixture's height channel intentionally reuses a valid grayscale roughness image to test five-channel wiring; it is not presented as a provider-generated material.

This run did **not** log into live StudioTwin, spend credits, install into a daily Hermes profile, publish, merge, or deploy. It does not claim first-hand live validation of the 673-asset cloud account. Independent Salt review is already encoded in child card `t_e757f8bb`; completing this implementation card releases that review, not release authority.
