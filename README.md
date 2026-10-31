# StudioTwin for Hermes Agent

Create and inspect images, environments, PBR materials, 3D meshes, rigs, character motion and sound effects with [StudioTwin](https://studiotwin.ai), from Hermes Agent or Hermes Desktop. Keep creative iterations together as durable ConceptLab Concepts, then reuse the resulting assets across projects.

A RealTwin plugin for Hermes, **not a Nous Research official plugin**. This portable [Agent Plugins v1](https://agent-plugins.org) package ships:

| Part | Purpose |
|---|---|
| `mcp.json` | Direct Streamable HTTP connection to StudioTwin's hosted MCP server; no local MCP process |
| `plugin.json` | Hermes native approval/cost declarations and profile-scoped configuration |
| `skills/studiotwin/` | Workflow skill with the complete captured tool catalog, routing, spending, delivery and local script instructions |
| `desktop/plugin.js` | Desktop workspace, media viewers, progress cards and status chips |
| `dashboard/plugin_api.py` | Host-authenticated Desktop backend for assets, jobs, uploads, media streaming and local provenance |

Try: “Make a character Concept and show me the image before creating the mesh,” “Turn this panorama into a world,” “Extract a tileable brass material from this image,” or “Make a rain loop for my game; estimate the credits first.” Generation is paid; inspecting existing assets and local post-processing do not create paid generations.

## Requirements

- Hermes Agent with Agent Plugins v1, remote Streamable HTTP MCP and native MCP approval/cost support. Hermes Desktop is optional and needs transcript directives/tool-media renderers for the full UI. This manifest does not declare a numeric minimum Hermes version; verify your host rather than inferring compatibility from installation alone.
- StudioTwin account, API key and enough wallet credits for requested generation. No separate OpenAI, Tripo or ElevenLabs key is required by this plugin.
- Network access to `api.studiotwin.ai` and returned StudioTwin/Amazon S3 storage endpoints for cloud operations and delivery.
- Python 3.11+ for the backend/helpers; backend dependency `httpx>=0.27,<1` plus the host's FastAPI environment. Let Hermes manage plugin dependencies.
- Optional: Blender 4.2+ for local handoff; ffmpeg/ffprobe for audio processing/conversion and preview encoding; Chromium/Chrome plus Node.js for headless GLB MP4 previews. Package development requires Node.js 24+ and npm. The preview helper itself requires Node.js 22+.

## Install and setup

```sh
hermes plugins install realtwin/hermes-studiotwin
hermes plugins enable hermes-studiotwin
hermes plugins show hermes-studiotwin
```

Installation is per profile; select the intended profile first, for example `hermes -p <profile> plugins install realtwin/hermes-studiotwin`. Review the installer prompts, including dependency preparation. Installation does not prove a successful MCP connection or a loaded Desktop half.

To install a reviewed revision rather than the default branch, use `hermes plugins install realtwin/hermes-studiotwin --ref <full-40-character-commit-sha>` (replace the placeholder with the actual reviewed commit).

Create an API key in your StudioTwin account. In Hermes Desktop, open **Capabilities → Plugins**, find **hermes-studiotwin**, open its settings and enter **StudioTwin API key**. Keep the key out of chat. Without Desktop, use the active profile's secret configuration (`hermes config set STUDIOTWIN_API_KEY <your-key>`, executed privately), or its `.env`:

```dotenv
STUDIOTWIN_API_KEY=<your-key>
```

The example is a placeholder, not a key to copy. Secrets belong to the active profile's `.env`/secret store, never `config.yaml` or the renderer. Shell commands can enter shell history; the Desktop secret field is preferable. Do not paste real credentials into bug reports.

Start a new Hermes session and ask it to discover StudioTwin tools and call **`studiotwin_get_credit_balance`**. A real balance response verifies authentication without a paid generation. Optionally list existing assets/jobs. Enable the plugin's **Desktop** half in Capabilities → Plugins, then open **StudioTwin** from the sidebar/palette; the workspace route is **`/studiotwin`**. Desktop UI is opt-in and separate from the agent half. A remote connection also needs the Desktop UI available on the client and the enabled backend on the Hermes host.

There is no need to add a second MCP server manually. The bundled declaration connects directly to:

```json
{
  "type": "streamable-http",
  "url": "https://api.studiotwin.ai/mcp",
  "headers": {"x-api-key": "${STUDIOTWIN_API_KEY}"}
}
```

A manually configured `mcp_servers.studiotwin` can override the bundled connection. Avoid accidental duplication/replacement. `api_base_url` changes the **Desktop backend** endpoint, not this agent MCP declaration.

## Capabilities

| Modality / workflow | Cloud capabilities | Desktop / local delivery |
|---|---|---|
| Images | One-shot generate/edit; typed concept-image guidance | Image preview, before/after comparison |
| Concepts | Draft, create-and-generate, generate, edit, attach/select active asset, clone, rename/replace metadata, list/status/delete | Concepts tab, history/version strip and active-asset indication |
| Meshes | Simple or Tripo image-to-3D, retopology/decimation | GLB/FBX/OBJ inspection, orbit/pan/zoom, textured/clay/normals/wireframe modes, grid and measured geometry stats |
| Rigs / animation | Blender cloud auto-rig, Tripo riggability check and auto-rig; motion generation/edit/control/stitch | Skeleton/clip inspection, clip selection and playback/scrubbing; local Blender handoff and GLB preview MP4 |
| Environments / worlds | Text/image environment maps, upscale, sticker placement/compositing, environment-to-world | 360° HDR/EXR/PNG panorama viewer, exposure control and sticker placement boundaries; world mesh preview |
| Materials | Text-to-PBR, image-guided extraction, texture decomposition | Sphere/cube/rounded-plane inspection, map channel views and map/zip download; absent optional maps stay unavailable |
| Audio | Sound effects, optional duration and loops | Waveform/seek/play/pause/loop audition, original download and ffmpeg conversion; local trim/mono/loudness/loop checks/packs |
| Video / frame sequences | Browse/upload existing assets; not a video-generation promise | Range-enabled video playback/scrubbing and explicit frame-sequence playback |
| Account / jobs / assets | Estimate/balance, status/list/cancel, upload/complete/resolve/library | Library, Jobs, Concepts and Upload workspace, credit/active-job chips, local “Made from” lineage |

**Next** actions submit a visible request to the originating chat for review/approval; they do not bypass the agent and start paid jobs from a card. A preview is not proof of target-engine compatibility, successful retargeting or artist approval.

### Tools and schema drift

The bundled [workflow skill](skills/studiotwin/SKILL.md#complete-captured-tool-catalog) lists **all 45 exact provider tool names** from the [captured tools/list](tests/fixtures/tools-list-2026-10-30.json), including ConceptLab. The live server can change independently of this package; discover and read its schemas before invoking. Hermes prefixes/sanitizes callable names; search results, not guessed prefixes, are authoritative.

Image routing has an intentional warning: legacy viewer code names `openai-gpt-image-1-v1-fn`, while the captured server exposes `openai-gpt-image-2-v4-fn` plus `concept-lab-img-fn`. Do not call the old identifier merely because a renderer recognizes it. `pano-sticker-placement` chooses placement parameters; the separate `pano-stickers` function composites the panorama with camelCase sticker inputs. See the skill for the captured `sourceAspect` schema discrepancy and safe pass-through policy.

## Credits and approval

Paid tools run through the **direct remote MCP server**. The manifest marks it `trust: untrusted`, sets a 1,500-second call timeout and declares credits for Hermes's native cost-aware approval UI. There is **no plugin session spend cap, no artificial 200-credit cap and no local credit reservation ledger**. Illustrative manifest ranges such as 1–100 credits are not provider maximum prices.

Before input-dependent paid work, or when you ask about cost, the skill requires `studiotwin_estimate_cost` with exact intended inputs and `studiotwin_get_credit_balance`. It states the operation, variants/stages and quote, then requires explicit user approval **or** the native untrusted-server prompt before submission. A fixed-cost operation uses its live schema price; an estimate is still appropriate for expensive/uncertain work. Unknown cost is disclosed, never fabricated. Each extra generation or retry is a separate paid action, not a free continuation.

Approval behavior depends on the Hermes host and your profile's approval settings. Unattended runs without an approver can be refused. A denial is not a reason to switch off trust, call the API through a script or retry around the gate. User-configured approval bypasses can permit unattended spending; this plugin adds no separate cap. An insufficient-wallet error (`40001`) needs a balance check and a user decision, not automatic retries.

The agent submits once and polls the original job/Concept. A timeout does not prove the provider failed to create or bill a job. Cancellation applies only to owned queued/submitted jobs and is subject to the provider's state/refund rules; do not assume a running job can be cancelled.

## Desktop cards and background jobs

With the Desktop half enabled, standalone directives render existing assets or progress. Examples (replace placeholders with actual IDs/host paths):

```text
::studiotwin-model{path="/absolute/model.glb" title="Character"}
::studiotwin-audio{asset="<asset-uuid>"}
::studiotwin-env{path="/absolute/environment.hdr"}
::studiotwin-material{maps='{"albedo":{"path":"/absolute/albedo.png"},"normal":{"path":"/absolute/normal.png"}}'}
::studiotwin-image{asset="<asset-uuid>" before="<source-asset-uuid>"}
::studiotwin-video{path="/absolute/preview.mp4"}
::studiotwin-task{id="<job-uuid>"}
::studiotwin-job{id="<job-uuid>"}
::studiotwin-concept{id="<concept-uuid>"}
```

[Exact attributes and sequence/sticker examples](skills/studiotwin/SKILL.md#delivery-by-surface-and-desktop-directives) are in the skill. Model/audio/environment cards use a local `path` or asset UUID, not arbitrary cloud URLs. Material maps need resolved/downloaded channel sources. A task/job card uses `id`, not `task`. Cards are scoped to their original profile/connection; reopening after a switch avoids retargeting old media to a different account. At most four live 3D WebGL viewers are allowed, configurable down to one; off-screen/context-limited cards can fall back until reopened.

**Telegram, Discord, Slack and WhatsApp:** long mesh, rig, pano-stickers and world jobs need a real notification-capable background poller. The skill supplies a host-aware Python adapter using the shipped direct MCP client to poll `studiotwin_get_job_status`, launched through `terminal(background=True, notify=True)`, exiting 0 on completion. A shell cannot invoke a model tool by typing its name, and no `studiotwin` CLI/poller executable is bundled. The host interpreter, active-profile secret resolver and plugin path must be checked before arming it. Without that wake, the agent must not promise future delivery. Desktop polling updates the visible card only; it does not wake the agent or execute a paid chain.

Downloads are delivered on messaging surfaces through standalone `MEDIA:/absolute/path` lines; CLI/TUI shows paths/text. Large attachments can use the provider download link instead. Link expiry follows actual provider metadata (many captured outputs say one hour), not a blanket retention guarantee. Save files you need to keep.

## Settings

In Desktop: **Capabilities → Plugins → hermes-studiotwin → settings**. Nonsecret settings live under `plugins.entries.hermes-studiotwin.settings`; for example:

```sh
hermes config set plugins.entries.hermes-studiotwin.settings.webgl_limit 2
hermes config set plugins.entries.hermes-studiotwin.settings.blender_handoff never
```

The complete `plugin.json` configuration surface (declared defaults, not a claim that every viewer consumes every setting):

| Key | Type / default | Purpose / accepted values |
|---|---|---|
| `api_key` | secret / unset | StudioTwin API key; stored as `STUDIOTWIN_API_KEY`, never sent to browser |
| `api_base_url` | str / `https://api.studiotwin.ai` | Desktop API endpoint; HTTPS, with HTTP only for localhost/127.0.0.1 tests; agent MCP stays direct to production |
| `show_credits` | bool / `true` | Show Desktop credit balance |
| `inline_cards` | bool / `true` | StudioTwin media cards in chat |
| `auto_rotate` | bool / `true` | Rotate models in Desktop viewers |
| `webgl_limit` | int / `4` | Maximum live WebGL viewers, 1–4 |
| `gallery_limit` | int / `24` | Recent assets shown, 1–100 |
| `blender_handoff` | str / `ask` | Offer new local Blender project: `ask`, `always`, `never` |
| `blender_path` | str / empty | Full Blender executable path; empty finds it on PATH |

Current settings boundary: `show_credits` is live in Desktop chrome; workspace inspection consumes `webgl_limit`, while inline viewers retain their four-context default. `inline_cards`, `auto_rotate` and `gallery_limit` are declared settings but are not yet wired across the assembled UI. Disable the Desktop half to suppress all custom cards; the library intentionally reads all pages so filtering is complete. Blender settings guide the workflow skill, not permission to overwrite a scene or decimate without an approved budget. There is no hidden model/audio-format/session-cap setting: per-call controls come from live MCP schemas.

## Files, provenance and local helpers

Files live on the **Hermes backend machine**, which may be remote from Desktop. The backend uses the active Hermes home's plugin data directory, normally `<HERMES_HOME>/plugin-data/agent-plugin-hermes-studiotwin-<hash>/` (with an unhashed fallback):

- `studio_cache/`: resolved cloud downloads, with unique names.
- `uploads/`: local uploaded copies; cloud upload is a separate explicit step.
- `asset-index.json`: profile-local index of files opened/downloaded by the plugin; not a scan of your home folder.
- `provenance.json`: local source/output IDs, prompt, tool, Concept/job and session linkage used by **Made from**.
- Conversion scratch files are removed after requests; saved/exported project files are not automatically cleaned up.

The Desktop backend serves checked media paths from plugin data, active `<HERMES_HOME>/cache/generated/` and supported files under the user's home. Local file access is constrained by backend path/link/media checks, not unrestricted renderer filesystem access. Downloads and uploads have size/format limits; unsupported or unsafe files are refused. Audio/video streaming supports HTTP Range; audio conversion requires ffmpeg on the backend host.

Provenance is not inferred from every remote call automatically. The skill documents how to record source IDs on submission and output IDs after completion using authenticated, plugin-scoped `POST /provenance` (full mount `/api/plugins/hermes-studiotwin/provenance`) and read it back. This is **not** a public StudioTwin endpoint. If an agent lacks a scoped backend adapter, it reports lineage in chat rather than pretending it persisted it. Prompt/session data in local provenance should be included in your retention/privacy planning.

Four bundled scripts run locally, with no StudioTwin generation credits. Examples from the plugin root:

```sh
python3 skills/studiotwin/scripts/glb_stats.py /absolute/model.glb
node skills/studiotwin/scripts/render_preview.mjs /absolute/model.glb --out /absolute/preview.mp4 --seconds 6 --size 720 --max-mb 8
blender --background --factory-startup --python skills/studiotwin/scripts/blender_handoff.py -- --input /absolute/model.glb --out-dir /absolute/new-handoff --export both
python3 skills/studiotwin/scripts/sfx_tool.py process /absolute/sound.wav --out /absolute/sound.ogg --mono --trim --loudness -18
python3 skills/studiotwin/scripts/sfx_tool.py loopcheck /absolute/loop.wav
```

[Full script CLI, dependencies and safety notes](skills/studiotwin/SKILL.md#local-scripts-no-studiotwin-credits):

- `glb_stats.py`: stdlib, measured geometry, bound skins and animation clip names; no network.
- `render_preview.mjs`: GLB turntable/clip **MP4**, not contact sheet. Spawns headless Chromium and ffmpeg. Uses bundled/development three 0.180.0 or downloads its integrity-checked tarball from `registry.npmjs.org` to `<HERMES_HOME>/cache/studiotwin-preview/`; default output is `cache/generated/videos/`. Rendering refuses external URLs inside the GLB and reports blocked resources.
- `blender_handoff.py`: Blender 4.2+, new background factory-startup processes, new optimized blend/GLB/FBX exports and fresh-process verification. Optional triangle/texture/LOD reductions require agreed scope; no live-scene edits. Decimation is not retopology; rig/shape-key losses must be disclosed.
- `sfx_tool.py`: Python stdlib + ffmpeg/ffprobe; probe/process/loopcheck/loopfix/pack. Writes chosen outputs and pack folder/manifest/zip, refuses existing outputs without `--force`. Never trim/fade a loop; check the delivered file's seam. Reports JSON measurements/errors.

## Privacy, network and telemetry

- Prompts, generation parameters, referenced source media/assets and authorized uploads leave the host for StudioTwin's cloud under your key. StudioTwin may use its generation providers (the schemas identify OpenAI/Gemini, Tripo, fal.ai and ElevenLabs routes). Provider billing, retention and terms apply; do not assume offline generation or that only RealTwin infrastructure processes media.
- The agent connects directly to `api.studiotwin.ai/mcp`. Desktop backend requests also go directly to the configured StudioTwin endpoint and allowed StudioTwin/S3 delivery/upload origins. The plugin does not add a local MCP proxy, IPC broker, opaque handles or URL-redaction layer. Desktop's host-scoped media streaming is not an agent MCP wrapper.
- `STUDIOTWIN_API_KEY` (`st_...`) and presigned **POST** upload policy/signature fields are secrets. They must not be copied into chat, browser JS, logs or reports. Presigned **download** URLs and `s3://` URIs are normal delivery links/locations and are **not redacted** merely because they contain signatures.
- Asset index/provenance and downloaded files stay in the active profile's storage unless you upload/share them. Hermes transcripts can contain prompts, IDs and ordinary delivery links. This plugin adds no independent analytics/telemetry collector; Hermes and StudioTwin have their own logging/policies.
- No persistent local MCP daemon is installed. Desktop polls visible jobs/status; agent-armed terminal pollers are bounded background processes, and local previews/handoffs/conversions spawn tools while running. Disabling/removing the plugin does not cancel a cloud job or necessarily stop a previously armed terminal process. Stop those processes separately when appropriate.

## Troubleshooting

| Symptom | Check |
|---|---|
| No tools | Agent half enabled in the correct profile, new session, MCP discovery; inspect host plugin/MCP logs; remove accidental duplicate server overrides only after review |
| Key rejected / no balance | Active profile's secret field/`.env`, not another profile or only the Desktop client's shell; never print the key |
| Insufficient credits (`40001`) | Read wallet and estimate; let the user fund/reduce scope; no paid auto-retry |
| Timeout after submit | List recent jobs and poll the existing ID; an uncertain result may already be billed |
| Concept seems stuck at draft | Inspect `operation.status` via ConceptLab status; lifecycle draft alone is not image-operation status |
| Expired download | Resolve existing asset for a new URL; no regeneration needed |
| Blank/unsupported card | Desktop half, exact directive attributes, original profile/connection, supported file format; see settings boundary above; use normal file/link fallback |
| No format conversions | ffmpeg on the Hermes host; original download still works |
| Local helper cannot find file | Terminal and backend may run on different machines; confirm paths/tool host before copying or installing |
| No automatic chat follow-up | A verified `background=True, notify=True` poller must be armed; a visible progress card alone is insufficient |
| Cannot cancel | Provider permits cancellation only before running; read back current job status |

## Disable or remove

```sh
hermes plugins disable hermes-studiotwin
hermes plugins remove hermes-studiotwin
```

Use the active profile and turn off Desktop UI separately if needed. Review the host's removal prompt/options; back up desired downloads and provenance first. Do not assume removal deletes cloud assets, cancels cloud jobs, clears retained profile data or revokes the API key. Stop outstanding terminal pollers, explicitly cancel eligible cloud jobs, and revoke the key in StudioTwin if desired. Delete retained local data only after identifying the correct active-profile directory and confirming scope.

## Development

From this repository, use Node.js 24+, npm and Python 3.11+; the Python dependency manifest is `[project]` only, letting the Hermes host manage plugin dependencies. The committed Desktop bundle is built from `src/` with React/SDK supplied by the host.

```sh
npm ci
npm run typecheck
npm run build:desktop
STUDIOTWIN_WEBGL_TEST=1 npx vitest run
python -m venv .venv
.venv/bin/pip install -r requirements-test.txt
PYTHONPATH=/absolute/path/to/hermes-agent .venv/bin/pytest -q
PYTHONPATH=/absolute/path/to/hermes-agent .venv/bin/python tools/verify_v07.py
hermes plugins validate .
hermes plugins doctor --ci .
```

The pinned portable host automatically discovers `skills/*/SKILL.md`. It does not accept a top-level `skills` manifest field; the admission probe verifies actual `studiotwin` skill discovery and zero warnings instead of shipping an ignored declaration.

Backend/host-loader tests may require a matching Hermes source checkout on `PYTHONPATH`; use their fixtures and the host version under test. Do not infer live compatibility from offline unit tests. Run validate/doctor/install/load probes only in a disposable Hermes home/environment, never a daily profile. Tests use captured schemas and local stand-ins; no paid provider call is required for this development loop. Rebuild `desktop/plugin.js` after renderer changes. The bundled tool snapshot is a deterministic fixture, not a version pin on the hosted service.

## License and attribution

MIT; see [NOTICE](NOTICE) and the retained upstream [licenses/](licenses/). Model/animation tooling and viewer patterns are adapted from Nous Research's Meshy plugin; audio tooling/card patterns from its ElevenLabs Sound Effects plugin, retaining attribution. Those upstream plugins' official status does not make this RealTwin package an official Nous Research plugin. StudioTwin and third-party service/content terms apply separately to generated assets.
