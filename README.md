# StudioTwin for Hermes Agent

> A RealTwin plugin for Hermes, not a Nous Research official plugin.

Create and inspect images, environments, PBR materials, meshes, rigs, character motion and sound effects with [StudioTwin](https://studiotwin.ai). Keep iterations together as durable ConceptLab Concepts, then reuse the assets in your projects.

One package supplies a direct remote MCP connection for the agent, a bundled workflow skill, and an optional Hermes Desktop workspace with media viewers. There is no local MCP server or proxy. Generation is paid; browsing existing assets and local processing do not create paid generations.

Try: “Create a character Concept, estimate the credits first, and show me the image before making a mesh,” or “Make a rain loop for my game; estimate it before generating.”

## Requirements and support

- **Tested released agent/backend host: Hermes v0.23.1** at `3b421578588243f920886e6fe79a6faa87ea026e`, on Linux/Python 3.14.9, with isolated validation, doctor and actual PluginManager load. Full Desktop UI also needs the transcript-directive, tool-media and scoped backend SDK surfaces; native client acceptance is separate. **Installation alone does not prove compatibility.** See [support and verification boundaries](docs/compatibility.md). Portable Agent Plugins v1 has no manifest host-floor field; the earliest compatible historical release is not established.
- A StudioTwin account and API key, with wallet credits for generation. No separate OpenAI, Tripo or ElevenLabs key is required by this plugin.
- Network access from the Hermes host to `api.studiotwin.ai` and the returned StudioTwin/Amazon S3 delivery/upload endpoints.
- Python 3.11+ for the backend/helpers, `httpx>=0.27,<1`, and the host's FastAPI environment. Let Hermes prepare plugin dependencies.
- Optional local tools, on the machine doing the processing: Blender 4.2+; ffmpeg/ffprobe for sound and MP4 previews; Node.js 22+ and Chrome/Chromium for GLB previews/contact sheets. Package development requires Node.js 24+ and npm.

## Install

The repository is currently private. You need GitHub access to **`realtwin/hermes-studiotwin-plugin`**; it is not a public catalog install. Authenticate Git on the **Hermes backend machine** using your normal approved credential helper or organizational access method before installing. A StudioTwin API key does not grant GitHub access. Do not put GitHub tokens in a repository URL, command argument, chat or bug report.

A read-only Git check, run privately on that machine:

```sh
git ls-remote https://github.com/realtwin/hermes-studiotwin-plugin.git HEAD
```

Then, in the intended Hermes profile:

```sh
hermes plugins install realtwin/hermes-studiotwin-plugin
hermes plugins enable hermes-studiotwin
hermes plugins show hermes-studiotwin
```

The **repository slug** ends in `-plugin`; the **plugin ID** remains `hermes-studiotwin`. Installation is per profile: use `hermes -p <profile> plugins ...` consistently for another profile. Review the installer's code/dependency/enable prompts. Agree to Python dependency preparation for the backend; `--no-deps` leaves a downloaded package disabled and is not a working setup. The Desktop bundle is committed, so end users do not need a source build to load it.

For a reviewed revision, replace the placeholder below with the maintainer-supplied full 40-character commit SHA. This is a command template, not a published v1 pin:

```sh
hermes plugins install realtwin/hermes-studiotwin-plugin --ref <full-40-character-commit-sha>
```

A new local documentation/release-candidate commit is not necessarily available from GitHub. Private Git authentication and a pinned install still need to succeed on the target host; local fixture tests are not substitutes.

## Configure and verify without spending

1. Create an API key in your StudioTwin account. In Desktop, open **Capabilities → Plugins → hermes-studiotwin → settings → StudioTwin API key**. Keep credentials out of chat.
2. Without Desktop, use the active profile's secret configuration or `.env`. `hermes config set STUDIOTWIN_API_KEY <your-key>` is supported when executed privately, but real values can enter shell history. The Desktop secret field is preferable. Secrets belong in the active profile's `.env`/secret store, never `config.yaml` or browser JS.
3. Start a new Hermes session. Ask: **“Discover StudioTwin tools and check my credit balance without generating anything.”** A real `studiotwin_get_credit_balance` response verifies the MCP connection and key without a paid generation. Optionally list existing assets/jobs.
4. For Desktop, turn on the plugin's **Desktop** half and open **StudioTwin** from the sidebar or command palette. The workspace route is `/studiotwin`, with Library, Jobs, Concepts and Upload tabs. The Desktop toggle and the enabled agent/backend are separate requirements.

**Remote Desktop:** install/enable the agent package and configure the key on the remote Hermes host. On the client Desktop, use **Capabilities → Plugins → Install from Git** with `realtwin/hermes-studiotwin-plugin`, select the **Desktop UI** target, then enable its Desktop switch. Authenticate private-repository access on that client too. Desktop UI is app-level, not installed anew for each selected agent profile. A remote backend-only install can show **unavailable (remote backend)** until the client has the UI. Files and conversion tools remain on the backend; playback/downloads stream through scoped host access. See the [official SDK's unified-package guidance](https://hermes-agent.nousresearch.com/docs/developer-guide/desktop-plugin-sdk#one-package-both-sdks).

`mcp.json` already connects directly to `https://api.studiotwin.ai/mcp`, using Streamable HTTP and `x-api-key: ${STUDIOTWIN_API_KEY}`. Do not add a duplicate `mcp_servers.studiotwin` entry inadvertently: it can override the bundle. The `api_base_url` setting changes the **Desktop backend**, not the agent MCP endpoint.

## Capabilities

| Workflow | Cloud tools | Desktop / local inspection |
|---|---|---|
| Images and Concepts | One-shot generate/edit; create, generate, edit, attach/select assets, clone, update, list/status/delete durable Concepts | Image comparison, Concept history and active-asset indication |
| Meshes | Simple/Tripo image-to-3D; retopology and decimation | GLB/FBX/OBJ preview, orbit/pan/zoom, textured/clay/normals/wireframe, geometry stats |
| Rigs and motion | Cloud Blender/Tripo rigging, riggability check, motion generate/edit/control/stitch | Bound skeleton/clip inspection, clip playback/scrub, provider rig-audit display, new Blender handoff |
| Environments and worlds | Text/image environment maps, upscale, sticker placement/compositing, environment-to-world | HDR/EXR/PNG 360° viewer, exposure, sticker boundaries and world-mesh preview |
| PBR materials | Text-to-material, image-guided extraction, texture decomposition | Sphere/cube/rounded-plane inspector, available map channels and map/zip downloads |
| Sound effects | SFX with optional duration/loops | Waveform, seeking, loop audition, original/converted downloads; local loudness, seam and pack tools |
| Video / frame sequences | Browse/upload existing assets, **not video generation** | Video playback/scrub; exact MP4 frame stepping where timing can be read; explicit-rate image sequences |
| Account / assets / jobs | Estimates, wallet, status/list/cancel, upload/complete/resolve | Library, Jobs, Concepts, Upload, credit/active-job chips and local Made from lineage |

**Next** actions put a visible request into the originating chat; they do not start hidden paid jobs. An image-to-mesh chain, retargeting route or engine import still needs compatible inputs and authorization at each stage. Motion JSON is not automatically a rigged animated GLB. A world mesh is not a complete engine level. Missing optional material maps remain unavailable rather than fabricated.

### Multiview and reskin references

In a model inspector, choose **Multiview**, 4 or 6 views, shading and yaw offset, then **Capture Multiview**. Desktop captures the current pose and restores the live view state. It offers a labeled PNG contact sheet, individual-view badges and **Download Sheet**. The sheet is staged **locally** on the originating backend, with Made from provenance; this does not upload it to the cloud. Staging/lineage errors leave the sheet downloadable but disable the reskin handoff.

**Reskin 3D in Chat** proposes a reference workflow: inspect the sheet, authorize upload/edit, review the edited reference, then separately estimate/approve reconstruction. This is not in-place retexturing and may change topology, rig and animation. Do not assume a contact sheet is a supported multiview input to a live provider. [Full workflow and CLI](skills/studiotwin/references/local-tools.md#multiview-reference-sheets-and-forge-e-style-reskinning).

Environment IBL lets available HDR/EXR or equirectangular PNG/JPG panoramas light a model, optionally as its background. It changes preview lighting, not the source file.

### Tool and card reference

The [bundled skill](skills/studiotwin/SKILL.md) links a [complete catalog of the 45 captured provider tools](skills/studiotwin/references/tools.md), with required arguments and [routing constraints](skills/studiotwin/references/workflows.md). Its source is the [2026-10-30 fixture, server 1.2.4](tests/fixtures/tools-list-2026-10-30.json), **not a live-server pin**. Discover tools and describe their live schemas before calling; use the returned callable name rather than guessing a Hermes prefix.

The snapshot's current image identifier is `openai-gpt-image-2-v4-fn`; the viewer also recognizes legacy `openai-gpt-image-1-v1-fn` for old transcripts. Renderer recognition does not make that legacy function callable. `pano-sticker-placement` selects placement; `pano-stickers` composites with camelCase sticker fields. The captured `sourceAspect` discrepancy is documented in the routing reference, not silently normalized.

Desktop directives must occupy their own paragraph. Replace placeholders with real backend paths or IDs:

```text
::studiotwin-model{path="/absolute/model.glb" audit="/absolute/rig-audit.json" title="Character"}
::studiotwin-audio{asset="<asset-uuid>"}
::studiotwin-env{path="/absolute/environment.hdr"}
::studiotwin-material{albedo="/absolute/albedo.png" normal="/absolute/normals.png"}
::studiotwin-image{asset="<asset-uuid>" before="<source-asset-uuid>"}
::studiotwin-video{path="/absolute/preview.mp4"}
::studiotwin-task{id="<job-uuid>"}
::studiotwin-job{id="<job-uuid>"}
::studiotwin-concept{id="<concept-uuid>"}
```

[Exact attributes, all optional channels, audit handling, sequence/sticker limits and provenance](skills/studiotwin/references/delivery.md). Task/job cards use `id`, not `task`; material `normal` deliberately maps the provider's `normals`. Nested braces in attribute values cannot pass Desktop's transcript parser: use flat channels and tool-media for object-based sequences/stickers. Model/audio/environment cards accept backend-local paths or asset UUIDs, not arbitrary cloud URLs. Local skeleton counts are not a provider rig-audit verdict. Viewers and waveforms are user-facing UI, **not proof the model saw or heard the result**.

## Credits, approval and recovery

Paid calls go through the **direct remote MCP server**. The manifest declares `trust: untrusted`, a 1,500-second timeout and estimated credit costs for Hermes's native approval UI. There is **no plugin session spend cap, artificial 200-credit cap or local billing/reservation ledger**. Illustrative ranges such as 1–100 are not provider price ceilings.

For variable-price work, or a cost/balance question, the skill requires `studiotwin_estimate_cost` with the **exact intended inputs** and `studiotwin_get_credit_balance`. State the operation, variants, stages and quote, then obtain explicit user approval or the native trust prompt before submission. Fixed prices come from live schemas; unknown cost is disclosed, never invented. Extra stages, variants and retries are separate authorizations.

Host/profile approval settings matter. An unattended run without an approver can be refused; configured prompt bypasses can permit uncapped spending. A denial is not a reason to change trust, call a paid API through a helper or retry around the gate. Insufficient-wallet error `40001` needs a balance check and user decision.

Submit once and preserve the job, Concept and output-asset IDs separately. A timeout or lost connection does **not** prove the job failed or was not billed. Resume by listing/checking the original job. Concept image operations use `studiotwin_conceptlab_get_status` and `operation.status`, not the Concept ID as a job ID or lifecycle `draft` as a completion signal. Cancel only eligible owned queued/submitted jobs; verify status afterward and do not assume running jobs can be cancelled or refunded.

Desktop polls visible status/cards; it does not wake the agent or execute dependent paid stages. On Telegram, Discord, Slack and WhatsApp, the skill's [long-job procedure](skills/studiotwin/SKILL.md#long-jobs-arm-a-real-chat-wake) requires a verified `terminal(background=True, notify=True)` poller for automatic follow-up. No `studiotwin` CLI/poller executable is bundled. Without working host interpreter, profile-secret access and notifications, the agent must disclose that automatic delivery is not armed. A sleep alone is not a status poller.

Messaging delivery uses a separate `MEDIA:/absolute/path` line for each downloaded attachment; CLI/TUI prints paths/text. Large files can use the provider link. Link expiry follows provider metadata; resolve an expired asset URL instead of regenerating.

## Settings

Desktop: **Capabilities → Plugins → hermes-studiotwin → settings**. Nonsecrets live under `plugins.entries.hermes-studiotwin.settings`:

```sh
hermes config set plugins.entries.hermes-studiotwin.settings.webgl_limit 2
hermes config set plugins.entries.hermes-studiotwin.settings.blender_handoff never
```

| Key | Type / default | Purpose |
|---|---|---|
| `api_key` | secret / unset | Stored as `STUDIOTWIN_API_KEY`, never sent to browser JS |
| `api_base_url` | str / `https://api.studiotwin.ai` | Desktop API base; HTTPS, HTTP only for localhost/127.0.0.1 tests |
| `show_credits` | bool / `true` | Credit chip |
| `inline_cards` | bool / `true` | Inline StudioTwin cards |
| `auto_rotate` | bool / `true` | Initial model rotation |
| `webgl_limit` | int / `4` | Maximum live WebGL viewers, clamped 1–4 |
| `gallery_limit` | int / `24` | Recent Concepts/Jobs page size, clamped 1–100 |
| `blender_handoff` | str / `ask` | Workflow policy: `ask`, `always`, `never` |
| `blender_path` | str / empty | Blender executable; empty uses PATH |

Settings refresh on the scoped settings-changed event. `inline_cards=false` restores tool-media fallback/plain directive text, not disabled workspace/navigation/chrome. `auto_rotate` initializes inline/workspace viewers; manual toggles override it locally. `webgl_limit` includes workspace inspectors; off-screen/context-limited viewers can fall back until reopened. `gallery_limit` resets recent-page offsets, not the library's complete 100-row paging or all-page active-job counts. Missing/malformed values use defaults. Blender settings do not authorize overwrites or geometry losses. There is no hidden model/audio-format/session-cap setting; generation controls come from live schemas.

## Files, privacy and local tools

Files live on the **Hermes backend machine**, possibly remote from Desktop. The active home's data root is normally `<HERMES_HOME>/plugin-data/agent-plugin-hermes-studiotwin-<hash>/`, with an unhashed fallback:

- `studio_cache/`: uniquely named cloud downloads; `uploads/`: local staged copies. Cloud upload is a separate explicit action.
- `asset-index.json`: files opened/downloaded through this plugin, not a scan of the home folder.
- `provenance.json`: local Made from records, which can include prompt, source/output, job, Concept and session IDs. Remote jobs are **not all automatically recorded**. [Scoped provenance write/readback procedure](skills/studiotwin/references/delivery.md#made-from-provenance).
- Audio-conversion scratch files are removed after requests. Exports/project files are not automatically cleaned up; preview MP4s default to `<HERMES_HOME>/cache/generated/videos/`.

Backend file/link/media checks constrain serving to plugin data, active `cache/generated/` and supported files under the user home. This is not an execution sandbox. Downloads/uploads have size/format limits; audio/video support HTTP Range. Format conversion needs ffmpeg on the backend host.

Five bundled entry-point scripts run through the terminal: `glb_stats.py` (measured mesh/rig/clip data), `render_preview.mjs` (MP4), `render_multiview.mjs` (PNG sheets/splits), `blender_handoff.py` (new Blender/export copies) and `sfx_tool.py` (probe/process/loopcheck/loopfix/pack). [Exact recipes, dependencies and safety flags](skills/studiotwin/references/local-tools.md). They spend no StudioTwin credits, but rendering may download integrity-checked three 0.180.0 from `registry.npmjs.org` into the active home's preview cache. Render helpers share `render_harness.mjs`, spawn headless Chromium with `--no-sandbox` and `--enable-unsafe-swiftshader`, and refuse external GLB resources; MP4 also spawns ffmpeg. These flags disable Chromium's sandbox and enable unsafe software rendering: resource refusal/integrity checks are not process isolation. Use trusted inputs; process untrusted assets only in a separately isolated environment. Blender runs fresh factory-startup processes, not an attached live scene or a security sandbox. Do not trim/fade loops; inspect the delivered seam. Choose new outputs; risky loss/overwrite flags need authorization.

Prompts, generation parameters, source references/media and authorized uploads leave the host for StudioTwin and its selected generation providers. Captured schemas identify OpenAI/Gemini, Tripo, fal.ai and ElevenLabs routes. Their terms, billing and retention apply. The plugin exposes no separate provider-retention control and makes no cloud-retention guarantee; this is not offline generation. Desktop requests go directly to its configured API and allowed StudioTwin/S3 origins. It adds no MCP proxy, TCP IPC broker, opaque handles or URL-redaction layer.

**Secrets:** API keys (`st_...`) and presigned **POST** upload policy/signature fields must not appear in chat, renderer JS, logs or reports. Presigned **download** URLs and `s3://` URIs are ordinary delivery locations and are not redacted just for being signed. Transcripts may contain prompts, IDs and those normal links. Index/provenance/cache stay in the active profile unless shared/uploaded. This plugin adds no independent analytics collector; Hermes/StudioTwin have their own logs and policies.

No persistent local MCP daemon is installed. Desktop polling, agent-armed bounded background pollers and temporary render/conversion/Blender processes are separate activities. Disable/remove does not necessarily stop a poller or cancel a cloud job.

## Troubleshooting

| Symptom | Check |
|---|---|
| Repository not found / install denied | Correct `realtwin/hermes-studiotwin-plugin` slug and private GitHub access on the machine doing the clone |
| No tools | Correct enabled profile, new session, discovery, host plugin/MCP logs and accidental server overrides |
| Key rejected / no balance | Active backend profile's secret field, not another profile or only the client shell; never print the key |
| Timeout after submit | List recent jobs and poll the original ID; do not automatically submit again |
| Concept remains draft | Inspect `operation.status` through ConceptLab status |
| Blank card / remote UI unavailable | Client Desktop UI install/switch, original scope, exact attributes, supported file; use normal link/file fallback |
| Expired download | Resolve the existing asset again |
| Missing conversion/helper input | Tools/files must be on the processing host; terminal and backend can be different machines |
| No automatic follow-up | Check the actual notification-capable poller handle; a visible progress card alone is insufficient |
| No exact video frame stepping | Timing inspection has format/size/CORS limits; ordinary playback remains available; [timing details](docs/video-frame-timing.md) |

## Disable or remove

```sh
hermes plugins disable hermes-studiotwin
hermes plugins remove hermes-studiotwin
```

Use the intended profile; manage the app-level Desktop switch separately. Back up wanted downloads/provenance and review removal behavior first. Removal does not imply cloud deletion, job cancellation, API-key revocation or deletion of retained local data. Stop pollers separately, explicitly cancel eligible jobs if wanted, and revoke the key in StudioTwin if no longer needed. Identify the correct active-profile storage before any confirmed cleanup.

## Development and verification

[Development recipes and evidence classes](docs/development.md) cover isolated dependencies, script checks, tests, bundle rebuilds and host validation. Do not run dependency-preparation probes against a daily profile/shared managed environment. [Compatibility](docs/compatibility.md) distinguishes released-host source inspection, fixture/browser tests and native Desktop acceptance; none is silently substituted for another. [Candidate v1 notes](docs/release-notes-v1.md) are not a shipped-release claim.

## License and attribution

MIT; see [NOTICE](NOTICE) and retained upstream [licenses/](licenses/). Model/animation tooling and viewer patterns adapt Nous Research's Meshy plugin; audio tooling/card patterns adapt its ElevenLabs Sound Effects plugin. Attribution does not make this RealTwin package an official Nous plugin. StudioTwin and third-party service/content terms apply separately to generated assets.
