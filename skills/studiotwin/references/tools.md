# StudioTwin reference: tools

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
