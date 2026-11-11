---
name: studiotwin
description: Create and deliver StudioTwin assets, Concepts and motion.
version: 0.2.0
author: RealTwin, Hermes Agent
license: MIT
platforms: [linux, macos, windows]
metadata:
  tags: "media, 3d, audio, concepts, mcp"
  host-tested: "Hermes v0.23.1 (3b421578588243f920886e6fe79a6faa87ea026e)"
---

# StudioTwin

Generate images, Concepts, environments, worlds, materials, meshes, rigs, motion and sound through the bundled **remote** `studiotwin` MCP connection. Most generation spends StudioTwin credits. Local viewers and processing are separate from cloud generation.

## When to Use

- Create or iterate a StudioTwin asset or durable Concept; reuse, inspect, download or upload assets.
- Check wallet, jobs or Concept history; inspect a downloaded GLB, render a preview, prepare a new Blender copy or process audio locally.
- Not a speech, full-song or general video-generation toolset. Video and frame-sequence viewers display existing media; they do not imply a video-generation API. Unreal/Blender editor mutations require separately connected editor tools and authorization.

## Prerequisites and discovery

The `hermes-studiotwin` plugin must be enabled in the active profile with `STUDIOTWIN_API_KEY` configured securely. Tested agent/backend release: **Hermes v0.23.1**, commit `3b421578588243f920886e6fe79a6faa87ea026e`; this is not an established historical minimum or native Desktop acceptance. Portable `plugin.json` has no host-floor field. Never ask for a key in chat. `mcp.json` connects directly to `https://api.studiotwin.ai/mcp` over Streamable HTTP; its `x-api-key` header resolves from the active profile's `STUDIOTWIN_API_KEY` secret. No local MCP proxy, IPC gateway, redaction service, opaque handle registry or credit-reservation layer is required.

Use Hermes tool search, describe the exact returned tools, then call them. Hermes may sanitize provider hyphens to underscores and add a prefix such as `mcp__studiotwin__`; do not construct a callable identifier from this table. Read the **live schema** immediately before invocation. The [captured tool catalog](references/tools.md) is orientation, not permission to invent arguments or assume an old function is available.

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

## Reference-driven workflows

Read the relevant reference **before** choosing arguments or continuing a chain. These files ship with this skill, not as separate skills.

| Task | Required reference |
|---|---|
| Find exact provider tools, required fields, ConceptLab state/inputs or upload sequence | [Complete captured catalog](references/tools.md) |
| Image → mesh → retopo → rig → motion; environment → world/stickers; PBR extraction; SFX prompting and formats | [Routing and compatibility](references/workflows.md) |
| Desktop cards, audit JSON, surface-specific delivery or `POST /provenance` plus readback | [Delivery and provenance](references/delivery.md) |
| Inspect GLB; render MP4/contact sheets; 3D reskin reference chain; new Blender copy; sound/loop/pack processing | [Local tools](references/local-tools.md) |

Use `terminal` for the local script commands in that reference: `glb_stats.py`, `render_preview.mjs`, `render_multiview.mjs`, `blender_handoff.py`, `sfx_tool.py`. Resolve the actual installed skill/plugin directory first; scripts run on the terminal host, not necessarily the Desktop or backend host. Check dependencies and choose new destinations before execution. No StudioTwin credits are used; optional first-run dependency downloads still use the network.

### Quick lookup (snapshot, not live schemas)

This index retains every captured provider name for discovery. Do not invoke from this list alone; load [tools.md](references/tools.md) and describe the live schema first.

- `text-to-motion-edit`, `text-to-motion`, `text-to-motion-kimodo`
- `text-to-motion-control`, `motion-stitch-single`, `text-to-environment-map`
- `image-to-environment-map`, `environment-map-to-world`, `environment-map-upscale-cpu`
- `pano-sticker-placement`, `pano-stickers`, `text-to-material`
- `texture-to-material`, `image-to-material`, `image-to-3d-mesh`
- `tripo-image-to-3d-mesh`, `tripo-rig-check`, `blender-auto-rig`
- `tripo-auto-rig`, `tripo-retopology`, `text-to-sound-effect`
- `prompt-to-dart-translation`, `openai-gpt-image-2-v4-fn`, `concept-lab-img-fn`
- `studiotwin_get_job_status`, `studiotwin_estimate_cost`, `studiotwin_get_credit_balance`
- `studiotwin_list_my_jobs`, `studiotwin_cancel_job`, `studiotwin_list_my_assets`
- `studiotwin_upload_asset`, `studiotwin_complete_asset_upload`, `studiotwin_resolve_asset`
- `studiotwin_conceptlab_create`, `studiotwin_conceptlab_create_and_generate`, `studiotwin_conceptlab_list`
- `studiotwin_conceptlab_get`, `studiotwin_conceptlab_get_status`, `studiotwin_conceptlab_attach_asset`
- `studiotwin_conceptlab_generate`, `studiotwin_conceptlab_edit`, `studiotwin_conceptlab_clone`
- `studiotwin_conceptlab_set_active_asset`, `studiotwin_conceptlab_update`, `studiotwin_conceptlab_delete`

Desktop directive lookup (load [delivery.md](references/delivery.md) for exact attributes):
`::studiotwin-model`, `::studiotwin-audio`, `::studiotwin-env`, `::studiotwin-material`, `::studiotwin-image`, `::studiotwin-video`, `::studiotwin-task`, `::studiotwin-job`, `::studiotwin-concept`.

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

A standalone Python process does not inherit the parent's secret-scope ContextVar, and setting `HERMES_HOME` alone does not load its `.env`. On the inspected host, unscoped `get_secret` reads process environment outside multiplex mode and can refuse under multiplexing. Use this adapter only after the actual terminal execution path demonstrably resolves the intended profile secret through supported host context; never copy another profile's key or print it to diagnose. If that precondition cannot be established, use inline tool polling or disclose manual check-back instead. A loopback test with an injected secret proves polling semantics, not production secret inheritance or a delivered notification.

Desktop progress cards can poll visually, but they do not wake the agent or execute dependent paid steps. In CLI/TUI, poll inline or use a verified notification-capable background process as appropriate.

## Verification and troubleshooting

- Missing tools: verify installed/enabled agent half and active profile, start a new session, discover tools again. Do not add a duplicate `mcp_servers.studiotwin` entry that replaces the bundle by accident.
- Authentication failure: configure the key in the active profile's secret settings, not browser JS or a chat. Insufficient credits (`40001`): check balance and obtain user-directed funding/changed scope; never retry paid submission automatically.
- Expired download: resolve the existing asset again. Missing file on terminal: check remote-host mismatch before installing or copying anything.
- Blank card: verify Desktop half, actual directive attributes, origin profile/connection and supported format. Settings refresh from scoped `/status` on the settings-changed event. `inline_cards=false` restores tool-media fallback and plain directive text, not workspace/navigation/chrome. `webgl_limit` (1–4, default 4) constrains inline model/environment/material and workspace viewers. `auto_rotate` (default true) initializes model viewers, with a local manual override. `gallery_limit` (1–100, default 24) controls recent Concepts/Jobs pages, resetting offset on change, not complete-library 100-row paging or all-page active-job counts. Missing/malformed values use manifest defaults. Reopen off-screen cards if contexts are constrained. Keep an ordinary link/file fallback.
- Verify cancellation by reading original job status; a running job may no longer be cancellable. Deletion and metadata replacement require explicit scope confirmation and readback.
- Final delivery: actual successful output exists and is nonempty; every stated metric was measured; all IDs are labeled correctly; costs/partial success are disclosed; promised chat wake is armed; every named attachment appears exactly once.

## Pitfalls

- A Desktop viewer is not model observation. Inspect image pixels through a vision-capable tool; measure meshes/audio with local tools. Downloaded, reopened-validated, visually reviewed, artist-approved and engine-tested are distinct states.
- Do not reuse provider job IDs as Concept IDs, session upload IDs as asset IDs, or Desktop directive attributes as remote tool arguments.
- Presigned download URLs and `s3://` URIs are ordinary delivery locations. Keep API keys and presigned POST policy/signature fields secret. Resolve expired asset links instead of regenerating.
- Factory-startup Blender is a separate process, not a security sandbox. Local decimation is not quad retopology. Never trim/fade a loop or call it seamless without checking the delivered file.
