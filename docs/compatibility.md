# Compatibility and evidence boundaries

## Host target

**Tested released agent/backend host: Hermes Agent v0.23.1**, release commit **`3b421578588243f920886e6fe79a6faa87ea026e`**, on Linux with Python 3.14.9. The [release record](https://github.com/NousResearch/hermes-agent/releases/tag/v0.23.1) identifies that immutable revision. The isolated source-host runtime performed actual manifest validation, doctor, PluginManager registration/skill/MCP discovery and backend file-path import. This is agent/backend execution, **not native Desktop acceptance or authenticated private GitHub installation**. The CLI parser, installer and Desktop SDK at that commit were also inspected. Upstream main can move independently.

Portable Agent Plugins v1 `plugin.json` has **no supported `requires_hermes` field**; current host source assigns that gate to catalog metadata. No ignored field or fabricated historical minimum is shipped. The earliest compatible release is **not established**. Direct Git users should use the tested release and rerun compatibility checks on upgrades; private host imports can change. A source checkout may report an unstamped base version `0.0.0`; the immutable release tag/SHA, not that placeholder, identifies this tested host.

## What each check establishes

| Evidence | Establishes | Does not establish |
|---|---|---|
| Captured `tools/list`, server 1.2.4, 2026-10-30 | Deterministic provider names/fields in that fixture | Current live schemas, fresh prices, authenticated service access |
| Python tests / loopback StudioTwin | Behavior under disclosed fixture inputs, including error/approval boundaries | Live provider behavior or real billing |
| Vitest / Chromium / SDK shim | Rendering and interactions in the stated browser harness | Native Electron admission, client-private Git auth or real remote Desktop behavior |
| Real Blender helper execution | Import/export/reopen and measurements for the exercised file/toolchain | Artist approval, engine import, fidelity of every rig/clip |
| Host validate/doctor/load on isolated runtime | The exact checked revision passes those named host gates | A private Git install, native Desktop UI or paid generation |
| Native Desktop acceptance | Only the actual client/backend paths exercised at the reviewed revision | Unexercised operating systems, remote connections or modalities |

Repository evidence directories contain **historical** checks at their own revisions. They are not automatically final-v1 evidence. Keep exact SHA, tool versions, counts/skips, failures and limits with each new run. A generated browser screenshot is not a native Desktop screenshot.

## Remaining acceptance gates

Before release, the integrated candidate needs its own full tests, deterministic Desktop bundle, isolated dependency/admission/doctor/load and install proof against the selected released host. Independent exact-SHA review and native Desktop/client/backend acceptance follow separately. Exercise Library, Jobs, Concepts, local Upload, all supported viewers, scoped Next/composer, downloads/reopen/settings and failures. Remote/private install and OS-specific coverage must be reported individually as tested, blocked or not run.

The documentation recipes do not authorize live uploads, Concept mutation, cancellation, deletion, paid generation or publication. Use existing owned assets/read-only calls first. Cloud mutation and paid tests need separate bounded authorization. An install command template is not a tag, release or catalog listing.

## Known boundaries

- No speech/full-song/general video-generation claim. Motion frame JSON needs an independently verified retarget/import path; environment-to-world is a mesh, not a full authored level.
- Hosted schemas/prices can drift without a plugin release. A live discovery/schema check is required before invoking; fixture counts are never presented as live totals.
- Cards require the native Desktop half and enabled backend. A remote backend install does not install client UI. The app-level UI and profile-scoped backend have different ownership.
- Local helper execution is on the terminal host, which may differ from the backend and Desktop. Fresh Blender processes are not a security sandbox. Optional runtime availability is not guaranteed by installation.
- Preview lighting/exposure is inspection behavior, not an edited source file. Known PNG/HDR regression gates belong to the integrated hardening tests; baseline screenshots do not prove the fix.
- Exact video stepping has [timing inspection limits](video-frame-timing.md#intentional-limits); ordinary playback can work when stepping is unavailable.
- Storage, provenance and links are not permanent cloud-retention guarantees. Back up wanted files and disclose partial output/lineage failures.
