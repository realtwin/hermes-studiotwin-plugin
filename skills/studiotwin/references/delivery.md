# StudioTwin reference: delivery

## Delivery by surface and Desktop directives

Presigned **download URLs** and `s3://` URIs are ordinary delivery links/asset locations. Never redact them merely for being signed; they may appear in chat, logs, reports and visible commands. They may expire (many captured outputs say one hour); resolve the asset again to refresh rather than regenerate. Never expose `st_...` API keys, account credentials or presigned **POST** upload policies/signatures.

- **Desktop:** enable the Desktop half; workspace is `/studiotwin` with Library, Jobs, Concepts and Upload. Use a directive on its own line for a source the backend can actually serve, or an attributed `MEDIA:` file for automatic tool-media cards. Viewers do not themselves prove the agent visually reviewed an asset.
- **Messaging:** download to an absolute path accessible to the gateway, preferably beneath active `<HERMES_HOME>/cache/generated/`. Deliver each attachment once as a standalone `MEDIA:/absolute/path.ext` line. No Desktop directives or markdown images. Include a download link when file-size limits prevent attachment. Report link expiry from actual metadata, not Meshy's three-day policy. A local path in prose is not an attachment.
- **CLI/TUI:** report absolute paths, format, job/asset IDs and useful download links; `MEDIA:` and directives may display as literal text.
- **Remote Desktop:** backend paths belong to the Hermes machine, not necessarily the user's computer. Playback/download streams through scoped backend access. Local processing requires the files and tools on that host.

Directive attributes below come from `src/cards/`, not remote MCP schemas. Substitute real IDs/paths; placeholders are not executable UUIDs. Do not attach a `task` attribute where the renderer expects `id`.
Never put `{` or `}` inside any `::studiotwin-*` directive attribute value: the tested Hermes v0.23.1 parser allows at most 2048 characters inside the outer attribute block, without nested braces. Use flat material channel attributes, not nested JSON. Legacy JSON `maps` remains supported programmatically/tool-media, but cannot pass that transcript parser. Only pass environment stickers when needed, preferably through tool-media; sticker object JSON and object-based video frame sequences cannot pass this directive parser. Use ordinary video `path` or tool-media for those sequences.

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
