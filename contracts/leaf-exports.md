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
  "gatewayRegistry": {
    "definitionOwner": "S08",
    "integrationOwner": "S28",
    "registration": "def add(self, name: str, handler: GatewayHandler) -> None",
    "handler": "async def handler(*, context: GatewayCallContext, inputs: ValidatedCandidateInputs) -> MediatedValue",
    "duplicates": "refuse",
    "unclassified": "refuse",
    "schemaDrift": "refuse",
    "resultContract": "studiotwin.gateway.v1#GatewayResultV1"
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

## GatewayRegistry and callable contract (Q3)

S08 defines `GatewayRegistry`, `GatewayHandler`, `GatewayCallContext` and
`ValidatedCandidateInputs` in its owned `gateway/classification.py`; S06 defines the
`MediatedValue` validation wrapper in `gateway/redaction.py`. Consumers import these names
from those modules, not independent local protocols. S28 supplies a registry instance when
integrating leaves. S05's pre-integration setup-only launcher does not import future leaves.

`registry.add(name, handler)` is synchronous, returns None, and has exactly the signature in
the JSON block. It resolves name and exact current schemaHash through the S08 reviewed-release
classification; leaves do not supply their own hash, policy or raw input schema. Registration
refuses duplicate names (including identical handlers), unknown names, changed hashes and
non-async or signature-incompatible handlers. A new unclassified tool remains discoverable
but never receives a handler. Host/principal/publication gates still decide what is callable.
Registry registration is not paid authorization, and there is no public global registry.

`GatewayHandler` is an async callable with keyword-only `context` and `inputs`, no defaults,
varargs or arbitrary kwargs. Inputs are the immutable `ValidatedCandidateInputs` wrapper,
with exact bound tool/schemaHash, canonicalInputHash, scope_id and generation; it exposes a
read-only `values` mapping containing only the validated effective candidate fields.
`GatewayCallContext` is immutable and supplied by the gateway, never model data. It has:

    scope_id: str
    generation: int
    trusted_context: VerifiedHostContext
    execute: Callable[[ValidatedCandidateInputs], Awaitable[MediatedValue]]

`VerifiedHostContext` is S04's authenticated HostContextV1 wrapper (defined in its owned
`gateway/host_context.py`), not a dict marked trusted by a caller. `execute` is already bound
to this registration's exact tool/hash/scope/generation. S08 provides the facade; S09/S10 own
its consent/ledger/dispatch gates. It rejects a mismatched wrapper. It performs classified reads
or the complete quote/once-only host consent/reserve/submit-once path for paid work; the handler
cannot turn a browser quote into dispatch. Only gateway mediation owns hosted transport.
A typical handler is `return await context.execute(inputs)`; special leaves may compose safe
local presentation but must return a MediatedValue validated as GatewayResultV1. S28 validates
registration and output at runtime. No handler returns raw MCP dictionaries, raw candidate
inputs or unrestricted IPC result objects. The old GOOD_GATEWAY syntax-check fixture tests only
export syntax and intentionally does not establish that its dummy `_tool(args)` is a runnable
registered handler; Q3 requires S08/S28's actual callable validation too.

## Mandatory relational checks (Q1)

These are normative S09/S10 checks, not assertions that JSON Schema compares fields or that
an oracle has executed the real SQLite/consent/dispatch path. The concrete complete-envelope
negative fixtures are in `test_r1_q1_relational_invariants_have_concrete_negative_fixtures`;
`support.relational_violations` is their independent conformance oracle.

```json relational-checks
{
  "binding": "S09/S10: trusted scope/generation/session/run/operation/tool/schemaHash/canonicalInputHash and previewId/mode/expiry must agree across current classified call, preview row, authorization and reservation/reconciliation; interactive runId equals trustedSessionId. Bind consent elicitation ID to this exact in-flight host call, not model/browser assertions.",
  "estimate": "S09: in interim mode approved maxCredits == preview estimatedCredits == authorization estimatedCredits == reservedCredits; never reinterpret it as a remote cap. In server mode reserve the authenticated approved maximum and bind the server token/effective inputs/provider-price version/expiry, not the estimate.",
  "debit-equality": "S10: known actualCost.credits == verified job-specific finalDebit.credits; evidence ref must identify this same-scope operation/job in the authoritative ledger, not wallet delta or a differently scoped job. Refund likewise needs its own verified same-job evidence.",
  "overrun": "S10: interim verified finalDebit > approved estimate iff SETTLED_OVERRUN; atomically create scope pause. Equal/below is not overrun. Server finalDebit above proven max is a capability breach requiring quarantine/escalation, never relabel as an allowed interim charge or release as unbilled.",
  "time-order": "S09/S10: observedAt <= authorization.createdAt <= now < authorization.expiresAt <= previewExpiresAt. Unknown or expired binding cannot authorize; timestamps must come from the bound preview/host clocks, not browser receipt. S10 also enforces submitted <= terminal <= reconciled when known, pause.created <= acknowledged; unknown/raw timestamps remain unknown.",
  "single-use": "S09/S10: atomically verify, consume operationId and insert RESERVED_UNSENT in BEGIN IMMEDIATE; duplicate/restart/timeout returns existing operation, never dispatches. Record DISPATCHING durably before RPC bytes. Only verified pre-send failure/pre-debit rejection releases; ambiguous candidates remain held.",
  "guard": "S09: sum all unreleased reservations for exactly (scope_id, trusted_session_id), plus proposed reservation, <= user-lowered guardLimit. Concurrent checks and insertion share the consumption transaction; no cross-session aggregation or double-count of the same operation.",
  "pause": "S09/S10: unacknowledged verified-overrun pause blocks all new paid operations in that scope, across sessions. S10/S11 acknowledgement compares authenticated current scope/generation and exact pause operationId atomically, only writes acknowledged_at_ms, and never changes settlement, consent or dispatch. Repeated acknowledgement is idempotent; stale acknowledgement cannot clear a newer pause."
}
```

Additional mandatory owning-slice negative integration fixtures: forged consent ID; old-generation
response after rotation; same job ID with a foreign ledger reference; server token bound to other
inputs; reserved estimate != approved estimate; known actual 19 vs verified debit 20; SETTLED_OVERRUN
with debit == estimate; SETTLED without pause when debit > estimate; server debit > maximum; future
observation/created time, expired preview, terminal before submission, acknowledgement before pause;
two concurrent reserves straddling the guard; duplicate consumed operation after restart; foreign
scope/stale-pause acknowledgement; zero or multiple recovery candidates. Assert real store diffs
and RPC/log spies, not just return values. The concrete S03 fixtures execute equality/binding/time/
guard/single-use/pause predicates, but cannot prove atomicity, authentic ledger provenance,
clock correctness, no-replay under crashes or runtime sink integration before S09/S10 exist.

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
