# Metadata payload reliability (v1.0.1)

## Changes

- Read-only MCP metadata is projected while streaming. Oversized input strings are replaced with `[inputs too large to display]`, and the owning row gets `inputs_truncated: true`. IDs, status, ordinary prompts and other rows survive.
- Applies to job lists/status, asset lists/resolution and Concept list/detail/status. No binary download limit is raised. Signed HTTPS and `s3://` references remain intact.
- Handles structured results, JSON inside MCP text blocks and SSE. Parsing nested tool JSON does not allocate the original giant text string.
- Input string values have a 16 KiB individual / 64 KiB shared subtree budget. Nested `inputs` cannot restart that budget. Discarded values refund their provisional charge so later small prompts remain available. References are exempt from input string truncation, but still subject to the retained metadata limit.
- Safety limits remain: 8 MiB retained metadata accounting, 128 MiB decompressed wire data, nesting limit, existing HTTP read timeout and origin/redirect guards. Malformed or excessive non-input metadata fails closed with a sanitized 502. These are bounded degradation guarantees, not unlimited-document support. The input budget covers string values; keys, scalar arrays and container overhead remain bounded by the global metadata accounting.
- The background active-jobs chip requests identity/status summaries, not full output maps. It retains only a numeric count in the query cache. It polls every five seconds while jobs are active and every thirty seconds while idle or following errors; tool-completion invalidation still refreshes it.
- Environment preview decoding now uses the fetched filename, never the optional display label. A display label with no extension or a misleading extension cannot select the decoder.

## Evidence

A read-only wallet probe reproduced the original 413: a 24-job MCP reply was 9,940,203 bytes. Four failed jobs contributed 9,874,708 bytes of `inputs`, mostly nested image data URIs. No wallet mutation or paid generation was used.

With this build, the real `/jobs?limit=24&offset=0` route returned 200 and all 24 rows, including four explicitly truncated rows. A final sample was 75,186 response bytes with a 12,710-byte largest row. Exact signed-URL lengths rotate, so healthy response sizes are not constants. The background `limit=100&summary=true` route returned 33 rows in 2,132 bytes (largest row 68 bytes).

A synthetic 12 MiB embedded-text input stream retained a 197-byte JSON result and peaked at 310,809 traced Python allocation bytes in the reader probe. This is a reader allocation measurement, not a whole-Desktop heap measurement.

Regression tests cover >8 MiB input rows through the actual router/client for structured/text/SSE responses; ordinary siblings and exact URLs; nested budgets, UTF-8/escaped Unicode, SSE line endings/comments/multiline data, malformed input and wire limits. Mutation controls fail when streaming is bypassed. Browser tests fail when the environment display-label bug is restored. Polling tests fail when idle polling is restored to five seconds.

Serial local gates:

- Python 3.14.9 focused payload/parser: 27 passed.
- Full Python: 299 passed, 1 skipped, 1 failed. The unchanged base has the **same single failure** (`test_media_generator_reproduces_every_file_byte_for_byte`): this FFmpeg 6.1.1 environment differs on MP3/MP4 golden bytes and their manifest. Base: 272 passed, 1 skipped, 1 failed. Failure identities were compared programmatically; none were introduced. Goldens were not regenerated.
- Node 26.12.1 typecheck/build passed; ordinary Vitest: 334 passed, 39 skipped, zero failures.
- Opt-in Chromium/SwiftShader environment/material lifecycle suite: 13 passed, including HDR/PNG/EXR with a misleading display label.
- The complete opt-in WebGL suite and lowest-declared Python 3.11 were not run in this lane.

## Boundaries and upstream work

The previous five-second background poll repeatedly downloaded large metadata **in the plugin backend**. On a rejected request the browser receives a small error JSON, not the upstream multi-megabyte response. On success the count query returns a number; full rows are transient during scanning, not accumulated by that cache. This distinction matters when investigating renderer memory.

Historical long-session tab-reset causality remains unestablished. Source confirms pooled WebGL cleanup and also uncached/base64 media hydration and mounted data-URL retention. Those are separate media-memory risks, not proof of a crash. Do not call a metadata fix a renderer OOM fix.

Proposed API work: add bounded job-list projections / active-status filters and avoid echoing inline generation inputs into routine history/status responses. The plugin summary mode reduces browser transfer but cannot reduce upstream bytes without such an API contract. Full signed URLs and asset references must remain usable, not redacted.
