# hermes-studiotwin leaf exports v1 (frozen, S03)

Contract: `studiotwin.leaf-exports.v1`. Exact-match. A leaf that does not match its kind exactly
(a missing export, an extra export, or a different signature) is refused at registration. Nothing is
adapted or guessed.

DESIGN §9 preamble and D25: leaf modules export only through these frozen shapes. No leaf edits a
shared router or registry. S28 is the only post-leaf owner of `gateway/router.py`,
`dashboard/router.py`, `src/registry.ts` and `src/plugin.tsx`.

## Integration facts (checked against pinned core 088f657)

- The dashboard process loads the plugin's dashboard api file by path and mounts its module-level
  FastAPI `router` under `/api/plugins/<name>`:
  `hermes_cli/web_server_dashboard.py:1231-1237` (`getattr(mod, "router", None)`, then
  `app.include_router(router, prefix=f"/api/plugins/{plugin['name']}", ...)`).
- The isolated plugin host child does the same in a fresh FastAPI app:
  `hermes_cli/plugin_host_child.py:318-322` (`getattr(module, "router", None)`, then
  `app.include_router(router)`).
- So core sees exactly one router per plugin. `dashboard/plugin_api.py` (S11) is the file core
  imports. `dashboard/router.py` (S28) aggregates every backend leaf router into it. Leaf routers
  declare paths relative to the §5 table (e.g. `/assets/{uuid}`). They add no
  `/api/plugins/...` prefix, because core adds it.
- Desktop contributions use the `PluginContribution` shape declared in `src/sdk.d.ts:72-81`
  (`id`, `area`, optional `title`, `order`, `when`, `enabled`, `data`, `render`). `src/registry.ts`
  (S28) imports each leaf's `contribution`, and `src/plugin.tsx` (S28) registers them.

## Export kinds

Each Python leaf declares `__all__` equal to its exact export list. Each Desktop leaf module has
exactly one `export` statement. The fenced block below is the machine-readable source;
`tests/contracts/test_leaf_exports.py` parses it, and S28's registration test may reuse
`tests/contracts/leaf_check.py`.

```json leaf-exports
{
  "contract": "studiotwin.leaf-exports.v1",
  "compatibility": "exact-match",
  "onMismatch": "refuse",
  "kinds": {
    "gateway": {
      "path": "gateway/leaves/<name>.py",
      "exports": ["register_gateway"],
      "signatures": {
        "register_gateway": "def register_gateway(registry: GatewayRegistry) -> None"
      }
    },
    "backend": {
      "path": "dashboard/services/<name>.py",
      "exports": ["SERVICE_ID", "router"],
      "signatures": {
        "SERVICE_ID": "SERVICE_ID: Final[str] = \"<name>\"",
        "router": "router: APIRouter = APIRouter()"
      }
    },
    "desktop": {
      "path": "src/**/<module>.ts(x), as listed by src/registry.ts",
      "exports": ["contribution"],
      "signatures": {
        "contribution": "export const contribution: PluginContribution"
      }
    }
  },
  "leaves": {
    "gateway/leaves/image.py": "S12",
    "gateway/leaves/upload.py": "S13",
    "gateway/leaves/jobs.py": "S14",
    "gateway/leaves/concepts.py": "S15",
    "dashboard/services/images.py": "S12",
    "dashboard/services/uploads.py": "S13",
    "dashboard/services/jobs.py": "S14",
    "dashboard/services/concepts.py": "S15",
    "dashboard/services/audio.py": "S18",
    "dashboard/services/env.py": "S20"
  },
  "integrationOwner": "S28",
  "integrationFiles": ["gateway/router.py", "dashboard/router.py", "src/registry.ts", "src/plugin.tsx"]
}
```

## Rules per kind

- **gateway**: `register_gateway(registry)` takes exactly one positional parameter named `registry`
  with no default, and is annotated `-> None`. It registers the leaf's tools on the registry it is given.
  It never imports `gateway/router.py` and never reaches a global registry.
- **backend**: `SERVICE_ID` is a module-level string literal equal to the module's file stem
  (`dashboard/services/jobs.py` → `"jobs"`), matching `^[a-z][a-z0-9_]{0,31}$`. `router` is a
  module-level `APIRouter(...)` call with no `prefix=` argument. The leaf never includes another
  router and never mounts itself.
- **desktop**: exactly one export, `export const contribution: PluginContribution = ...`. No
  default export, no `export *`, no re-exports, no other named export.

## Values the contracts cannot prove

Schemas constrain shape. A bare high-entropy token (for example a 64-hex signature) looks the same
as a hash or an ID, so the contracts cannot reject it by shape. Value provenance stays with S06/S07
mediation: their redactor and handle tests must prove no StudioTwin secret value reaches a contract
field.
