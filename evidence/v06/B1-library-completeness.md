# V06 B1: complete merged Library reads

Remediation for task t_920c0645 and Salt finding B1 at 1fcf7936c391c7eb461f4af144c6e080ba735fb6.

## Behavior

`GET /assets` now accepts a nonnegative `offset` alongside the existing bounded page size (`limit` 1–100, default unchanged), and returns `total` and nullable `next_offset`. It merges cloud/local rows by UUID or local path and applies the existing type predicate before slicing. A cached cloud UUID remains one row. An offset beyond the end returns an empty page with no next offset.

These are plugin API pagination fields only. `studiotwin_list_my_assets` still receives only its actual optional `type`, or `{}` for the complete cloud list. No provider paging, schema extension, local gateway, handle table, reservation or URL redaction was introduced.

Library follows `next_offset` until completion, then applies its existing composite modality and name/prompt/UUID search predicates to the complete merged result. Page size is not a library size cap. Each page uses the existing revocable profile/connection scope. A later-page failure surfaces the retryable library error rather than publishing a truncated result or claiming no matches. Refresh starts a complete read again. Invalid/nonadvancing page offsets fail explicitly instead of looping.

## Regression evidence

- RED: the new real-Chromium/real-router regression against the original implementation failed: 209 expected asset cards, 100 received. Log: `.verification/v06-b1-red.log`.
- GREEN: the same regression passes with 209 mixed cloud/local merged rows across three pages. It discovers the video after 205 cloud images, decodes its actual video in the inspector, searches/inspects a late local image and a cached late cloud image, and verifies deduplication plus page totals/termination. Log: `.verification/v06-b1-green.log`.
- Real-router Python regression covers merged pagination, filtering before slicing, cached UUID deduplication, empty final pages, negative offset/oversized limit validation, exact provider arguments, and local-only pagination without a key.
- Additional Chromium transport-failure case aborts page two, verifies an error without a false no-match message, then refreshes successfully through the real router. This single transport failure is injected; successful asset data is not fabricated/intercepted.
- Focused run: three Library Chromium cases passed; focused backend regression passed. Log: `.verification/v06-b1-focused.log`.
- Final full suites are run on the exact committed HEAD and recorded in the task review handoff and `.verification/v06-b1-{pytest,vitest,typecheck}.log`.

## Boundaries

No install, push, release, paid generation or live authenticated provider call. Host SDK/config/secret/home boundaries remain test doubles; the actual plugin router and loopback HTTP MCP/storage fixture execute. Frozen scaffold/config/SDK and V07 assembly paths remain unchanged.

The provider currently supplies a complete array. Plugin pagination re-reads that array per page rather than inventing an unsupported provider cursor. Loading/rendering costs grow with library size. Offset reads are not a transactional snapshot if the provider library changes during a read; Refresh re-reads the current library. This remediation removes the fixed first-100 visibility defect, not those provider/performance constraints.
