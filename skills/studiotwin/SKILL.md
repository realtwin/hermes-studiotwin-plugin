---
name: studiotwin
description: Create and deliver StudioTwin assets, Concepts and motion.
version: 0.2.0
author: RealTwin
license: MIT
---

# StudioTwin

Generate images, Concepts, environments, worlds, materials, meshes, rigs, motion and sound through the bundled **remote** `studiotwin` MCP connection. Most generation spends StudioTwin credits. Local viewers and processing are separate from cloud generation.

## When to use

- Create or iterate a StudioTwin asset or durable Concept; reuse, inspect, download or upload assets.
- Check wallet, jobs or Concept history; inspect a downloaded GLB, render a preview, prepare a new Blender copy or process audio locally.
- Not a speech, full-song or general video-generation toolset. Video and frame-sequence viewers display existing media; they do not imply a video-generation API. Unreal/Blender editor mutations require separately connected editor tools and authorization.

## Prerequisites and discovery

The `hermes-studiotwin` plugin must be enabled in the active profile with `STUDIOTWIN_API_KEY` configured securely. Never ask for a key in chat. `mcp.json` connects directly to `https://api.studiotwin.ai/mcp`, Streamable HTTP, header `x-api-key: ${STUDIOTWIN_API_KEY}`. No local MCP proxy, IPC gateway, redaction service, opaque handle registry or credit-reservation layer is required.

Use Hermes tool search, describe the exact returned tools, then call them. Hermes may sanitize provider hyphens to underscores and add a prefix such as `mcp__studiotwin__`; do not construct a callable identifier from this table. Read the **live schema** immediately before invocation. The captured 45-tool catalog below is orientation, not permission to invent arguments or assume an old function is available.

Verify connection without spending with `studiotwin_get_credit_balance` and, as needed, `studiotwin_list_my_assets` or `studiotwin_list_my_jobs`. The API key identifies the wallet; an organization key's asset library is the key minter's library. Do not assume every organization asset belongs to that identity.

## Procedure and spending

1. Pick the deliverable, destination, source assets, format and smallest chain. A Concept is a durable typed object with history and active-asset state, not merely an image. Prefer ConceptLab tools for consistent references and iterative editing; use one-shot image functions when no Concept lifecycle is needed.
2. Validate inputs and ownership. Cloud tools generally take `vpc::assets/<uuid>` references or data URIs where their schema says so, **not local paths**. Upload local inputs only with user authorization. Resolve existing assets rather than regenerating to change destination.
3. Before a paid job with variable cost, or whenever the user asks about price/balance, call **both** `studiotwin_estimate_cost` (`functionName`, `inputs` containing the exact intended inputs) and `studiotwin_get_credit_balance`. For other paid work, state the live fixed credit cost; estimate/check balance when expensive or uncertain. If estimation is unavailable, disclose unknown cost and stop for authorization rather than inventing a quote.
4. Explain the selected operation, number of variants, costs and dependent stages. Obtain **explicit user approval OR the native `trust: untrusted` approval prompt** before paid submission. Authorization is scoped to that work; extra retries, variants, uploads or downstream stages need their own authorization. A Next button composes a visible chat request, not a paid submit. If approval is denied or unavailable, stop; never bypass it through a script or change trust settings as a workaround.
5. Submit once; preserve the returned job UUID, Concept UUID and asset UUIDs separately. Poll the original `studiotwin_get_job_status` with `jobId` until `COMPLETE` or `FAILED` (also honor cancellation). A transport timeout does not prove failure: inspect `studiotwin_list_my_jobs` and existing status before considering resubmission. Never silently submit a second billed job.
6. Concept image operations return a pending Concept: poll `studiotwin_conceptlab_get_status` with `conceptId`, not the Concept UUID as a job ID. `operation.status` draft/queued/running is in progress; done/failed/cancelled is terminal. `lifecycleStatus: draft` alone does not mean image generation failed or finished. Keep `operation.vpJobId` separately. Get the reconciled Concept to inspect completed/active assets.
7. Download/resolve actual outputs, record lineage when the scoped Desktop backend is available, inspect files, and only then continue dependent steps. A succeeded rig job alone does not establish that a file has a bound skeleton or clips.
8. Deliver on the current surface, report IDs, formats, actual observed metrics, costs/warnings and unresolved work. Do not label a download game-ready, artist-approved or engine-tested without that verification.

The manifest's illustrative `1–100` credit ranges are **not provider maxima**. ConceptLab's captured approximate ranges are not fresh quotes either. There is **no artificial 200-credit cap**, plugin session cap or local reservation mechanism. Hermes handles native approvals; the provider handles billing. Do not copy Meshy's spending policy into StudioTwin.

## Complete captured tool catalog

Source: `tests/fixtures/tools-list-2026-10-30.json`, server version 1.2.4. Required arguments are shown; optional controls and nested constraints must come from live schemas. “Variable” means estimate exact inputs before approval.

### Generation functions

| Exact provider tool | Required inputs | Routing / captured credits |
|---|---|---|
| `text-to-motion-edit` | `animation`, `editMode`, `seed`, `textPrompt`, `timeRange` | Edit existing frame data; 5 |
| `text-to-motion` | `durations`, `seed`, `textPrompts` | Text sequence to motion JSON; variable |
| `text-to-motion-kimodo` | `durations`, `seed`, `textPrompts` | Alternative motion route; variable |
| `text-to-motion-control` | `seed`, `textPrompt`, `trajectory` | Trajectory-guided motion; 5 |
| `motion-stitch-single` | `lhsAnimation`, `rhsAnimation`, `seed` | Stitch existing frame data; 5 |
| `text-to-environment-map` | `prompt`, `seed` | Environment HDR + PNG; 20 |
| `image-to-environment-map` | `prompt`, `referenceImage`, `seed` | Image-guided HDR + PNG; 25 |
| `environment-map-to-world` | `environmentMap`, `quality`, `seed`, `worldType` | World mesh, optional sky; 80 |
| `environment-map-upscale-cpu` | `inputEnvmap` | Panorama upscale; variable |
| `pano-sticker-placement` | `sticker` | Placement parameters, not a finished panorama; 1 |
| `pano-stickers` | `prompt`, `seed` | Composite/generate panorama with `stickers`; variable |
| `text-to-material` | `resolution`, `textPrompt` | Generate PBR maps; variable |
| `texture-to-material` | `referenceTexture` | Decompose source texture into PBR maps; 20 |
| `image-to-material` | `referenceImage`, `resolution`, `textPrompt` | Extract/generate specified material from image; variable |
| `image-to-3d-mesh` | `referenceImage`, `seed` | Simple image-to-mesh; 25 |
| `tripo-image-to-3d-mesh` | `referenceImage` | Model/topology/texture controls; variable |
| `tripo-rig-check` | `sourceModel` | Free GLB riggability check; 0 |
| `blender-auto-rig` | `mesh` | Cloud rig + audit; 15, not the local Blender helper |
| `tripo-auto-rig` | `sourceModel` | Rig GLB/FBX; 45 |
| `tripo-retopology` | `sourceModel`, `topology` | Smart retopology or Basic decimation; variable |
| `text-to-sound-effect` | `prompt` | SFX, optional loop/duration; variable |
| `prompt-to-dart-translation` | `inputPrompt`, `prompt` | Prompt/template translation; 1 |
| `openai-gpt-image-2-v4-fn` | `mode`, `prompt` | One-shot image generate/edit; variable |
| `concept-lab-img-fn` | `conceptType`, `mode`, `prompt` | Typed concept-image guidance, not a durable Concept; variable |

**Image-name drift:** the viewer recognizes both `openai-gpt-image-2-v4-fn` and legacy `openai-gpt-image-1-v1-fn` so old transcripts still render. The legacy identifier is **not** in this captured tool list: discover the live tool and do not call the legacy identifier. The snapshot exposes `openai-gpt-image-2-v4-fn`; do not rename either token or assume they are interchangeable.

### Wallet, jobs and assets

| Exact provider tool | Inputs / behavior |
|---|---|
| `studiotwin_get_job_status` | Required `jobId`; poll existing generation, inspect outputs |
| `studiotwin_estimate_cost` | Required `functionName`; optional `inputs` (always provide exact inputs for a useful quote) |
| `studiotwin_get_credit_balance` | No arguments |
| `studiotwin_list_my_jobs` | Optional `limit`, `offset`; newest first |
| `studiotwin_cancel_job` | Required `jobId`; only own queued/submitted jobs, not running; provider refunds reserved credits |
| `studiotwin_list_my_assets` | Optional `type`: image, image_sequence, 3d_model, animation, audio, video, unknown, jpg, png |
| `studiotwin_upload_asset` | No arguments; creates presigned POST upload session |
| `studiotwin_complete_asset_upload` | Required `uploadSessionId`; tar uploads also require ordered `entries` with `name`, `offset`, `size` |
| `studiotwin_resolve_asset` | Required `assetId`; metadata + refreshed presigned download URL |

Upload sequence: create session → multipart POST directly to the returned URL with **every** returned form field and file → complete session → use returned asset UUIDs. A session UUID is not the completed asset UUID. Keep POST policy/signature fields out of chat and logs. Desktop's upload drawer/backend can perform this sequence without exposing them.

### ConceptLab

| Exact provider tool | Required inputs / behavior |
|---|---|
| `studiotwin_conceptlab_create` | `conceptType`, `name`; empty draft, no media or credits; optional `metadata` |
| `studiotwin_conceptlab_create_and_generate` | `conceptType`, `name`, `jobInputs`; draft + one paid image, variable |
| `studiotwin_conceptlab_list` | Optional `limit` (1–100, default 20), `offset`; `{concepts: [...]}`, no total |
| `studiotwin_conceptlab_get` | `conceptId`; reconciles operations, returns Concept |
| `studiotwin_conceptlab_get_status` | `conceptId`; reconciles and reports latest operation |
| `studiotwin_conceptlab_attach_asset` | `conceptId`, `assetId`; idle draft, optional `makeActive` defaults false |
| `studiotwin_conceptlab_generate` | `conceptId`, `jobInputs`; one paid image on idle draft, variable |
| `studiotwin_conceptlab_edit` | `conceptId`, `jobInputs`; paid edit of active completed image on idle draft, variable |
| `studiotwin_conceptlab_clone` | `conceptId`; new draft with same type/name and active asset, not full history/metadata |
| `studiotwin_conceptlab_set_active_asset` | `conceptId`, `assetId`; select completed asset already attached to idle draft |
| `studiotwin_conceptlab_update` | `conceptId`; optional `name`, `metadata`; metadata **replaces** whole object |
| `studiotwin_conceptlab_delete` | `conceptId`; permanent deletion of Concept and unreferenced generated assets; uploaded assets/job history retained; confirm explicitly |

`conceptType` is `object`, `character`, `environmentMap` or `world`. ConceptLab `jobInputs` requires `modelId: "openai/gpt-image-2"` and `prompt: {"user":"...","enhancement":{"enabled":true}}`. Optional `params.quality` is low/medium/high; `params.resolution` is a live-schema resolution preset. Generate/create-and-generate may use owned `sourceAsset` (UUID or `vpc::assets/<uuid>`). Edit uses the active image automatically and does **not** take that field. Persisted Concept type cannot be overridden in params. Captured default image cost is about 6 credits; source image adds 2; edit about 8. Estimate, do not treat these as billing guarantees. Read back each Concept mutation to verify actual active state/history.

## Routing details and compatibility

- **Image → model → rig → motion:** approve image first, reuse its asset reference, choose simple mesh or Tripo based on topology/texture needs. Tripo modelVersion choices in the snapshot are P1-20260311, P2-20260801 and v3.1-20260211; option compatibility varies. P2/v3.1 support quad output; v3.1 parts require texture/PBR off and conflict with quads. Leave export orientation unset if later Tripo post-processing is planned. Retopologize **before** rigging where possible.
- **Retopology:** `topology` is triangles/quads, `mode` smart/basic. Basic requires `faceLimit` and rejects `bakeTextures`; Smart has different face limits and baking support. These are not the local helper's Decimate operation. Use live limits.
- **Rig:** free `tripo-rig-check` accepts GLB only, maximum 150 MB. `tripo-auto-rig` accepts GLB or FBX; FBX maximum 20 MB and requires `skipRigCheck: true` with consciously chosen `rigType`. GLB not riggable may produce metadata without `mesh`; report that rather than claiming a rig exists.
- **Motion:** `animation`/lhs/rhs values are frame objects, not a mesh URL; frames require `keypoints3D`, with optional quaternions/smplPoses/rootTranslation. Trajectory requires waypoints. Do not promise a rigged GLB from JSON motion output or imply automatic retargeting into a character. Verify the chosen destination's import/retarget route separately.
- **Environment chain:** text/image map → optional upscale → optional world. Keep HDR/EXR for lighting and PNG for preview. World mesh is not a complete authored engine level.
- **Pano stickers:** `pano-sticker-placement` returns `yawDeg`, `pitchDeg`, `rollDeg`, `hFovDeg`, `vFovDeg`, `sourceAspect`. The next generation is `pano-stickers`; pass the supported camelCase fields unchanged in `stickers[]` (`assetId`, `pitchDeg`, `yawDeg`, `hFovDeg`, optional `rollDeg`). Do not snake_case them. The snapshot's strict sticker item schema does not list `sourceAspect` despite the placement description suggesting it: forward it only if the **live** item schema permits it; otherwise disclose the mismatch. `vFovDeg` is informational, not a listed sticker input.
- **Materials:** texture-to-material decomposes the source; image-to-material needs a prompt specifying which surface to extract. Optional maps can be absent. Service output uses `normals`, while the Desktop material directive expects channel `normal`; map it deliberately after downloading/resolving. Never fabricate missing channels.
- **Images:** generate/edit mode is required; edits require a source. One-shot functions support `n` 1–4, source/mask constraints and size/quality controls. ConceptLab durable image operations queue one image. Transparent background is not supported by the captured GPT Image 2.5 route despite its input enum; inspect warnings. Report actual `size`/`sizeSnapped`, not just request.
- **Sound:** `prompt` at most 450 characters; `duration` 0.5–30 seconds, optional; `loop`, `modelId`, `outputFormat`, `promptInfluence` are camelCase API arguments. Do not copy the sibling plugin's `duration_seconds` or `prompt_influence` API names. Default `pcm_48000` is delivered as stereo WAV. Describe source + action + space, keep one sound per request, repeat style for an authorized variation set. WAV suits engine one-shots/video; OGG/WAV for loops; MP3 for chat audition. Measure actual duration and seam before calling it seamless.

## Long jobs: arm a real chat wake

On **Telegram, Discord, Slack and WhatsApp**, long mesh, rig, `pano-stickers` and world jobs must not strand a user after “started.” After submission, start a bounded **terminal background poller with `background=True, notify=True`**, preserve its session handle, then end the turn. It must poll `studiotwin_get_job_status` for the original `jobId`, print the terminal result and **exit 0 on completion** so Hermes wakes the originating session. On wake, verify status, download and deliver. Exit nonzero on failure/cancellation/deadline so the wake reports a problem, not success. Do not use a blind sleeping timer as a substitute for polling.

A shell cannot invoke a model-only tool by name. There is **no bundled `studiotwin` CLI or poller executable**. Use a host-aware adapter: first confirm terminal runs on the Hermes host, locate the installed plugin directory, verify the host's Python has `httpx`/`fastapi` and the active-profile secret resolver, then execute the following Python via an inline stdin script in the terminal background command. Replace the plugin path and job UUID with discovered values; do not put the key into argv, source or output. This adapter uses the shipped direct MCP client, not a local server and not a paid submit:

```python
import importlib.util, json, sys, time
from pathlib import Path
from agent.secret_scope import get_secret

plugin_dir = Path(sys.argv[1]).resolve()  # actual installed plugin directory
job_id = sys.argv[2]                    # actual returned job UUID
spec = importlib.util.spec_from_file_location(
    "studiotwin_poll_client", plugin_dir / "dashboard/studiotwin_client.py")
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)
key = get_secret("STUDIOTWIN_API_KEY")
if not key:
    raise SystemExit("StudioTwin key unavailable in this host/profile")
deadline = time.monotonic() + 7200
with module.StudioTwinClient("https://api.studiotwin.ai", key) as client:
    while time.monotonic() < deadline:
        row = client.call("studiotwin_get_job_status", {"jobId": job_id})
        state = str(row.get("status", "")).lower()
        if state in {"complete", "completed", "done", "succeeded"}:
            print(json.dumps({"jobId": job_id, "result": row}), flush=True)
            raise SystemExit(0)
        if state in {"failed", "cancelled", "canceled"}:
            print(json.dumps({"jobId": job_id, "status": state}), flush=True)
            raise SystemExit(1)
        time.sleep(30)
raise SystemExit("StudioTwin polling deadline reached; job may still be running")
```

For example, the terminal command is `python3 - /absolute/installed/plugin JOB_UUID` followed by the Python above through stdin (a shell heredoc is one way). Pass that **complete command string** to `terminal(command=..., background=True, notify=True)`; those are tool arguments, not shell flags. Keep the same `HERMES_HOME`/profile environment and use the host interpreter, not an unrelated container. Verify startup/import/secret resolution before claiming the wake is armed; check the returned handle for immediate failure. A read-only status probe is sufficient; do not test by creating a paid job. If host secret resolution or terminal notification is unavailable, say automatic delivery is not armed, keep polling inline if feasible, or give the ID/link and ask the user to check back. Never promise future delivery without an armed wake. Concept operations use a separate adapter polling `studiotwin_conceptlab_get_status` by `conceptId` and inspecting `operation.status` if background handling is needed.

Desktop progress cards can poll visually, but they do not wake the agent or execute dependent paid steps. In CLI/TUI, poll inline or use a verified notification-capable background process as appropriate.

## Delivery by surface and Desktop directives

Presigned **download URLs** and `s3://` URIs are ordinary delivery links/asset locations. Never redact them merely for being signed; they may appear in chat, logs, reports and visible commands. They may expire (many captured outputs say one hour); resolve the asset again to refresh rather than regenerate. Never expose `st_...` API keys, account credentials or presigned **POST** upload policies/signatures.

- **Desktop:** enable the Desktop half; workspace is `/studiotwin` with Library, Jobs, Concepts and Upload. Use a directive on its own line for a source the backend can actually serve, or an attributed `MEDIA:` file for automatic tool-media cards. Viewers do not themselves prove the agent visually reviewed an asset.
- **Messaging:** download to an absolute path accessible to the gateway, preferably beneath active `<HERMES_HOME>/cache/generated/`. Deliver each attachment once as a standalone `MEDIA:/absolute/path.ext` line. No Desktop directives or markdown images. Include a download link when file-size limits prevent attachment. Report link expiry from actual metadata, not Meshy's three-day policy. A local path in prose is not an attachment.
- **CLI/TUI:** report absolute paths, format, job/asset IDs and useful download links; `MEDIA:` and directives may display as literal text.
- **Remote Desktop:** backend paths belong to the Hermes machine, not necessarily the user's computer. Playback/download streams through scoped backend access. Local processing requires the files and tools on that host.

Directive attributes below come from `src/cards/`, not remote MCP schemas. Substitute real IDs/paths; placeholders are not executable UUIDs. Do not attach a `task` attribute where the renderer expects `id`.
Never put `{` or `}` inside any `::studiotwin-*` directive attribute value: Desktop's parser permits only `[^{}]{0,1024}` inside the outer attribute block. Use flat material channel attributes, not nested JSON. Legacy JSON `maps` remains supported programmatically/tool-media, but cannot pass that transcript parser. Only pass environment stickers when needed, preferably through tool-media; sticker object JSON and object-based video frame sequences cannot pass this directive parser. Use ordinary video `path` or tool-media for those sequences.

| Directive | Actual attributes |
|---|---|
| `studiotwin-model` | Exactly one `path` or `asset`; optional `name`, `title`, `audit` (local audit JSON path or audit asset UUID). No remote `url` input. |
| `studiotwin-audio` | Exactly one `path` or `asset`; optional `prompt`. |
| `studiotwin-env` | Exactly one `path` or `asset`; optional `name`. Prefer tool-media for sticker objects. |
| `studiotwin-material` | Flat `albedo` required; `normal`, `roughness`, `metalness`, `heightmap` optional. Each value is a local path or asset UUID; aliases `normals`, `metallic`, `height` accepted. Optional `name`/`title`, `zip`. Brace-free `maps="albedo=/a.png,normal=/n.png"` also supported. |
| `studiotwin-image` | Exactly one `path`, `asset` or `url`; optional `before` (HTTP URL or asset UUID, not local path), `title`. |
| `studiotwin-video` | Exactly one `path`, `asset` or `url`, OR JSON-string `frames` array of objects each with exactly one such source; optional numeric `fps`. |
| `studiotwin-task` | Required `id` (job UUID); optional `kind="concept"` selects Concept polling. |
| `studiotwin-job` | Required `id` (job UUID); optional `kind="concept"`. |
| `studiotwin-concept` | Required `id` (Concept UUID); Concept polling. |

```text
::studiotwin-model{path="/absolute/model.glb" audit="/absolute/rig-audit.json" title="Approved character"}
::studiotwin-audio{asset="<asset-uuid>" prompt="Rain ambience"}
::studiotwin-env{path="/absolute/environment.hdr"}
::studiotwin-material{albedo="/absolute/albedo.png" normal="/absolute/normals.png" roughness="/absolute/roughness.png" metalness="/absolute/metalness.png" heightmap="/absolute/heightmap.png"}
::studiotwin-image{asset="<asset-uuid>" before="<source-asset-uuid>" title="Iteration"}
::studiotwin-video{path="/absolute/preview.mp4"}

::studiotwin-task{id="<job-uuid>"}
::studiotwin-job{id="<job-uuid>"}
::studiotwin-concept{id="<concept-uuid>"}
```

Environment sticker JSON uses `assetId`, numeric `yawDeg`, `pitchDeg`, `rollDeg`, `hFovDeg`, optional positive `sourceAspect`. Its overlay shows a placement boundary, not proof the provider composited the image. For material/env/model sources, resolve cloud URIs to asset UUIDs or download locally; those cards do not take arbitrary `s3://` paths. Image/video URL acceptance in the directive does not guarantee backend/network support: download or resolve an asset when necessary.

For a provider rig verdict, preserve the separate `blender-auto-rig` `audit` output (or `tripo-auto-rig` audit when supplied), save that JSON locally on the backend or resolve its asset UUID, then pass it as `audit=` alongside the mesh. The JSON must contain boolean `riggable`, nonnegative integer `joints`, and a string-array `warnings`. A valid audit alone supplies “Rig audit: passed / needs attention”; warnings remain visible. Missing audit sources produce no badge; supplied but malformed/unloadable data shows an unavailable notice without breaking the preview. “Rig inspection (local)” reports only parsed model joints, skinned meshes and clips, never a provider verdict.

Tool-media cards read the producing tool's result, including Hermes's `{result: ...}` / `structuredContent` envelope; they do not receive a filename-to-output-field mapping for sibling attachments. A local/asset `audit` reference is loaded through the bound-scope `/file` route. An HTTPS-only audit says “provided separately” and is not fetched by the renderer. MCP resource links remain links (not automatically downloaded), and binary embedded resources produce a saved-resource notice rather than rewriting `audit` to a local path. Thus downloading files in a separate tool does not automatically attach the provider audit to a model card: use the explicit directive with the saved audit reference.

## Made from provenance

Remote tool results do not automatically establish local lineage. Record "Made from" through `POST /provenance`. When a **scoped, authenticated Desktop backend** is available, use `ctx.rest('/provenance', {method:'POST', body: record})` in the host's supported request context. The full host-mounted route is `/api/plugins/hermes-studiotwin/provenance`; `/provenance` is the plugin-scoped suffix, **not a public StudioTwin API route**. An agent must use an available authenticated host adapter; do not invent a REST tool, global token or unscoped localhost request.

Exact accepted POST fields:

```json
{
  "id": "<job-or-asset-uuid>",
  "jobId": "<job-uuid>",
  "conceptId": "<concept-uuid>",
  "sourceAssetIds": ["<source-asset-uuid>"],
  "outputAssetIds": ["<output-asset-uuid>"],
  "prompt": "User's actual prompt",
  "tool": "exact-provider-tool-name",
  "session_id": "actual-originating-session-id"
}
```

Only the identifier is required: `id` is preferred; `jobId` or `task_id` can supply it if `id` is absent. `task_id` is an identifier alias, not stored metadata. `sourceAssetIds` and `outputAssetIds` are arrays of up to 100 UUIDs, deduplicated by the backend; `conceptId` and `jobId` must be UUIDs; `prompt`, `tool`, `session_id` must be strings at most 8000 characters. Omit unknown optional values; never send placeholder IDs or invented settings/cost fields. Submission can record sources; completion updates the same identifier with outputs (partial writes merge). Read back `GET /provenance?id=<uuid>` (alias `/details?id=<uuid>`) to verify `record`, parents/children and `made_from`. Link output IDs so asset views can find job lineage. Without a scoped backend, report lineage in chat and disclose it was not persisted locally.

## Local scripts (no StudioTwin credits)

Use the actual installed skill directory, not the shell's current directory. Examples below run from the **plugin root**; replace `/absolute/...` inputs and choose new output destinations. All processing runs on the terminal host. Check dependencies there first. Do not install dependencies or overwrite outputs without authorization.

### Inspect GLB

```sh
python3 skills/studiotwin/scripts/glb_stats.py /absolute/model.glb /absolute/rigged.glb
```

Standard library only, one JSON line per file. Report actual `triangles`, `bytes`, `skinned_mesh_nodes` and named `clips`. Skin/joint definitions alone are not a bound rig. A file error is not a successful inspection.

### Render MP4 preview

```sh
node skills/studiotwin/scripts/render_preview.mjs /absolute/model.glb --list-clips
node skills/studiotwin/scripts/render_preview.mjs /absolute/model.glb --out /absolute/preview.mp4 --seconds 6 --fps 30 --size 720 --label "Character" --max-mb 8
node skills/studiotwin/scripts/render_preview.mjs /absolute/rigged.glb --clip "Walk" --out /absolute/walk.mp4 --no-label
```

This renders a **turntable or animation MP4**, not a contact sheet. Node 22+ for the script (package development requires 24+), Chromium/Chrome and ffmpeg; ffprobe adds verification metadata. `--chrome PATH` overrides browser discovery. It uses three 0.180.0 from package dependencies or downloads the integrity-checked npm tarball into `<HERMES_HOME>/cache/studiotwin-preview/` on first use; extraction needs `tar`. Default output is a uniquely named MP4 under `cache/generated/videos/`; existing explicit outputs are refused. Read the JSON `ok`, `bytes`, `clip`, `probe`, and `blocked_urls`; embedded external resource URLs are not fetched. Rendering spawns headless Chromium and ffmpeg, not a persistent service.

### Multiview reference sheets and Forge-E style reskinning
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

## Verification and troubleshooting

- Missing tools: verify installed/enabled agent half and active profile, start a new session, discover tools again. Do not add a duplicate `mcp_servers.studiotwin` entry that replaces the bundle by accident.
- Authentication failure: configure the key in the active profile's secret settings, not browser JS or a chat. Insufficient credits (`40001`): check balance and obtain user-directed funding/changed scope; never retry paid submission automatically.
- Expired download: resolve the existing asset again. Missing file on terminal: check remote-host mismatch before installing or copying anything.
- Blank card: verify Desktop half, actual directive attributes, origin profile/connection and supported format. Settings refresh from scoped `/status` on the settings-changed event. `inline_cards=false` restores tool-media fallback and plain directive text, not workspace/navigation/chrome. `webgl_limit` (1–4, default 4) constrains inline model/environment/material and workspace viewers. `auto_rotate` (default true) initializes model viewers, with a local manual override. `gallery_limit` (1–100, default 24) controls recent Concepts/Jobs pages, resetting offset on change, not complete-library 100-row paging or all-page active-job counts. Missing/malformed values use manifest defaults. Reopen off-screen cards if contexts are constrained. Keep an ordinary link/file fallback.
- Verify cancellation by reading original job status; a running job may no longer be cancellable. Deletion and metadata replacement require explicit scope confirmation and readback.
- Final delivery: actual successful output exists and is nonempty; every stated metric was measured; all IDs are labeled correctly; costs/partial success are disclosed; promised chat wake is armed; every named attachment appears exactly once.
