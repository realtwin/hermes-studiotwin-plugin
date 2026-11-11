"""Fake StudioTwin scenario knobs and the named mode registry.

A `Scenario` is a frozen bag of knobs read by `FakeStudioTwin` (state machine) and
`fake_mcp.http` (HTTP harness). `MODES` names the presets later slices use; every mode has a
reachability probe in `tests/fixtures/test_fixture_foundation.py`, and
`tests/fixtures/contracts/fake-modes.v1.json` mirrors this registry.

Defaults are live-faithful to the StudioTwin API `src/mcp/mcp.service.ts` handlers: generation
calls return a text-only JSON acknowledgement (no structuredContent) and job status/list
results are JSON text blocks. Concept tools dual-emit text + structuredContent.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

ACK_STYLES = (
    "live_text_json",  # live: {"jobId","functionName","cost","status","next"} as one text block
    "prose_no_id",  # job created, response is prose with no job id and no structured content
    "empty_content",  # job created, content == []
    "malformed_json",  # job created, text is truncated JSON
    "protocol_error_after_create",  # job created, then a JSON-RPC error is returned
    "timeout_after_create",  # job created, then the handler hangs past the client timeout
)
STATUS_VOCABULARIES = ("api", "described")
TIMESTAMP_STYLES = ("iso", "mixed")
MALFORMED_KINDS = (None, "status_not_json", "concept_schema_violation")
SECRET_ERROR_KINDS = ("result", "protocol")
OPTIONAL_OUTPUTS = ("all", "required_only")
FINAL_STATES = ("done", "failed")


@dataclass(frozen=True)
class Scenario:
    name: str = "normal"
    # --- generation acknowledgement / job lifecycle -------------------------------------
    ack_style: str = "live_text_json"
    hang_seconds: float = 30.0
    # Internal statuses consumed by successive studiotwin_get_job_status polls of one job.
    job_schedule: tuple[str, ...] = ("submitted", "running", "done")
    final_state: str = "done"
    status_vocabulary: str = "api"
    list_visibility_delay: int = 0  # list_my_jobs calls during which a new job is hidden
    timestamp_style: str = "iso"
    optional_outputs: str = "all"
    # --- money ----------------------------------------------------------------------------
    wallet_balance: int = 500
    price_delta: int = 0  # extra credits charged at run time vs the estimate
    price_change_tools: tuple[str, ...] | None = None  # None = every priced tool
    estimate_provider: str = "fixture-provider-a"
    run_provider: str = "fixture-provider-a"
    server_max_credits: bool = False  # enforce `maxCredits` before debit (proposed D30)
    advertise_max_credits: bool = False  # advertise the D30 capability in initialize
    expose_settlement_evidence: bool = False  # proposed: job status carries ledger evidence
    # --- discovery ------------------------------------------------------------------------
    include_unclassified_tool: bool = False
    unclassified_tool_after_calls: int | None = None  # appears mid-session + list_changed
    schema_drift_tool: str | None = None
    # --- secrets / channels ---------------------------------------------------------------
    secret_channels: bool = False
    secret_error: str = "result"
    emit_progress: bool = False
    emit_logs: bool = False
    signed_url_ttl_seconds: int = 3600
    # --- malformed / timing ---------------------------------------------------------------
    malformed: str | None = None
    call_delay_seconds: float = 0.0
    # --- Concepts ---------------------------------------------------------------------------
    concept_active_swap_on_edit: bool = False
    # --- HTTP harness only ------------------------------------------------------------------
    http_json_response: bool = True  # live server is stateless JSON; False = SSE streams
    http_require_api_key: bool = True
    http_rate_limit_first: int = 0
    http_retry_after: str = "1"
    http_redirect: str | None = None  # None | "foreign" | "same_origin"
    http_error_status: int | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        checks = (
            (self.ack_style, ACK_STYLES),
            (self.status_vocabulary, STATUS_VOCABULARIES),
            (self.timestamp_style, TIMESTAMP_STYLES),
            (self.malformed, MALFORMED_KINDS),
            (self.secret_error, SECRET_ERROR_KINDS),
            (self.optional_outputs, OPTIONAL_OUTPUTS),
            (self.final_state, FINAL_STATES),
        )
        for value, allowed in checks:
            if value not in allowed:
                raise ValueError(f"scenario {self.name!r}: {value!r} not in {allowed}")
        if self.http_redirect not in (None, "foreign", "same_origin"):
            raise ValueError(f"scenario {self.name!r}: bad http_redirect {self.http_redirect!r}")

    def with_(self, **changes: Any) -> Scenario:
        return replace(self, **changes)


@dataclass(frozen=True)
class Mode:
    name: str
    scenario: Scenario
    transport: str  # "any" (in-process or HTTP) or "http" (HTTP harness only)
    consumers: tuple[str, ...]
    summary: str


def _m(name: str, transport: str, consumers: tuple[str, ...], summary: str, **knobs: Any) -> Mode:
    return Mode(name, Scenario(name=name, **knobs), transport, consumers, summary)


_ALL_MODES = (
    _m("normal", "any", ("S06", "S07", "S10", "S12", "S13", "S14", "S30"),
       "Live-faithful async lifecycle: text-JSON ack, queued->running->done by polls, outputs with signed URLs."),
    _m("ambiguous_no_structured_content", "any", ("S10", "S14"),
       "Job is created and billed; the ack is prose with no job id and no structuredContent.",
       ack_style="prose_no_id"),
    _m("ambiguous_empty_content", "any", ("S06", "S10"),
       "Job is created and billed; the result content list is empty.", ack_style="empty_content"),
    _m("ambiguous_malformed_ack", "any", ("S06", "S10"),
       "Job is created and billed; the ack text is truncated JSON.", ack_style="malformed_json"),
    _m("ambiguous_protocol_error_after_create", "any", ("S10",),
       "Job is created and billed, then the call fails with a JSON-RPC error.",
       ack_style="protocol_error_after_create"),
    _m("ambiguous_timeout_after_create", "any", ("S05", "S10"),
       "Job is created and billed, then the handler hangs past the caller's timeout.",
       ack_style="timeout_after_create", hang_seconds=30.0),
    _m("delayed_list_visibility", "any", ("S10", "S14"),
       "A new job stays absent from studiotwin_list_my_jobs for the first 2 list calls.",
       list_visibility_delay=2),
    _m("price_change_interim", "any", ("S10", "S23", "S30"),
       "Run selects another provider and charges estimate+12; no server maximum; dispatches once.",
       price_delta=12, run_provider="fixture-provider-b", expose_settlement_evidence=True),
    _m("price_change_server_max", "any", ("S10",),
       "Proposed D30: maxCredits enforced; a run above it returns PRICE_EXCEEDS_MAX before any debit.",
       price_delta=12, run_provider="fixture-provider-b", server_max_credits=True,
       advertise_max_credits=True, expose_settlement_evidence=True),
    _m("max_credits_advertised_not_enforced", "any", ("S10",),
       "Probe trap: the D30 capability is advertised but maxCredits is silently ignored.",
       price_delta=12, run_provider="fixture-provider-b", advertise_max_credits=True,
       expose_settlement_evidence=True),
    _m("settlement_evidence", "any", ("S10",),
       "Proposed API: job status carries job-specific final debit/refund evidence.",
       expose_settlement_evidence=True),
    _m("job_failure", "any", ("S10", "S14"),
       "Jobs end failed with a safe error; the reserved credits are refunded.",
       job_schedule=("submitted", "running", "failed"), final_state="failed"),
    _m("long_running", "any", ("S14", "S24"),
       "Jobs stay running for 50 polls (pano-stickers can run for hours).",
       job_schedule=("submitted",) + ("running",) * 50 + ("done",)),
    _m("insufficient_balance", "any", ("S10", "S23"),
       "Wallet holds 3 credits; priced runs fail with code 40001 and create no job.", wallet_balance=3),
    _m("secret_channels", "any", ("S06", "S07", "S30"),
       "Every result channel carries a unique canary: text, embedded/fenced JSON, structuredContent, "
       "resource links, embedded resources, _meta, isError results, progress and logs.",
       secret_channels=True, emit_progress=True, emit_logs=True),
    _m("secret_protocol_error", "any", ("S06",),
       "secret_channels, but the failing call returns a JSON-RPC error with canaries in message and data.",
       secret_channels=True, secret_error="protocol", emit_progress=True, emit_logs=True),
    _m("new_unclassified_tool", "any", ("S08", "S23", "S30"),
       "tools/list carries the 45 captured tools plus one unclassified billable tool.",
       include_unclassified_tool=True),
    _m("new_tool_midsession", "any", ("S08",),
       "The unclassified tool appears after the first tools/call and tools/list_changed is sent.",
       unclassified_tool_after_calls=1),
    _m("schema_drift", "any", ("S08",),
       "text-to-environment-map keeps its name but gains a required input (schema hash changes).",
       schema_drift_tool="text-to-environment-map"),
    _m("malformed_status", "any", ("S06", "S14"),
       "studiotwin_get_job_status returns an HTML error page as text.", malformed="status_not_json"),
    _m("malformed_concept", "any", ("S06", "S15"),
       "Concept structuredContent violates the captured outputSchema.", malformed="concept_schema_violation"),
    _m("mixed_timestamps", "any", ("S14",),
       "Job timestamps mix ISO-8601 Z, ISO with offset, epoch milliseconds and {$date} forms.",
       timestamp_style="mixed"),
    _m("described_status_vocabulary", "any", ("S14",),
       "Statuses use the tool description's QUEUED/RUNNING/COMPLETE/FAILED words, not the API's.",
       status_vocabulary="described"),
    _m("optional_outputs_omitted", "any", ("S17", "S20"),
       "Jobs return only required outputs (world without skyMap, auto-rig metadata-only).",
       optional_outputs="required_only"),
    _m("expiring_signed_urls", "any", ("S07", "S11"),
       "Signed URLs expire 60 s after issue on the fake clock.", signed_url_ttl_seconds=60),
    _m("slow_calls", "any", ("S05",), "Every tools/call sleeps 0.3 s first.", call_delay_seconds=0.3),
    _m("concept_active_asset_race", "any", ("S15",),
       "Between quote and edit the Concept's active asset swaps A->B, so the submission differs.",
       concept_active_swap_on_edit=True),
    _m("http_sse", "http", ("S05",), "Streamable HTTP with SSE responses (progress/log notifications flow).",
       http_json_response=False, emit_progress=True),
    _m("http_rate_limited", "http", ("S05", "S11"),
       "The first 2 POSTs get HTTP 429 with Retry-After: 1.", http_rate_limit_first=2),
    _m("http_redirect_foreign", "http", ("S05", "S06"),
       "POST /mcp answers 307 to a foreign origin whose Location carries a signed canary.",
       http_redirect="foreign"),
    _m("http_redirect_same_origin", "http", ("S05",),
       "POST /mcp answers 307 to /mcp-moved on the same origin (allowed redirect).",
       http_redirect="same_origin"),
    _m("http_error_body", "http", ("S06", "S11"),
       "POST /mcp answers 502 with a diagnostic body quoting a signed URL canary.", http_error_status=502),
)

MODES: dict[str, Mode] = {m.name: m for m in _ALL_MODES}
if len(MODES) != len(_ALL_MODES):  # pragma: no cover - registry self-check
    raise RuntimeError("duplicate fake mode name")


def mode(name: str) -> Mode:
    return MODES[name]


def scenario(name: str, **overrides: Any) -> Scenario:
    return MODES[name].scenario.with_(**overrides) if overrides else MODES[name].scenario
