# StudioTwin installed — configure and verify

This is RealTwin's `hermes-studiotwin` plugin, not a Nous Research official plugin. No generation is needed to finish setup. Its private Git repository is `realtwin/hermes-studiotwin-plugin`; the installed plugin ID stays `hermes-studiotwin`.

1. **Use the intended Hermes profile.** Enable the agent half if it is not enabled:
   ```sh
   hermes plugins enable hermes-studiotwin
   hermes plugins show hermes-studiotwin
   ```
   Installation/enabled state alone does not prove that the remote tools or Desktop UI loaded.
2. **Configure your StudioTwin API key privately.** In Desktop: **Capabilities → Plugins → hermes-studiotwin → settings → StudioTwin API key**. Without Desktop, put `STUDIOTWIN_API_KEY` in the active profile's `.env`/secret configuration. `hermes config set STUDIOTWIN_API_KEY <your-key>` is also supported when executed privately; real keys can enter shell history. Do not paste the key into chat, source files, screenshots or bug reports. A new StudioTwin key comes from your StudioTwin account; this plugin does not require separate generation-provider keys.
3. **Start a new Hermes session.** Ask: “Discover StudioTwin tools and check my credit balance without generating anything.” A real `studiotwin_get_credit_balance` response verifies the remote connection and key. Optionally list existing assets or jobs. Do not use a paid generation as a connectivity test.
4. **Enable Desktop UI if wanted.** Turn on the plugin's Desktop half in Capabilities → Plugins, then open **StudioTwin** from the sidebar/palette. Route: **`/studiotwin`**; tabs: Library, Jobs, Concepts and Upload. Remote use needs the enabled backend/key on the Hermes machine **and** client UI: in the client Desktop's **Install from Git**, use `realtwin/hermes-studiotwin-plugin` with **Desktop UI** selected, then enable its Desktop switch. Private GitHub access is required on each cloning machine. Desktop UI is app-level, not per selected backend profile. CLI/chat users do not need Desktop.
5. **Start with an estimate.** For example: “Create a character Concept, estimate the credits first, and show me the image before making any mesh.” The bundled `studiotwin` skill covers routing, all captured tools, exact card attributes and local scripts.

## Connection and requirements

`mcp.json` already connects directly to `https://api.studiotwin.ai/mcp` using Streamable HTTP with `x-api-key: ${STUDIOTWIN_API_KEY}`. Do **not** add a duplicate `mcp_servers.studiotwin` entry unless deliberately overriding the bundle. There is no local MCP proxy/IPC gateway, no local MCP daemon and no opaque-handle or URL-redaction layer.

Use a Hermes host with Agent Plugins v1, Streamable HTTP MCP and native approval/cost support; full Desktop cards need transcript-directive/tool-media support. See [support and evidence boundaries](docs/compatibility.md): Hermes v0.23.1 is the tested released host for isolated install/load. This is not an inferred historical minimum or native Desktop proof; the portable manifest does not enforce a numeric host floor. Backend/helpers need Python 3.11+; the backend uses httpx and the host FastAPI environment. Optional local tools: Blender 4.2+, ffmpeg/ffprobe; MP4 previews also need Node.js 22+ and Chromium/Chrome. Package development requires Node.js 24+. Network access to StudioTwin and allowed S3/StudioTwin asset origins is needed for cloud workflows.

## Spending — read before generating

Generation consumes your StudioTwin wallet credits. The plugin declares the MCP server **`trust: untrusted`** and prices for Hermes's native approval UI, with a 1,500-second call timeout. Variable-price work must use **`studiotwin_estimate_cost` with exact inputs plus `studiotwin_get_credit_balance`** before submission; these checks also apply when you ask about price/balance. Fixed prices come from the live schema. The agent must explain the selected operation and cost, then obtain explicit approval **or** the native trust prompt before paid work. Extra variants, retries and stages are not implicitly approved.

There is **no artificial 200-credit limit**, plugin session spend cap, local reservation ledger or separate payment gateway. Manifest ranges are illustrative approval guidance, not provider price ceilings. Host settings that bypass prompts can allow unattended spending without a plugin cap; do not change them to work around a denial. An unattended session without an approver may refuse paid work. Next buttons send visible chat requests, not hidden paid submissions. Insufficient balance (`40001`) or uncertain submission must not trigger automatic paid retries.

## What leaves the machine; what stays

- Prompts, generation parameters, source references/media and authorized uploads go to StudioTwin under your key; StudioTwin's selected generation providers and terms apply. The captured schemas identify routes using OpenAI/Gemini, Tripo, fal.ai and ElevenLabs. This is cloud generation, not an offline model. The plugin adds no provider-retention setting or cloud-retention guarantee.
- The agent uses the direct remote MCP endpoint. The Desktop backend calls StudioTwin directly and downloads/uploads through allowed StudioTwin/Amazon S3 origins. Changing `api_base_url` affects the Desktop backend, **not** the agent MCP declaration.
- `st_...` API keys and presigned **POST** upload policies/signatures are secret and must not be exposed. Presigned **download** URLs and `s3://` URIs are ordinary delivery links/asset locations, not credentials to redact. Links can expire; resolve the existing asset again instead of generating it again.
- Files stay on the Hermes backend host, which may be remote from your Desktop. Cached downloads, uploaded copies, `asset-index.json` and local `provenance.json` live under active `<HERMES_HOME>/plugin-data/agent-plugin-hermes-studiotwin-<hash>/` (with an unhashed fallback). The index is not a home-folder scan. Provenance can include prompts and source/output/job/Concept/session IDs. Do not assume every remote job automatically has a local Made from record.
- Generated preview MP4s default to `<HERMES_HOME>/cache/generated/videos/`; other scripts write chosen destinations. Desktop conversion scratch files are cleaned after requests. Back up assets you need permanently; viewing is not a storage/retention guarantee.
- This plugin adds no independent analytics collector. Hermes and StudioTwin still have their own logs/policies; transcripts may contain prompts, IDs and normal download links.

## Background and local tools

Desktop polls visible jobs/status but does not itself wake the agent or continue paid chains. In Telegram, Discord, Slack and WhatsApp, long mesh/rig/pano-stickers/world jobs require an actually armed **`terminal(background=True, notify=True)`** process polling the original `studiotwin_get_job_status` and exiting 0 on completion. The skill includes a host-aware direct-client Python adapter. There is no bundled `studiotwin` CLI: typing a model tool name into a shell is not a working poller. The agent must verify host interpreter/profile/secret access and notification support; without a wake it must not promise later automatic delivery. Bounded pollers and cloud jobs can outlive a chat turn; disabling the plugin does not necessarily stop them.

Bundled scripts (`skills/studiotwin/scripts/`) cost no StudioTwin generation credits:

- `glb_stats.py`: inspect actual triangles, bound skeletons and clips, standard library only.
- `render_preview.mjs`: GLB turntable/animation MP4; spawns headless Chromium/ffmpeg and can download integrity-checked three 0.180.0 from `registry.npmjs.org` into the active home's preview cache if absent. External GLB resources are blocked/reported.
- `render_multiview.mjs`: four/six-view PNG sheets and optional split images; shares `render_harness.mjs` with the MP4 helper. Needs Node 22+, Chromium and three; no ffmpeg or paid call.
  Both render helpers launch Chromium with `--no-sandbox` and `--enable-unsafe-swiftshader`. Chromium's sandbox is disabled and unsafe software rendering enabled. Integrity checks and external-resource refusal are not process isolation: use trusted inputs, or a separately isolated processing environment for untrusted assets.
- `blender_handoff.py`: fresh Blender factory-startup process, new blend/GLB/FBX outputs and fresh-process checks. No live-scene edits; triangle budgets and risky loss/overwrite flags require authorization. A fresh process is not a security sandbox.
- `sfx_tool.py`: ffmpeg/ffprobe processing, format conversion, loudness/loop checks and packs. Selected outputs must not overwrite existing files without permission. Never trim or fade a loop; check its final seam.

See [README](README.md#files-privacy-and-local-tools) and the [local-tools reference](skills/studiotwin/references/local-tools.md) for exact commands and prerequisites. Scripts run on the terminal host, not automatically on the Desktop computer.

## Settings, failures and removal

Current settings boundary: `show_credits` is live. Settings refresh on the settings-changed event without reload. `inline_cards=false` restores tool-media fallbacks and plain directive text, without disabling workspace/navigation/chrome. `auto_rotate` initializes inline and workspace model viewers; a manual viewer toggle overrides it locally. Clamped `webgl_limit` applies to inline model/environment/material viewers and workspace inspectors. Clamped `gallery_limit` sets recent Concepts/Jobs page sizes (offset resets on change), not the library's complete-filter 100-row paging or the active-job count. Missing/malformed values use manifest defaults.

Desktop settings include `api_key`, `api_base_url`, `show_credits`, `inline_cards`, `auto_rotate`, `webgl_limit` (1–4, default 4), `gallery_limit` (1–100, default 24), `blender_handoff` (ask/always/never, default ask) and `blender_path` (empty: PATH). Nonsecrets use `plugins.entries.hermes-studiotwin.settings.*`; the key maps to `STUDIOTWIN_API_KEY`. The [README settings table](README.md#settings) lists every default.

Missing tools: check correct profile, enabled agent half, new session and accidental MCP overrides. Blank cards: check Desktop half, exact attributes, supported file and original connection/profile; see the settings boundary above. Missing conversions: ffmpeg must be on the backend host. An expired URL needs asset resolution. A timeout after submission needs original-job status/listing, not another paid create. For ConceptLab, use Concept status and inspect `operation.status`, not just lifecycle draft.

To disable/remove:

```sh
hermes plugins disable hermes-studiotwin
hermes plugins remove hermes-studiotwin
```

Back up wanted downloads/provenance and review removal options first. Stop background pollers separately; cancel eligible queued/submitted cloud jobs explicitly if wanted. Removal is not a cloud-asset deletion, job cancellation or key revocation guarantee, and retained local data may need a separate confirmed cleanup. Revoke the key in StudioTwin if no longer needed.

MIT; see [NOTICE](NOTICE) and the retained upstream [licenses/](licenses/). Meshy and ElevenLabs Sound Effects adaptations retain Nous Research attribution; RealTwin's plugin is distributed independently.
