# V01 backend handoff

> Historical slice notes, not the current release/install guide. Routes and verification
> commands below describe V01 at its own revision; later changes can supersede them.
> Use [development](development.md) and [compatibility](compatibility.md) for current
> isolated verification and evidence boundaries. In particular, old reference paths,
> hard-coded assertions and successful fixture runs are not current-host install proof.

## Architecture

The agent connects directly to `https://api.studiotwin.ai/mcp` through portable
Agent Plugins v1 `mcp.json`. Hermes owns paid-tool approval (`trust: untrusted`,
1500-second timeout, credits table). There is no local MCP server, TCP IPC,
opaque resource table, reservation ledger or plugin session spend limit.

The Desktop host imports `dashboard/plugin_api.py` by file path and mounts its
`router`. It owns request authentication and profile context. The backend reads
`agent.secret_scope.get_secret("STUDIOTWIN_API_KEY")`,
`hermes_cli.config.load_config_readonly()` and `get_hermes_home()` at request time.
Nothing reads credentials or opens storage at import. The backend only performs
reads, upload sessions/completion and queued-job cancellation, not paid generation.

`studiotwin_client.py` implements the MCP initialize/initialized/tools-call
exchange over httpx, including JSON and SSE responses and optional session
cleanup. Credentialed redirects must retain the exact scheme/host/effective port,
with no userinfo. Storage requests do not carry the API key. They permit the API
origin (including loopback tests), HTTPS S3 endpoints and assets.studiotwin.ai;
redirects must stay on the initial origin. Remote error bodies and exception text
are not echoed because they can contain credentials or upload form secrets.
Signed GET URLs and `s3://` URIs are returned intact.

## Backend contract for viewer/workspace slices

All routes are relative to `/api/plugins/hermes-studiotwin`.

- GET `/status`: configured, key_env, settings, balance, host.ffmpeg and
  host.conversions. Missing keys are a normal configured=false state; provider
  errors are reported in error without leaking remote diagnostics.
- GET `/assets?type=&limit=`: `{configured, assets}`. Merges cloud rows, validated
  asset-index.json entries and studio_cache files, with local_path and made_from.
  Supported filters are the captured API types, including legacy jpg/png aliases.
- GET `/assets/{uuid}`: resolved metadata, downloadUrl, s3Uri, local_path,
  made_from. Links remain unredacted.
- GET `/file?path=&asset=&task=&format=&raw=`: exactly one of path or asset.
  Asset UUIDs download once into studio_cache and then work from cache offline.
  Task is optional attribution, not a download instruction. Default JSON is
  `{name, bytes, mtime, mime, dataUrl}`. raw=1 returns bytes. A Range header also
  selects bytes, supporting one normal/open-ended/suffix range, HTTP 206 with
  Content-Range, and HTTP 416 with `bytes */size`. Every binary response advertises
  Accept-Ranges. Bodies are bounded at 128 MiB so the isolated host can serialize
  Response bytes without special streaming support.
- `/file` format=mp3|wav|ogg|flac converts audio with local ffmpeg (45-second
  timeout), with range support over the converted representation. Missing ffmpeg
  returns 409. No network protocols are enabled for ffmpeg input; input is piped
  from the already admitted file descriptor. Original is the default format.
- GET `/jobs?limit=&offset=`: `{jobs}` containing provider records.
- GET `/jobs/{job_id}` and `/task?id=`: provider job record plus id/progress.
  Progress is 100 for success, otherwise provider-reported or null, never an
  invented intermediate percentage. Outputs preserve delivery URLs/URIs.
- GET `/active?tasks=uuid,uuid`: `{configured,tasks,done,missing,failed}`; maximum
  16 deduplicated UUIDs. Reads nothing when the input is empty.
- POST `/jobs/{job_id}/cancel`, POST `/cancel` JSON `{id}` (jobId also accepted).
  The server decides whether the job is still cancellable; no submit/retry path.
- GET `/concepts?limit=&offset=`, `/concepts/{uuid}`,
  `/concepts/{uuid}/status`: captured ConceptLab response shapes.
- POST `/upload`: local upload. JSON `{filename,data:base64,cloud?:true}` or one
  multipart file. Query cloud=true opts into cloud upload. POST `/uploads` always
  uploads to cloud. Local files live in uploads/ with unique names. The cloud
  sequence is upload_asset -> presigned S3 multipart POST -> complete_asset_upload.
  Only local metadata and completed asset records return to the browser, never
  the POST form policy/signature. TAR entry tables are derived without extraction;
  traversal paths and link entries are rejected before network calls. Optional
  JSON entries must match the actual archive.
- POST `/provenance`: `{id, sourceAssetIds?, outputAssetIds?, jobId?, conceptId?,
  prompt?, tool?, session_id?}`. jobId/task_id can identify a record when id is
  absent. All object IDs are UUIDs. Partial upserts merge without erasing previous
  fields. GET `/provenance?id=` and `/details?id=` return
  `{id,record,parents,children,made_from,recorded}` from local provenance.json.
- GET `/actions?id=&type=`: `{id,type,actions}`. Media-type hints include image,
  3d_model, animation, environment and texture. type=job polls the job and only
  offers actions on success. With no hint, resolve the asset, falling back to a
  job on 404. Each action carries tool, cost (null when variable), cost_label and
  a visible composer message requiring live schema/compatibility checks, an exact
  estimate and approval. The route never executes the action.

Allowed local roots: the plugin data root, HERMES_HOME/cache/generated and the
user home. Absolute paths only, no traversal or symlinks, and only the explicitly
listed media extensions. POSIX reads walk no-follow directory descriptors and
hold the final descriptor through serving. This is a media file policy, not an
execution sandbox. Windows is not exercised in this slice.

## Pricing declaration caveat

The requested table has 27 entries: 24 captured generation functions and 3
Concept generation/edit operations. One of those 24 functions, tripo-rig-check,
is explicitly zero-cost in the snapshot and remains 0. Fixed values are copied
from the capture. Concept ranges are the approximate ranges in its descriptions.
The other input-dependent functions publish no numeric bounds in that capture;
the [1,100] intervals are explicitly labelled illustrative UI estimates, NOT
provider maxima or guaranteed prices. Their notes require a fresh
studiotwin_estimate_cost with exact inputs before approval. No maximum is enforced
by this plugin or promised by these ranges. Review must not mistake the illustrative
interval for published StudioTwin pricing.

## Verification and reproducibility

Use a separate test venv, not the live Hermes runtime:

    python -m venv .venv
    .venv/bin/python -m pip install -r requirements-test.txt
    npm ci --ignore-scripts
    PYTHONPATH=/path/to/reference/hermes-agent .venv/bin/python -B tools/verify_v01.py

The verifier writes real output to evidence/v01/: host-validation.json,
pytest.txt, node-scaffold.txt and two mutation logs. It checks real host admission,
all Python tests, the locked Node scaffold, then mutates production Range and
redirect handling in disposable copies. Both mutations must fail assertions.

Also exercised on Python 3.11 with:

    PYTHONPATH=/path/to/reference/hermes-agent UV_CACHE_DIR=$TMPDIR/v01-uv-cache-t_0e8070b8 UV_PYTHON_INSTALL_DIR=$TMPDIR/v01-python-t_0e8070b8 .venv/bin/uv run --python 3.11 --no-project --with-requirements requirements-test.txt python -B -m pytest -q --tb=short

Keep the uv package cache OUTSIDE the checkout: the host security scanner correctly
rejects compiled dependencies and escaping interpreter symlinks if an embedded uv
cache is scanned as plugin source. The first 3.11 probe exposed that layout error;
moving the cache to profile scratch restored clean admission without disabling checks.

The retained fixture suite originally imported two files removed during teardown.
Only its test-only marker helper/data were restored, with a v2 note explicitly
rejecting blanket URL redaction. No production gateway or policy module returned.
Old S11 backend tests were replaced; scaffold Python assertions were migrated from
removed stdio/expert/credit-ledger contracts to v2 remote transport and settings.
The frozen Node manifests and runner were not changed. Runtime uv.lock was refreshed
for httpx only; test dependencies live separately in requirements-test.txt.

No live StudioTwin account, paid generation, Desktop UI render or Windows execution
was attempted. Node npm audit reports inherited dev-toolchain vulnerabilities;
follow-up t_d6dee7c0 routes that decision to Tris without changing the frozen runner.
Salt review is the next task, t_63fab6b5; implementation completion is not release approval.
