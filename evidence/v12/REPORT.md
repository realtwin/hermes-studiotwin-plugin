# V12 — Studio palette and control hierarchy (v0.3.1)

Base: `188f09d0857826becce48595d870e011f825bd64`.
Branch: `feat/v12-aaa-studio-palette-and-controls`.

## Critical audit and changes

The v0.3.0 hierarchy gave utility actions the same primary-blue weight as creation actions. Metadata badges repeated that hue, selected filters paired solid accent with a nonexistent foreground token, and elevated modal surfaces inherited the theme tint. Closing was visually mixed with asset actions; the image lightbox put Close before the zoom tools.

1. **Neutral inspection rooms.** Added dedicated achromatic backdrop, dialog, section, stage, chip, button and selected-toggle tokens. Inspector surfaces and shared viewer chrome use relative OKLCH with zero chroma. Model-stage backgrounds/grids, environment/sticker chrome and audio waveform colors also strip hue before Canvas/Three.js consumption; asset textures/images are not desaturated. Neutral native range/checkbox accent inherits from the stage.
2. **Close hierarchy.** The asset inspector has a sticky header, title/icon/metadata grouping, Copy and Download utilities, divider, and dedicated far-right Close + ESC. The image lightbox has a real outside-click scrim, left zoom tools, and an independently reserved right-hand Close + ESC even at a narrow viewport. Exact accessible names remain `Close asset inspection` and `Close inspection`. Escape closes the nested image inspection without closing its parent and returns focus to Inspect image.
3. **Soft palette.** Workspace active filters use 16% accent tint and primary text, with a soft accent border. Workspace tabs use elevated card selection rather than solid accent. Secondary/ghost/button and muted metadata primitives make hierarchy explicit. Inspection toggles are separate from accent filters, avoiding inherited border-color leakage.
4. **Library.** Recessed search, quiet Refresh, refined single-frame cards, neutral modality medallions and translucent HUD micro-labels. Titles are ghost actions without another nested bordered panel.
5. **Jobs.** Quiet filters/pagination/copy/reuse/cancel; secondary Inspect Output, neutral tool badges, retained semantic status colors outside inspection rooms.
6. **Concepts.** Subtle selected-list tint/border; muted metadata; outline version/workflow/pagination controls with existing master-detail behavior.
7. **Workspace and upload.** Settings/Refresh iconography and neutral utility controls; softer upload medallion and file chooser; quiet format chips. The chooser remains a styled native file-input label to preserve keyboard and existing file-input selectors.
8. **Transcript cards and release artifact.** Explicit button variants/small sizing throughout cards and viewers; muted badges including the aliased audio Badge controls. Version is 0.3.1 in plugin.json, dashboard manifest and project-only pyproject.toml. Rebuilt desktop/plugin.js.

## Verification

- `pytest -q`, with the existing v09 test venv, reference host PYTHONPATH and `STUDIOTWIN_BLENDER_TEST=1`: **238 passed**, including Blender. See `pytest.log`.
- `npx vitest run`: **241 passed, 38 skipped**, 19 passing files and 1 skipped file. See `vitest-final.log`. Existing skips were retained, not converted to passes.
- `npm run typecheck`: exit 0.
- `hermes plugins validate` via the reference-host interpreter in a disposable home: **Validation passed**, 27 costed tools, **no spend limit**. See `validate.log`.
- Two consecutive `npm run build:desktop` runs compared byte-for-byte with `cmp`: identical. Final bundle SHA-256: `4a437120cd5658e1b89af33377e555c99a7276fa660cb9e2bbe7a5a78cde2a7f`.
- `git diff --check` and `git diff --exit-code -- package.json package-lock.json`: exit 0.
- Existing workspace theme invariant passes: no hex/rgb literals in workspace inline styles. No transport, billing, redaction, gateway, handle-table or artificial credit-cap changes.

### Regression sensitivity

Three new V12 tests in `tests/workspace/v11-studio.test.ts` failed before implementation: missing explicit SDK hierarchy, solid-accent filter fill, and missing Close/ESC hierarchy. The UI regression uses Chromium loading the actual production bundle, samples computed dialog/button/active zoom colors under deliberately saturated light and dark themes, checks neutral inline descendants and existing selectors, exercises outside click/Escape/focus restoration, and captures desktop/narrow views.

After implementation, `mutation.mjs` temporarily restores the base token module, asset inspector source and production bundle, runs the unchanged V12 tests, requires **all three to fail**, and restores working bytes in `finally`. See `mutation.log`. The restored final code passes all three again (`green.log`). Run that script from the repository root with the environment below; it is a mutation probe, not a build/install script.

The initial full UI pass exposed an optional Codicon export missing in a legacy test-host shim and the old waveform test's explicit accent-read requirement. The new icon now follows the existing optional-export guard convention, and the waveform assertion requires a neutral text-token read instead of accent. One material-toolbar readiness assertion timed out on the first full run while the Python media suite was also running; isolated execution and subsequent complete serial UI runs pass with the original readiness assertion unchanged. The initial Python command exceeded a 180-second timeout; its complete rerun passed in about 260 seconds. No failure was waived or synthesized.

## Reproduction environment

```sh
export PATH="/home/deploy/.hermes/tools/node-26.12.1-linux-x64/bin:/home/deploy/.hermes/tools/ffmpeg-9.0.1-linux-x64/bin:/home/deploy/.local/bin:/home/deploy/work/realtwin/hermes-studiotwin/worktrees/v09/.venv/bin:$PATH"
export WORKSPACE_TEST_PYTHON=/home/deploy/work/realtwin/hermes-studiotwin/worktrees/v09/.venv/bin/python
export PYTHONPATH=/home/deploy/work/realtwin/hermes-studiotwin/reference/hermes-agent
npm run typecheck
npm run build:desktop
npx vitest run
STUDIOTWIN_BLENDER_TEST=1 pytest -q
HERMES_HOME="$PWD/.verification/v12/validate-home" python -m hermes_cli.main plugins validate "$PWD"
node evidence/v12/mutation.mjs
```

## Evidence scope and visual review

`screenshots/` contains the production-bundle fixture gallery across viewers/tabs/light/dark and targeted inspector/image-lightbox/narrow captures. Historical v08 screenshots were restored rather than rewritten by this iteration. Visually inspected the dark asset inspector, light image lightbox, narrow dark lightbox, dark Library and light Jobs: neutral inspection chrome, clear right-hand Close, wrapped left-hand zoom tools, quieter metadata and no nested title-button frames. Asset pixels remain colored.

These are **real Chromium/Three.js/media decoders and the real plugin FastAPI backend against deterministic loopback StudioTwin/storage fixtures**, not a live cloud account or the actual Desktop application. SDK controls are host shims; Codicons are no-ops in that harness (blank medallions in fixture screenshots), so screenshots cannot establish actual host icon rendering. AST tests separately ensure explicit variants/sizes, rather than trusting shim defaults to emulate host primary-blue styling. Retained test warnings include deprecated RGBELoader, pytest-asyncio fixture-loop configuration, and intentionally missing Codicon exports in minimal shims.

No paid requests, daily-profile installation, publication, push, merge or deployment were performed. Implementation completion releases the pre-created independent Salt review `t_f638b666`; it is not release approval.
