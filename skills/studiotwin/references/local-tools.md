# StudioTwin reference: local-tools

## Local scripts (no StudioTwin credits)

Use the actual installed skill directory, not the shell's current directory. Examples below run from the **plugin root**; replace `/absolute/...` inputs and choose new output destinations. All processing runs on the terminal host. Check dependencies there first. Do not install dependencies or overwrite outputs without authorization.

### Inspect GLB

```sh
python3 skills/studiotwin/scripts/glb_stats.py /absolute/model.glb /absolute/rigged.glb
```

Standard library only, one JSON line per file. Report actual `triangles`, `bytes`, `skinned_mesh_nodes` and named `clips`. Skin/joint definitions alone are not a bound rig. A file error is not a successful inspection.

### Render MP4 preview

**Execution boundary:** this helper launches Chromium with `--no-sandbox` and `--enable-unsafe-swiftshader`: no Chromium sandbox, unsafe software rendering. Resource refusal and verified dependencies do not isolate renderer/decoder processes. Use trusted inputs, or a separately isolated processing environment for untrusted assets.

```sh
node skills/studiotwin/scripts/render_preview.mjs /absolute/model.glb --list-clips
node skills/studiotwin/scripts/render_preview.mjs /absolute/model.glb --out /absolute/preview.mp4 --seconds 6 --fps 30 --size 720 --label "Character" --max-mb 8
node skills/studiotwin/scripts/render_preview.mjs /absolute/rigged.glb --clip "Walk" --out /absolute/walk.mp4 --no-label
```

This renders a **turntable or animation MP4**, not a contact sheet. Node 22+ for the script (package development requires 24+), Chromium/Chrome and ffmpeg; ffprobe adds verification metadata. `--chrome PATH` overrides browser discovery. It uses three 0.180.0 from package dependencies or downloads the integrity-checked npm tarball into `<HERMES_HOME>/cache/studiotwin-preview/` on first use; extraction needs `tar`. Default output is a uniquely named MP4 under `cache/generated/videos/`; existing explicit outputs are refused. Read the JSON `ok`, `bytes`, `clip`, `probe`, and `blocked_urls`; embedded external resource URLs are not fetched. Rendering spawns headless Chromium and ffmpeg, not a persistent service.

### Multiview reference sheets and Forge-E style reskinning
**Execution boundary:** this helper also launches Chromium with `--no-sandbox` and `--enable-unsafe-swiftshader`. Use trusted inputs or a separately isolated environment for untrusted assets; external-resource refusal and the debugging pipe are not a sandbox.
Use `--yaw-offset <degrees>` (finite number, default `0`) to align FRONT with the model's authored forward axis: `0` for +Z, `90` for +X, `180` for -Z, `-90` for -X. The offset is added to every canonical yaw, including 3/4 and top; pitch stays unchanged. JSON stdout records `yaw_offset_deg`. Desktop exposes the same four orientations in the Multiview yaw offset selector before Capture Multiview. For example, add `--yaw-offset 180` for a model facing -Z.

```sh
node skills/studiotwin/scripts/render_multiview.mjs /absolute/model.glb --out /absolute/multiview-sheet.png --split-dir /absolute/views --views 6 --shading clay --tile-size 512
node skills/studiotwin/scripts/render_multiview.mjs /absolute/model.glb --out /absolute/normals.png --views 4 --shading normals --transparent --no-labels --chrome /absolute/chrome
```

Node 22+, Chrome/Chromium and three 0.180.0; no ffmpeg or Blender required. The helper shares the preview's verified Three.js discovery, integrity-checked first-run npm download and anonymous Chromium debugging pipe. It renders offline on `about:blank` with blob-imported modules and SwiftShader, refuses external GLB resources, and exits the browser after rendering. No local server or TCP IPC is created. Keep `render_harness.mjs` beside both render scripts when copying them.

Options: `--views 4|6` (default 4), `--shading textured|clay|normals|wireframe` (default textured), `--tile-size` (integer 64–2048, default 512), `--transparent`, `--no-labels`, `--split-dir`, `--out`, `--chrome`. Default output is `<model-stem>-multiview.png` beside the source; explicit or default existing outputs and existing split tiles are refused, never overwritten. The rest pose is frozen and centered, with a bounding-sphere fit. Four views are front/right/back/left at yaw 0/90/180/270°, pitch 12°; six add 3/4 at yaw 35°, pitch 22° and top at yaw 0°, pitch 85°. Tiles are ordered row-major in a 2×2 or 3×2 sheet; split files are `front.png`, `right.png`, `back.png`, `left.png`, `three_quarter.png`, `top.png` as applicable. Read the single JSON stdout line: `ok`, absolute `sheet`, ordered `views`, `split_files`, `shading`, `width`, `height`, `bytes`. A four-view 512px render is 1024×1024; six-view is 1536×1024.

In Desktop, load a model, choose 4/6 Views and the reference pass (Clay by default), then Capture Multiview. The live stage captures its current pose without advancing animation and restores the camera, shading, grid, background and auto-rotate state. It offers a labeled contact sheet preview, per-view badges and Download Sheet. It stages the sheet on the originating Hermes backend through `POST /upload` with `cloud:false`, filename `<stem>-multiview-<views>v-<shading>.png`. After staging, `POST /provenance` records a local UUID record with the sheet/source paths in the Made from prompt and source asset UUID when known. This local record is not a cloud asset or a claim of automatic cloud lineage; local-file links are textual, not cloud asset IDs. Staging/provenance failures leave Reskin disabled and do not start generation.

Reskin 3D in Chat sends a visible request to the originating chat, not a paid job. Use it as a Forge-E style 3D-to-3D reference workflow:

1. Inspect the saved sheet as pixels, ask for the intended style change and preserve silhouettes, view labels/layout and camera angles. A displayed viewer is not agent observation.
2. Discover the live ConceptLab or `openai-gpt-image-2-v4-fn` edit schema; obtain approval before uploading local references. Estimate exact credits and obtain approval before the image edit. Use a durable Concept when iteration/history is wanted.
3. Review the edited reference before discovering `image-to-3d-mesh` or `tripo-image-to-3d-mesh`. Choose a schema-compatible image or split view; do not assume a contact sheet is a supported multiview input. Estimate and approve this separate paid reconstruction stage.
4. Inspect the returned mesh and keep the source unchanged. Image-to-3D reconstruction does not guarantee exact geometry, topology, rig or animation preservation. Do not describe this as an in-place material-only reskin.

The model inspector offers Environment IBL when panorama assets are present; model components also accept an `envSource`. HDR/EXR and equirectangular PNG/JPG light the model through the same environment loader as the panorama viewer. Show environment background is optional; Studio lighting clears the environment. This changes local preview lighting, not the source asset or provider output.

### New Blender copy

```sh
blender --background --factory-startup --python skills/studiotwin/scripts/blender_handoff.py -- --probe
blender --background --factory-startup --python skills/studiotwin/scripts/blender_handoff.py -- --input /absolute/model.glb --out-dir /absolute/handoff --export both --name character
blender --background --factory-startup --python skills/studiotwin/scripts/blender_handoff.py -- --input /absolute/prop.glb --out-dir /absolute/prop-handoff --tris 3000 --lods 0.5,0.25,0.1 --max-texture 2048 --export glb
blender --background --factory-startup --python skills/studiotwin/scripts/blender_handoff.py -- --render /absolute/model.glb --png /absolute/model.png
```

Blender 4.2+. First honor `plugins.entries.hermes-studiotwin.settings.blender_handoff` (ask/always/never, default ask) and `blender_path` (empty: PATH). Use the configured executable in place of `blender`. Never change a live scene: handoff runs a fresh factory-startup process, creates a new `_optimized.blend` and exports, then fresh-process verifies by default. A triangle budget is **user-approved**; decimation is not quad retopology. Do not pass `--allow-skinned`, `--allow-shape-keys`, `--allow-loss`, `--no-verify` or `--force` without explaining the risk and receiving authorization. Read `HANDOFF_RESULT`, `verify`, `lost`, `preserved`, warnings and exit code. Downloaded, import-validated, visually reviewed and engine-tested are different states. A loss can return failure after files were written; disclose existing outputs rather than resubmit.

### Process sound

```sh
python3 skills/studiotwin/scripts/sfx_tool.py probe /absolute/sound.wav
python3 skills/studiotwin/scripts/sfx_tool.py process /absolute/hit.wav --out /absolute/hit-mono.ogg --mono --trim --loudness -18 --fade-ms 10
python3 skills/studiotwin/scripts/sfx_tool.py process /absolute/loop.wav --out /absolute/loop.ogg
python3 skills/studiotwin/scripts/sfx_tool.py loopcheck /absolute/loop.ogg
python3 skills/studiotwin/scripts/sfx_tool.py loopfix /absolute/loop.wav --out /absolute/fixed.wav --crossfade-ms 20
python3 skills/studiotwin/scripts/sfx_tool.py pack /absolute/take1.wav /absolute/take2.wav --name "Gravel Footsteps" --out-dir /absolute/packs --format ogg --variations
```

Python stdlib plus ffmpeg/ffprobe. Global `--ffmpeg`/`--ffprobe` overrides precede the subcommand. Process output extension chooses WAV/OGG/MP3/Opus/FLAC; pack `--format` supports wav/ogg/mp3/flac. Parent output directories must exist; existing outputs need explicit `--force`. Every operation returns one JSON line with `ok` or an error `code` (`ffmpeg_missing`, `bad_input`, `bad_args`, `ffmpeg_failed`, `interrupted`, `internal`). Never trim or fade a loop; plain conversion preserves edges. Crossfade shortens the loop and may dip: re-run loopcheck on the **delivered** file, report verdict/dip note and actual duration. Normalization reports measured loudness/true peak, not guaranteed target attainment. Packs create folder, `manifest.json` and zip; variation sets report measured loudness spread. No additional generation is implied by processing.
