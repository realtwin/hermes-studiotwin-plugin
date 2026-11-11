# V10 implementation evidence

Implementation phase; independent Salt review is downstream task t_1900a20a.

## Exercised paths

- Real Chrome/SwiftShader ModelStage capture: canonical camera yaw/pitch, four shading passes, labeled 4/6-view PNG dimensions and pixel content, alpha/studio backgrounds, current animated pose, repeatability, camera/material/grid/animation/canvas restoration, and restoration after injected PNG encoding failure.
- HDR image-based lighting changes actual model pixels in textured and clay passes; clearing restores the exact original snapshot. Show-background/null and malformed HDR paths exercised.
- Source React components and compiled Desktop bundle: accessible controls, 6-view normals download, local upload/provenance ordering, disabled reskin on errors, and profile/connection switch with a pending upload.
- Byte-for-byte production Desktop bundle served against the real FastAPI router and loopback fake StudioTwin provider: local PNG saved and reopened through /file, provenance persisted and read back by its actual UUID, originating composer receives sheet path/source, no provider submissions or credit debits.
- CLI renders both static-cube.glb and rigged-animated.glb across 4/6 views and textured/clay/normals/wireframe, transparent/no-labels/split options, deterministic bytes, JSON contract, argument validation and no-clobber output handling.
- Existing MP4 preview regression and real static/animated renders after extracting its unchanged Chrome pipe/blob-module harness.
- Complete asset-library query is shared by the Library and inspector IBL picker, including pagination rather than only the first 100 assets.

## RED, GREEN and sensitivity evidence

- multiview-red.log: CLI tests failed before implementation.
- webgl-red.log: real Chromium baseline before stage/UI APIs; last run 23 failed, 1 passed. Earlier harness attempts are preserved in the same log.
- canonical-mutation-red.log: deliberately changed actual 3/4 camera yaw from 35 to 45 degrees. The canonical-angle test failed with measured 45 versus expected 35. Mutation reverted before green gates.
- vitest-full-initial.log: caught two existing strict-locator regressions from adding a second toolbar. Fixed production Multiview control container to an accessible group, preserving the existing Model controls toolbar and tests unchanged.
- router-readback-test-red.log: the new real-router test initially expected the provenance identifier inside record metadata. Corrected to the actual existing API contract: top-level id, record containing stored metadata.
- Initial delegated test assumptions were aligned to the charter and existing API before acceptance: tile sizes are clamped as requested, and /upload uses data (not an invented data_base64 field). No backend compatibility shim was added.
- multiview-green.log: 31 new CLI tests passed.
- pytest-full-initial.log: 225 tests passed with Blender enabled.
- webgl-green.log: 26 V10 Chromium tests passed.
- vitest-full-green.log: 206 tests passed, preserving all existing 180 tests.
- shared-library-regression-green.log: all 46 workspace + V10 tests passed after extracting the shared paginated library hook.
- host-compat-initial.json: authoritative reference validator and doctor passed, warnings=[], actual skill/MCP/dashboard/runtime loading checked. No real paid generation.

The implementation is committed before the final gate run. Exact-commit verification logs are generated after that commit under ignored evidence/v10/exact-head/ and linked in the Kanban handoff, so no second evidence-only commit changes the verified HEAD. Existing V08 screenshot outputs are restored after test runs; V10 screenshots/samples remain here.

## Artifacts inspected

- screenshots/multiview-reference.png: actual compiled card after six-view normals capture/staging; all six view labels/badges, Download Sheet and Reskin controls visible, no clipping observed. This is an internal test capture with a temporary backend path, not a public marketing screenshot.
- ui-6-normals-sheet.png: actual sheet retrieved back from the real backend.
- verified-cube-4-clay.png: parent-run CLI output, 1024×1024, 34018 bytes, four split files in verified-cube-views/.
- rigged-6-normals.png: six-view CLI sheet; all six tiles nonempty/framed and labels legible. The fixture is a simple skinned rectangular column, not a humanoid.

## Boundaries

- Capture and handoff are free local operations. No live paid ConceptLab/image-edit/mesh-reconstruction execution was authorized or attempted.
- The reskin action is composer-only and requests live-schema compatibility, per-stage credit estimation, approval, and approval before uploading local references. Reconstruction is not guaranteed to retain topology, rig or exact geometry.
- Existing local provenance stores file links in prompt text under a local UUID, with a sourceAssetIds link when a cloud source UUID is known. It does not fabricate cloud asset IDs or claim local file paths are structured cloud lineage.
- Development dependencies are existing V09 node_modules/.venv symlinked into this worktree (the original node_modules symlink was broken). Frozen package manifests/lockfile, SDK declarations, scaffold tests, Vite and Vitest configs are unchanged.
