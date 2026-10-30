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

Schemas constrain shape, not value provenance. The following is a mandatory boundary API, not
an optional lint. S06 implements it in `gateway/redaction.py`; S07 wraps its output as mediated
values. `tests/contracts/support.py:validate_mediated_v1` is a conformance oracle only: tests of
this oracle do NOT claim that the unwritten runtime has integrated it or exercised all sinks.

Frozen signatures (Python notation; these internal names are not additional leaf exports):

    validate_mediated_v1(contract_ref: str, candidate: object, *,
                        scope_id: str, generation: int,
                        sensitive_values: Collection[str]) -> MediatedValue
    validate_candidate_inputs_v1(tool: str, schema_hash: str, candidate: object, *,
                                 scope_id: str, generation: int,
                                 sensitive_values: Collection[str]) -> ValidatedCandidateInputs

Both refuse with `BoundaryRefused(code="UNSAFE_PAYLOAD")`, containing no candidate values,
paths, schema validation dumps or raw exception chain. `MediatedValue` and
`ValidatedCandidateInputs` are immutable wrappers created only by these validators; never
construct them from browser/model booleans. Sensitive values are backend-owned: active API key,
volatile upstream presigned fields/credentials/signatures and their recognized encodings. Do not
persist/log the registry, and do not replace it with only a hard-coded test-canary prefix. S06
must inspect all channels in DESIGN §2.4, parse embedded/fenced JSON, scan residual text and
unknown credential-shaped values, and refuse unclassified paths/variants. A bare high-entropy
secret cannot be distinguished from an ordinary hash by JSON Schema; provenance and exact-value
comparison are mandatory even when shape validation succeeds.

Mandatory callers and ordering:

- S05 IPC send/receive and S11 backend IPC client validate the COMPLETE IpcRequestV1/IpcResponseV1
  envelope, not just payload fragments. Validate MAC/nonce/peer, bind scope/generation, match
  requestId and result.method to the outstanding request, then consume; never log raw envelopes.
  Every method's params are closed and selected by its method discriminator; each successful
  result is a closed `{method, payload}` union. `ok` selects exactly result or error.
- S06/S07 validate GatewayResultV1 after classification/mediation and before tool return,
  progress, transcript/directive props or MEDIA paths. Raw upstream responses never inhabit
  these types. S11 validates ErrorV1 before emitting/logging even when a failure occurs inside
  validation; emit a static safe fallback on refusal. No raw exception interpolation.
- S11 validates QuoteRequestV1 as a RAW CANDIDATE boundary before any IPC, logs, provenance or
  metrics. S09 then checks the exact current release-classified tool/schema hash, allowed names,
  required fields, field types/choices/bounds, canonical effective inputs and reviewed asset/handle
  transforms through validate_candidate_inputs_v1. Reject secret-bearing keys and values before
  forwarding; do not silently strip them and continue billing. No unrestricted input object is
  execution authority. CandidateInputsV1's finite typed JSON is only a transport ceiling.
- S08 validates every ToolInputSchemaV1 projection and all field-name/description/default/choice
  VALUES, not only schema property names. Enforce depth <=8, <=256 nodes, <=65536 encoded bytes,
  unique field names, consistent types/bounds/defaults/choices and exact live/classified hash.
  Unsupported constructs yield SCHEMA_UNAVAILABLE and disable execution; no remote `$ref`, HTML
  or executable patterns. S11 repeats validation on retrieval; S23 verifies current tool/hash
  binding and limits before form rendering, never trusts schema arrival as execution authority.
- S11 and owning leaves S12-S15/S18/S20 validate all outbound dashboard envelopes and persisted
  metadata/provenance; S16/S23 accept only these mediated forms. Browser code never has the
  secret registry or IPC capability and cannot attest secret safety itself.

Ceilings: reject >1 MiB JSON before parsing, non-finite numbers, excessive traversal (>48 total
wire levels or >100000 visited values), and all type-specific bounds before serializing.
Resource-group cumulative sizes and unique frame/resource relations, authenticated scope/generation,
handle purposes/expiry/read limits, and resolve/open/fstat root checks remain mandatory S07/S11
checks. uploads.putChunk's <=65536 integer bytes are explicitly upload content, not display JSON;
S13 binds upload ID, offset/idempotency and total bytes to the scoped session, asserts ALL outgoing
presigned fields and never logs the bytes. Other strings do not gain a binary escape hatch.

The generic conformance oracle exercises complete real-sink envelopes with every S02 canary and
nested presigned URL refusal, safe-ID survival and sanitized errors. S06/S07/S11 must rerun those
cases against their REAL implementations and real logging/forwarding/store spies before their
slice acceptance; an oracle pass is not end-to-end secret-flow proof.
