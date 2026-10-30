"""S03 frozen protocols: gateway-v1, host-gateway-v1 and dashboard-v1.

DESIGN §9 S03: incompatible versions and settlement-evidence conflation fail closed. The suite
also pins §7.1 AuthorizationV1 field classification, D31 host-context gating, the D11 spend-guard
key, D23 scope tuple, D09/D20 opaque handles and the §5 dashboard route table, and validates the
S02 fixtures (tests/fixtures/contracts/**, read-only) against the contract types.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

sys.dont_write_bytecode = True
_SUPPORT = Path(__file__).resolve().parent / "support.py"
_spec = importlib.util.spec_from_file_location("st_contract_support", _SUPPORT)
S = importlib.util.module_from_spec(_spec)
sys.modules["st_contract_support"] = S
_spec.loader.exec_module(S)

# Import S02's fake from tests/fixtures directly (pinned core shadows `tests`).
sys.path.insert(0, str(S.FIXTURES))
from fake_mcp import MODES, FakeStudioTwin, catalog  # noqa: E402
from fake_mcp import canaries as CAN  # noqa: E402

assert Path(catalog.__file__).resolve().is_relative_to(S.FIXTURES), catalog.__file__

UUID = "000010b5-0006-4000-8000-000000000006"
SCOPE_ID = "a" * 64
OP_ID = "op_" + "A" * 43
HANDLE = "sth_" + "b" * 43
HASH = "c" * 64


@pytest.fixture(scope="module")
def docs():
    return S.documents()


# ------------------------------------------------------------------------------------ fixtures

def scope_tuple(**kw):
    t = {"profileId": "profile-default", "connectionId": "conn-local", "endpointOrigin": "https://staging.studiotwin.invalid",
         "accountId": "acct-1", "orgId": "org-1"}
    t.update(kw)
    return t


def interim_auth(**kw):
    a = {
        "protocol": S.GATEWAY_PROTOCOL, "operationId": OP_ID, "scopeId": SCOPE_ID,
        "trustedSessionId": "session-1", "runKind": "interactive", "runId": "session-1",
        "tool": "text-to-environment-map", "schemaHash": HASH, "canonicalInputHash": HASH,
        "enforcementMode": "interim-local", "previewId": "pv_" + "d" * 43, "previewPriceVersion": None,
        "previewExpiresAtMs": 1793356800000, "estimatedCredits": 20, "maxCredits": 20,
        "expiresAtMs": 1793356800000, "createdAtMs": 1793356500000,
        "consent": {"channel": "mcp-elicitation-form", "action": "accept", "rememberKey": None,
                    "elicitationId": "el_" + "e" * 43},
        "contextSource": "trusted-tool-context-v1",
    }
    a.update(kw)
    return a


def server_auth(**kw):
    a = interim_auth(enforcementMode="server-max-credits", serverQuoteToken="sqt_" + "f" * 43)
    a.update(kw)
    return a


def unknown():
    return {"state": "unknown"}


def evidence(kind, credits, ref=None):
    ev = {"kind": kind}
    if ref:
        ev["ref"] = ref
    return {"state": "reported", "credits": credits, "evidence": ev}


def recon(**kw):
    r = {"protocol": S.GATEWAY_PROTOCOL, "operationId": OP_ID, "scopeId": SCOPE_ID, "jobId": UUID,
         "enforcementMode": "interim-local", "state": "ACCEPTED", "estimatedCredits": 20, "reservedCredits": 20,
         "submissionCost": unknown(), "finalDebit": unknown(), "refund": unknown(), "actualCost": unknown(),
         "reservationHeld": True, "scopePaused": False}
    r.update(kw)
    return r


CURRENT_CORE_CAPS = {
    "protocol": S.HOST_GATEWAY_PROTOCOL, "hostVersion": None, "hostVersionStatus": "unknown",
    "versionSource": "running-distribution-metadata",
    "capabilities": {"trustedToolContextV1": False, "onceOnlyElicitation": True, "noWriteReplay": True,
                     "portableMcpOwnership": True, "pluginBackendNamespace": True,
                     "profileScopedInterpolationFailClosed": True, "gatewayMigration": True},
}


# ------------------------------------------------------------------------- documents and versions

def test_documents_parse_and_are_valid_metaschemas(docs):
    from jsonschema import Draft202012Validator
    Draft202012Validator.check_schema(docs["gateway"])
    Draft202012Validator.check_schema(docs["host_gateway"])
    assert docs["gateway"]["$id"] == S.GATEWAY_ID and docs["host_gateway"]["$id"] == S.HOST_GATEWAY_ID
    assert docs["dashboard"]["openapi"].startswith("3.1.")
    for comp in docs["dashboard"]["components"]["schemas"].values():
        Draft202012Validator.check_schema(comp)


@pytest.mark.parametrize("key,proto", [("gateway", S.GATEWAY_PROTOCOL), ("host_gateway", S.HOST_GATEWAY_PROTOCOL),
                                       ("dashboard", S.DASHBOARD_CONTRACT)])
def test_every_document_declares_exact_match_refusal_policy(docs, key, proto):
    meta = docs[key]["x-studiotwin-version"]
    assert meta == {"contract": proto, "major": 1, "compatibility": "exact-match", "onMismatch": "refuse",
                    "refusalCode": "INCOMPATIBLE_PROTOCOL_VERSION"}


ENVELOPES = [
    ("gateway#/$defs/AuthorizationV1", interim_auth),
    ("gateway#/$defs/ReconciliationV1", recon),
    ("host_gateway#/$defs/HostCapabilitiesV1", lambda: copy.deepcopy(CURRENT_CORE_CAPS)),
]


@pytest.mark.parametrize("ref,make", ENVELOPES)
@pytest.mark.parametrize("bad", ["studiotwin.gateway.v2", "studiotwin.host-gateway.v2", "studiotwin.gateway.v1.1",
                                 "studiotwin.gateway.v0", "v1", "", None, 1, "STUDIOTWIN.GATEWAY.V1"])
def test_incompatible_or_missing_protocol_is_refused(docs, ref, make, bad):
    good = make()
    assert S.errors(ref, good, docs) == []
    inst = make()
    inst["protocol"] = bad
    assert not S.is_valid(ref, inst, docs)
    del inst["protocol"]
    assert not S.is_valid(ref, inst, docs)


def test_cross_protocol_envelope_is_refused(docs):
    """A host-gateway message cannot satisfy a gateway type and vice versa."""
    assert not S.is_valid("gateway#/$defs/AuthorizationV1", interim_auth(protocol=S.HOST_GATEWAY_PROTOCOL), docs)
    caps = copy.deepcopy(CURRENT_CORE_CAPS)
    caps["protocol"] = S.GATEWAY_PROTOCOL
    assert not S.is_valid("host_gateway#/$defs/HostCapabilitiesV1", caps, docs)


def test_version_refusal_shape_is_frozen(docs):
    ok = {"protocol": S.GATEWAY_PROTOCOL, "ok": False,
          "error": {"code": "INCOMPATIBLE_PROTOCOL_VERSION", "supported": [S.GATEWAY_PROTOCOL],
                    "received": "studiotwin.gateway.v2", "message": "gateway speaks studiotwin.gateway.v1 only"}}
    assert S.errors("gateway#/$defs/VersionRefusalV1", ok, docs) == []
    # The refusal never claims to support another version and always names what it got.
    bad = copy.deepcopy(ok)
    bad["error"]["supported"] = [S.GATEWAY_PROTOCOL, "studiotwin.gateway.v2"]
    assert not S.is_valid("gateway#/$defs/VersionRefusalV1", bad, docs)
    bad = copy.deepcopy(ok)
    del bad["error"]["received"]
    assert not S.is_valid("gateway#/$defs/VersionRefusalV1", bad, docs)


def test_ipc_envelope_refuses_other_versions_and_has_no_authorizing_method(docs):
    req = {"protocol": S.HOST_GATEWAY_PROTOCOL, "requestId": "rq_" + "a" * 22, "nonce": "n" * 43,
           "issuedAtMs": 1793356500000, "mac": "0" * 64, "method": "status.get", "params": {}}
    assert S.errors("host_gateway#/$defs/IpcRequestV1", req, docs) == []
    for bad in ("studiotwin.host-gateway.v2", S.GATEWAY_PROTOCOL):
        assert not S.is_valid("host_gateway#/$defs/IpcRequestV1", {**req, "protocol": bad}, docs)
    methods = docs["host_gateway"]["$defs"]["IpcMethodV1"]["enum"]
    assert "operations.quote" in methods
    assert not [m for m in methods if re.search(r"authori[sz]e|approve|consent|dispatch|submit|grant", m)]
    for m in ("operations.authorize", "operations.dispatch", "consent.grant"):
        assert not S.is_valid("host_gateway#/$defs/IpcRequestV1", {**req, "method": m}, docs)
    # A request missing MAC or nonce is not an IPC request (§5.3: nonce + MAC, replay fails).
    for k in ("mac", "nonce", "issuedAtMs"):
        r = dict(req)
        del r[k]
        assert not S.is_valid("host_gateway#/$defs/IpcRequestV1", r, docs)


# ---------------------------------------------------------------------------- AuthorizationV1 §7.1

AUTH_FIELDS = {
    # field: (interim-local, server-max-credits)
    "previewId": ("local-preview", "local-preview"),
    "previewPriceVersion": ("local-preview", "local-preview"),
    "previewExpiresAtMs": ("local-preview", "local-preview"),
    "estimatedCredits": ("local-preview", "local-preview"),
    "maxCredits": ("local-enforced", "server-enforced"),
    "serverQuoteToken": ("absent", "server-enforced"),
    "operationId": ("local-enforced", "local-enforced"),
    "scopeId": ("local-enforced", "local-enforced"),
    "trustedSessionId": ("local-enforced", "local-enforced"),
    "runKind": ("local-enforced", "local-enforced"),
    "runId": ("local-enforced", "local-enforced"),
    "tool": ("local-enforced", "local-enforced"),
    "schemaHash": ("local-enforced", "local-enforced"),
    "canonicalInputHash": ("local-enforced", "local-enforced"),
    "expiresAtMs": ("local-enforced", "local-enforced"),
}


def test_every_authorization_field_is_classified_per_mode(docs):
    auth = docs["gateway"]["$defs"]["AuthorizationV1"]
    props = auth["properties"]
    allowed = {"local-preview", "local-enforced", "server-enforced", "absent", "envelope"}
    for name, schema in props.items():
        cls = schema.get("x-enforcement")
        assert isinstance(cls, dict) and set(cls) == {"interim-local", "server-max-credits"}, name
        assert set(cls.values()) <= allowed, name
        # Nothing is server enforced in interim mode (§7.1: interim is not a hard cap).
        assert cls["interim-local"] != "server-enforced", name
    for name, (interim, server) in AUTH_FIELDS.items():
        assert props[name]["x-enforcement"] == {"interim-local": interim, "server-max-credits": server}, name


def test_interim_max_credits_is_labelled_approved_estimate_never_a_cap(docs):
    labels = docs["gateway"]["$defs"]["AuthorizationV1"]["properties"]["maxCredits"]["x-display-label"]
    assert labels["interim-local"] == "approved estimate"
    assert not re.search(r"cap|max|maximum|limit|guarantee", labels["interim-local"], re.IGNORECASE)
    assert labels["server-max-credits"] == "server-enforced maximum"


def test_authorization_modes(docs):
    ref = "gateway#/$defs/AuthorizationV1"
    assert S.errors(ref, interim_auth(), docs) == []
    assert S.errors(ref, server_auth(), docs) == []
    # Interim mode can never carry a server quote token; server mode must.
    assert not S.is_valid(ref, interim_auth(serverQuoteToken="sqt_" + "f" * 43), docs)
    srv = server_auth()
    del srv["serverQuoteToken"]
    assert not S.is_valid(ref, srv, docs)
    assert not S.is_valid(ref, interim_auth(enforcementMode="hard-cap"), docs)


def test_authorization_requires_trusted_context_and_once_only_elicitation(docs):
    ref = "gateway#/$defs/AuthorizationV1"
    for bad in ({"contextSource": "model-arguments"}, {"contextSource": "absent"},
                {"consent": {"channel": "ctx.rest", "action": "accept", "rememberKey": None, "elicitationId": "el_" + "e" * 43}},
                {"consent": {"channel": "mcp-elicitation-form", "action": "decline", "rememberKey": None,
                             "elicitationId": "el_" + "e" * 43}},
                {"consent": {"channel": "mcp-elicitation-form", "action": "accept", "rememberKey": "always",
                             "elicitationId": "el_" + "e" * 43}}):
        assert not S.is_valid(ref, interim_auth(**bad), docs), bad
    for k in ("consent", "contextSource", "trustedSessionId", "operationId", "canonicalInputHash", "scopeId"):
        a = interim_auth()
        del a[k]
        assert not S.is_valid(ref, a, docs), k


def test_paid_authorization_is_interactive_only_and_concept_paid_is_refused(docs):
    ref = "gateway#/$defs/AuthorizationV1"
    for kind in ("cron", "api", "kanban"):
        assert not S.is_valid(ref, interim_auth(runKind=kind), docs), kind
    for tool in catalog.CONCEPT_PAID_TOOLS:
        assert not S.is_valid(ref, interim_auth(tool=tool), docs), tool
    assert not S.is_valid(ref, interim_auth(tool=catalog.UNCLASSIFIED_TOOL["name"], schemaHash="not-a-hash"), docs)
    assert not S.is_valid(ref, interim_auth(extra="x"), docs)


# ------------------------------------------------------------------- reconciliation (design Q4)

def test_submission_cost_cannot_masquerade_as_final_debit(docs):
    ref = "gateway#/$defs/ReconciliationV1"
    sub = evidence("job-reported-submission-cost", 20)
    assert S.errors(ref, recon(submissionCost=sub), docs) == []
    # Conflation: the job's own cost field placed into the final-debit slot.
    assert not S.is_valid(ref, recon(finalDebit=evidence("job-reported-submission-cost", 20)), docs)
    assert not S.is_valid(ref, recon(refund=evidence("job-reported-submission-cost", 0)), docs)
    assert not S.is_valid(ref, recon(submissionCost=evidence("job-specific-final-debit", 20, "ledger-1")), docs)


@pytest.mark.parametrize("kind", ["wallet-delta", "balance-delta", "account-balance-delta", "inferred", "estimate"])
def test_wallet_deltas_and_inference_are_never_evidence(docs, kind):
    ref = "gateway#/$defs/ReconciliationV1"
    for slot in ("submissionCost", "finalDebit", "refund"):
        assert not S.is_valid(ref, recon(**{slot: evidence(kind, 20, "ref-1")}), docs), (slot, kind)
    assert not S.is_valid(ref, recon(actualCost={"state": "known", "credits": 30, "derivedFrom": kind}), docs)


def test_actual_cost_is_unknown_without_job_specific_final_debit(docs):
    ref = "gateway#/$defs/ReconciliationV1"
    known = {"state": "known", "credits": 20, "derivedFrom": "job-specific-final-debit"}
    # Known actual needs a reported final debit with a ledger reference.
    assert not S.is_valid(ref, recon(actualCost=known, submissionCost=evidence("job-reported-submission-cost", 20)), docs)
    assert not S.is_valid(ref, recon(actualCost=known, finalDebit=evidence("job-specific-final-debit", 20)), docs)
    ok = recon(state="SETTLED", actualCost=known, finalDebit=evidence("job-specific-final-debit", 20, "ledger-1"))
    assert S.errors(ref, ok, docs) == []
    # Unknown is represented as unknown, never as zero or null credits.
    for bad in ({"state": "unknown", "credits": 0}, {"state": "known"}, {"state": "known", "credits": None},
                None, 0):
        assert not S.is_valid(ref, recon(actualCost=bad), docs), bad


def test_settled_states_require_job_specific_evidence(docs):
    ref = "gateway#/$defs/ReconciliationV1"
    debit = evidence("job-specific-final-debit", 20, "ledger-1")
    known = {"state": "known", "credits": 20, "derivedFrom": "job-specific-final-debit"}
    for state in ("SETTLED", "SETTLED_OVERRUN"):
        assert not S.is_valid(ref, recon(state=state, submissionCost=evidence("job-reported-submission-cost", 20)), docs)
    assert not S.is_valid(ref, recon(state="SETTLED", finalDebit=debit), docs)  # actual must then be known
    assert S.is_valid(ref, recon(state="SETTLED", finalDebit=debit, actualCost=known), docs)
    assert not S.is_valid(ref, recon(state="REFUNDED_VERIFIED"), docs)
    assert S.is_valid(ref, recon(state="REFUNDED_VERIFIED", refund=evidence("job-specific-refund", 20, "ledger-2")), docs)
    # Overrun is interim-only, pauses the scope and needs a verified debit above the estimate.
    over = recon(state="SETTLED_OVERRUN", finalDebit=evidence("job-specific-final-debit", 30, "ledger-3"),
                 actualCost={"state": "known", "credits": 30, "derivedFrom": "job-specific-final-debit"}, scopePaused=True)
    assert S.errors(ref, over, docs) == []
    assert not S.is_valid(ref, {**over, "scopePaused": False}, docs)
    assert not S.is_valid(ref, {**over, "enforcementMode": "server-max-credits"}, docs)


def test_unknown_outcomes_never_read_as_unbilled_or_released(docs):
    ref = "gateway#/$defs/ReconciliationV1"
    for state in ("UNKNOWN", "UNKNOWN_NOT_VISIBLE"):
        assert S.is_valid(ref, recon(state=state, jobId=None), docs)
        assert not S.is_valid(ref, recon(state=state, actualCost={"state": "known", "credits": 0,
                                                                 "derivedFrom": "job-specific-final-debit"},
                                         finalDebit=evidence("job-specific-final-debit", 0, "l")), docs)
        # The reservation stays held: never released or shown as spendable.
        assert not S.is_valid(ref, recon(state=state, reservationHeld=False), docs)
    assert S.is_valid(ref, recon(state="RELEASED", jobId=None, reservationHeld=False), docs)
    assert not S.is_valid(ref, recon(state="RELEASED", jobId=None, reservationHeld=True), docs)
    assert not S.is_valid(ref, recon(state="UNBILLED"), docs)


def test_wallet_balance_is_account_context_only(docs):
    ref = "gateway#/$defs/ReconciliationV1"
    ctx = {"level": "account", "balanceBefore": 500, "balanceAfter": 470, "attributedToJob": False}
    assert S.is_valid(ref, recon(accountBalanceContext=ctx), docs)
    assert not S.is_valid(ref, recon(accountBalanceContext={**ctx, "attributedToJob": True}), docs)
    assert not S.is_valid(ref, recon(accountBalanceContext={**ctx, "level": "job"}), docs)
    assert not S.is_valid(ref, recon(accountBalanceContext={**ctx, "deltaCredits": -30}), docs)


def _reconcile_from_fake(mode: str) -> tuple[dict, FakeStudioTwin]:
    """Contract-level reconciliation built from S02 fake output, honouring the evidence rules."""
    fake = FakeStudioTwin(MODES[mode].scenario)
    before = fake.balance
    ack = json.loads(fake.call("text-to-environment-map", {"prompt": "x", "seed": 1}).text)
    job_id = ack["jobId"]
    st = {}
    for _ in range(8):
        st = json.loads(fake.call("studiotwin_get_job_status", {"jobId": job_id}).text)
        if st["status"] in ("done", "failed", "cancelled"):
            break
    r = recon(jobId=job_id, state="ACCEPTED", estimatedCredits=20, reservedCredits=20,
              submissionCost=evidence("job-reported-submission-cost", ack["cost"]),
              accountBalanceContext={"level": "account", "balanceBefore": before, "balanceAfter": fake.balance,
                                     "attributedToJob": False})
    settle = st.get("settlement")
    if settle:
        r["finalDebit"] = evidence("job-specific-final-debit", settle["finalDebitCredits"], settle["ledgerRef"])
        r["refund"] = evidence("job-specific-refund", settle["refundCredits"], settle["ledgerRef"])
        r["actualCost"] = {"state": "known", "credits": settle["finalDebitCredits"], "derivedFrom": "job-specific-final-debit"}
        r["state"] = "SETTLED"
    return r, fake


def test_s02_fake_normal_mode_leaves_actual_cost_unknown(docs):
    r, fake = _reconcile_from_fake("normal")
    assert S.errors("gateway#/$defs/ReconciliationV1", r, docs) == []
    assert r["actualCost"] == {"state": "unknown"} and r["finalDebit"] == {"state": "unknown"}
    assert r["accountBalanceContext"]["balanceBefore"] - r["accountBalanceContext"]["balanceAfter"] == 20
    # Inferring the actual from the wallet delta is a contract violation.
    inferred = {**r, "actualCost": {"state": "known", "credits": 20, "derivedFrom": "wallet-delta"}}
    assert not S.is_valid("gateway#/$defs/ReconciliationV1", inferred, docs)
    # So is promoting the job-reported submission cost to settled.
    promoted = {**r, "state": "SETTLED", "finalDebit": {**r["submissionCost"]}}
    assert not S.is_valid("gateway#/$defs/ReconciliationV1", promoted, docs)


def test_s02_fake_settlement_evidence_mode_settles(docs):
    r, _ = _reconcile_from_fake("settlement_evidence")
    assert S.errors("gateway#/$defs/ReconciliationV1", r, docs) == []
    assert r["state"] == "SETTLED" and r["actualCost"]["credits"] == 20


def test_s02_fake_price_change_interim_is_unknown_until_evidence(docs):
    """The provider charges more than the estimate. At acceptance the wallet surprise is account
    context only; an overrun is declared only from the job-specific final debit."""
    ref = "gateway#/$defs/ReconciliationV1"
    fake = FakeStudioTwin(MODES["price_change_interim"].scenario)
    before = fake.balance
    tool = "text-to-sound-effect"
    est = json.loads(fake.call("studiotwin_estimate_cost", {"functionName": tool, "inputs": {}}).text)["estimatedCost"]
    ack = json.loads(fake.call(tool, {"prompt": "x"}).text)
    delta = before - fake.balance
    assert delta > est
    r = recon(estimatedCredits=est, reservedCredits=est, jobId=ack["jobId"],
              submissionCost=evidence("job-reported-submission-cost", ack["cost"]),
              accountBalanceContext={"level": "account", "balanceBefore": before, "balanceAfter": fake.balance,
                                     "attributedToJob": False})
    assert S.errors(ref, r, docs) == []
    # Without job-specific evidence, neither the wallet nor the submission cost can declare it.
    for derived in ("wallet-delta", "job-reported-submission-cost"):
        over = {**r, "state": "SETTLED_OVERRUN", "scopePaused": True,
                "actualCost": {"state": "known", "credits": delta, "derivedFrom": derived}}
        assert not S.is_valid(ref, over, docs), derived
    st = {}
    for _ in range(8):
        st = json.loads(fake.call("studiotwin_get_job_status", {"jobId": ack["jobId"]}).text)
        if st["status"] == "done":
            break
    settle = st["settlement"]
    assert settle["finalDebitCredits"] > est
    over = {**r, "state": "SETTLED_OVERRUN", "scopePaused": True,
            "finalDebit": evidence("job-specific-final-debit", settle["finalDebitCredits"], settle["ledgerRef"]),
            "actualCost": {"state": "known", "credits": settle["finalDebitCredits"], "derivedFrom": "job-specific-final-debit"}}
    assert S.errors(ref, over, docs) == []


def test_reservation_state_machine_vocabulary_is_frozen(docs):
    states = docs["gateway"]["$defs"]["ReservationStateV1"]["enum"]
    assert states == ["AUTHORIZED", "RESERVED_UNSENT", "DISPATCHING", "ACCEPTED", "UNKNOWN", "UNKNOWN_NOT_VISIBLE",
                      "RELEASED", "EXPIRED", "SETTLED", "SETTLED_OVERRUN", "REFUNDED_VERIFIED"]


# ---------------------------------------------------------------- scope tuple and spend guard

def test_scope_tuple_is_exactly_the_d23_five(docs):
    ref = "gateway#/$defs/ScopeTupleV1"
    assert S.errors(ref, scope_tuple(), docs) == []
    assert docs["gateway"]["$defs"]["ScopeTupleV1"]["required"] == [
        "profileId", "connectionId", "endpointOrigin", "accountId", "orgId"]
    for k in scope_tuple():
        t = scope_tuple()
        del t[k]
        assert not S.is_valid(ref, t, docs), k
    assert not S.is_valid(ref, scope_tuple(sessionId="s"), docs)
    # Origin is a bare https origin: no path, query or userinfo.
    for o in ("https://staging.studiotwin.invalid/mcp", "https://u:p@staging.studiotwin.invalid",
              "http://staging.studiotwin.invalid", "https://staging.studiotwin.invalid?X-Amz-Signature=1"):
        assert not S.is_valid(ref, scope_tuple(endpointOrigin=o), docs), o
    meta = docs["gateway"]["$defs"]["ScopeTupleV1"]["x-trusted-source"]
    assert meta["profileId"] == meta["connectionId"] == "trusted-tool-context-v1"
    assert meta["accountId"] == meta["orgId"] == "authenticated-principal-probe"


def test_spend_guard_key_is_scope_plus_trusted_session(docs):
    ref = "gateway#/$defs/SpendGuardKeyV1"
    d = docs["gateway"]["$defs"]["SpendGuardKeyV1"]
    assert d["required"] == ["scopeId", "trustedSessionId"] and d["additionalProperties"] is False
    assert S.is_valid(ref, {"scopeId": SCOPE_ID, "trustedSessionId": "session-1"}, docs)
    for extra in ({"profileId": "p"}, {"toolCallId": "t"}, {"sessionIdSource": "model"}):
        assert not S.is_valid(ref, {"scopeId": SCOPE_ID, "trustedSessionId": "s", **extra}, docs)
    assert not S.is_valid(ref, {"scopeId": "raw-api-key", "trustedSessionId": "s"}, docs)
    pause = docs["gateway"]["$defs"]["ScopePauseV1"]
    assert "trustedSessionId" not in pause["properties"]  # an overrun pause is intentionally scope-wide


# ------------------------------------------------------------------ D31 host context and capabilities

def test_current_core_host_context_is_untrusted_and_carries_no_identity(docs):
    ref = "host_gateway#/$defs/HostContextV1"
    absent = {"protocol": S.HOST_GATEWAY_PROTOCOL, "trusted": False, "reason": "trusted-context-absent-on-host"}
    assert S.errors(ref, absent, docs) == []
    for k, v in (("sessionId", "s"), ("profileId", "p"), ("runKind", "interactive")):
        assert not S.is_valid(ref, {**absent, k: v}, docs), k
    trusted = {"protocol": S.HOST_GATEWAY_PROTOCOL, "trusted": True, "source": "trusted-tool-context-v1",
               "hostInstanceNonce": "h" * 43, "profileId": "default", "connectionId": "conn-local",
               "sessionId": "session-1", "runKind": "interactive", "cronRunId": None, "toolName": "studiotwin_get_job_status",
               "turnId": "turn-1", "toolCallId": "call-1", "callNonce": 1}
    assert S.errors(ref, trusted, docs) == []
    assert not S.is_valid(ref, {**trusted, "source": "model-arguments"}, docs)
    assert not S.is_valid(ref, {**trusted, "runKind": "cron"}, docs)  # cron needs cronRunId
    assert S.is_valid(ref, {**trusted, "runKind": "cron", "cronRunId": "cr-1"}, docs)


def test_trusted_tool_context_wire_is_reserved_meta_with_mac(docs):
    d = docs["host_gateway"]["$defs"]["TrustedToolContextV1"]
    assert d["x-meta-key"] == "hermes.trustedToolContext/v1"
    assert d["x-transport"] == "reserved MCP request _meta, never tool arguments"
    for k in ("hostInstanceNonce", "profileId", "connectionId", "sessionId", "runKind", "toolName", "turnId",
              "toolCallId", "callNonce", "mac"):
        assert k in d["required"], k


def _publication(docs, caps, identity="unproven", tiers=None):
    return {"protocol": S.GATEWAY_PROTOCOL, "hostCapabilities": caps, "principalIdentity": identity,
            "publishedTiers": tiers}


def test_current_core_publishes_no_mutation_or_paid_tier(docs):
    ref = "gateway#/$defs/PublicationDecisionV1"
    caps = copy.deepcopy(CURRENT_CORE_CAPS)
    assert S.errors("host_gateway#/$defs/HostCapabilitiesV1", caps, docs) == []
    assert S.is_valid(ref, _publication(docs, caps, tiers=["setup"]), docs)
    for tiers in (["setup", "hosted-read"], ["setup", "hosted-mutation"], ["setup", "paid"]):
        assert not S.is_valid(ref, _publication(docs, caps, tiers=tiers), docs), tiers
    # Even with the trusted transport, an unproven principal (D24) keeps hosted paths unpublished.
    caps["capabilities"]["trustedToolContextV1"] = True
    caps["hostVersion"], caps["hostVersionStatus"] = "0.22.3", "at-or-above-floor"
    assert not S.is_valid(ref, _publication(docs, caps, "unproven", ["setup", "hosted-read", "paid"]), docs)
    assert S.is_valid(ref, _publication(docs, caps, "proven", ["setup", "hosted-read", "hosted-mutation", "paid"]), docs)


@pytest.mark.parametrize("status", ["unknown", "below-floor"])
def test_unknown_or_old_host_version_is_setup_only(docs, status):
    caps = copy.deepcopy(CURRENT_CORE_CAPS)
    caps["capabilities"]["trustedToolContextV1"] = True
    caps["hostVersionStatus"] = status
    ref = "gateway#/$defs/PublicationDecisionV1"
    assert S.is_valid(ref, _publication(docs, caps, "proven", ["setup"]), docs)
    assert not S.is_valid(ref, _publication(docs, caps, "proven", ["setup", "offline-read"]), docs)


@pytest.mark.parametrize("cap", ["onceOnlyElicitation", "noWriteReplay", "portableMcpOwnership",
                                 "pluginBackendNamespace", "profileScopedInterpolationFailClosed", "gatewayMigration"])
def test_any_missing_required_capability_is_setup_only(docs, cap):
    caps = copy.deepcopy(CURRENT_CORE_CAPS)
    caps["capabilities"].update(trustedToolContextV1=True)
    caps["hostVersion"], caps["hostVersionStatus"] = "0.22.3", "at-or-above-floor"
    caps["capabilities"][cap] = False
    ref = "gateway#/$defs/PublicationDecisionV1"
    assert S.is_valid(ref, _publication(docs, caps, "proven", ["setup"]), docs)
    assert not S.is_valid(ref, _publication(docs, caps, "proven", ["setup", "hosted-read"]), docs)


def test_host_capabilities_reject_unknown_or_missing_flags(docs):
    ref = "host_gateway#/$defs/HostCapabilitiesV1"
    caps = copy.deepcopy(CURRENT_CORE_CAPS)
    caps["capabilities"]["futureFlag"] = True
    assert not S.is_valid(ref, caps, docs)
    caps = copy.deepcopy(CURRENT_CORE_CAPS)
    del caps["capabilities"]["trustedToolContextV1"]
    assert not S.is_valid(ref, caps, docs)
    caps = copy.deepcopy(CURRENT_CORE_CAPS)
    caps["versionSource"] = "imported-module"
    assert not S.is_valid(ref, caps, docs)


# ----------------------------------------------------------------- D09/D20 no secrets, opaque only

def test_no_field_name_can_carry_a_url_key_or_credential(docs):
    for key, doc in docs.items():
        assert S.banned_property_names(doc) == [], key


def test_every_string_is_constrained_or_explicitly_mediated_text(docs):
    loose = []
    for key, doc in docs.items():
        for path, node in S.string_schemas(doc):
            if any(k in node for k in ("enum", "const", "pattern")) or node.get("x-studiotwin-mediated-text") is True:
                continue
            if node.get("format") == "binary" and "/content/" in path:  # raw media/upload byte streams
                continue
            loose.append(f"{key}{path}")
    assert loose == []


def _secret_samples():
    fake = FakeStudioTwin(MODES["normal"].scenario)
    upload = json.loads(fake.call("studiotwin_upload_asset", {}).text)
    resolved = json.loads(fake.call("studiotwin_resolve_asset", {"assetId": "000a55e7-0001-4000-8000-000000000001"}).text)
    samples = [upload["preSignedPost"]["url"], *upload["preSignedPost"]["fields"].values(),
               "s3://fixture-bucket/users/u/assets/a/x.png", "https://x.invalid/a?X-Amz-Signature=abc"]
    samples += [v for v in _strings(resolved) if "://" in v]
    # Signed job-output URLs and storage URIs from a completed fake job (S02 settlement_evidence).
    done = FakeStudioTwin(MODES["settlement_evidence"].scenario)
    job_id = json.loads(done.call("text-to-environment-map", {"prompt": "x", "seed": 1}).text)["jobId"]
    status = {"status": "unpolled"}
    for _ in range(8):
        status = json.loads(done.call("studiotwin_get_job_status", {"jobId": job_id}).text)
        if status["status"] == "done":
            break
    assert status["status"] == "done"
    samples += [v for v in _strings(status) if "://" in v]
    samples += [c["value"] for c in CAN.document()["canaries"]]
    return [s for s in samples if isinstance(s, str) and len(s) > 8]


def _strings(o):
    if isinstance(o, dict):
        for v in o.values():
            yield from _strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from _strings(v)
    elif isinstance(o, str):
        yield o


def _structured_secret_samples():
    """Secret values with URL/URI/path/query/credential-scope structure. A bare signature or token
    (e.g. 64 hex chars) is shape-indistinguishable from a hash or ID; the contract cannot reject
    it by shape, so value provenance stays with S06/S07 mediation (see leaf-exports.md)."""
    return [s for s in _secret_samples() if re.search(r"://|[/?=%&]|^s3:|^data:", s)]


def test_presigned_values_fail_every_patterned_string(docs):
    """Every patterned string in all three contracts rejects every signed URL, presigned POST
    URL/key/credential, storage URI and canary-bearing URL produced by the S02 fake."""
    from jsonschema import Draft202012Validator
    samples = _structured_secret_samples()
    assert len(samples) >= 8 and any("X-Amz-Signature" in s for s in samples) and any(s.startswith("s3://") for s in samples)
    admitted = []
    for key, doc in docs.items():
        for path, node in S.string_schemas(doc):
            if "pattern" not in node or "enum" in node or "const" in node:
                continue
            v = Draft202012Validator({"type": "string", "pattern": node["pattern"], **(
                {"maxLength": node["maxLength"]} if "maxLength" in node else {})})
            for s in samples:
                if v.is_valid(s):
                    admitted.append((key, path, s[:40]))
    assert admitted == []


def test_bare_canaries_and_presigned_fields_are_not_ids_or_handles(docs):
    for value in [c["value"] for c in CAN.document()["canaries"]] + _secret_samples():
        for ref in ("gateway#/$defs/OpaqueHandleV1", "gateway#/$defs/AssetIdV1", "gateway#/$defs/JobIdV1",
                    "gateway#/$defs/OperationIdV1", "gateway#/$defs/ScopeIdV1"):
            assert not S.is_valid(ref, value, docs), (ref, value[:40])


def test_mediated_text_copies_are_identical(docs):
    g = docs["gateway"]["$defs"]["MediatedTextV1"]
    assert docs["host_gateway"]["$defs"]["MediatedTextV1"] == g
    assert docs["dashboard"]["components"]["schemas"]["MediatedTextV1"] == g


def test_mediated_text_rejects_url_and_presigned_shapes(docs):
    text = docs["gateway"]["$defs"]["MediatedTextV1"]
    assert text["x-studiotwin-mediated-text"] is True and text["maxLength"] <= 4000
    ref = "gateway#/$defs/MediatedTextV1"
    assert S.is_valid(ref, "Job 000010b5 is running (estimated charge 20 credits).", docs)
    for s in [x for x in _secret_samples() if "://" in x or "X-Amz" in x or "=" in x]:
        assert not S.is_valid(ref, s, docs), s[:40]
    # Every free-text field in every document routes through MediatedTextV1.
    for key, doc in docs.items():
        for path, node in S.string_schemas(doc):
            if node.get("x-studiotwin-mediated-text") is True:
                assert path.endswith("MediatedTextV1"), f"{key}{path}: inline free text must $ref MediatedTextV1"


def test_handles_are_256_bit_opaque_and_identity_free(docs):
    ref = "gateway#/$defs/OpaqueHandleV1"
    assert S.is_valid(ref, HANDLE, docs)
    for bad in ("sth_short", HANDLE + "x", "sth_" + "b" * 42 + "/", UUID, "s3://b/k", "https://x.invalid/a",
                "sth_" + "b" * 43 + "?sig=1"):
        assert not S.is_valid(ref, bad, docs), bad


def test_gateway_result_carries_only_ids_handles_and_local_media(docs):
    ref = "gateway#/$defs/GatewayResultV1"
    ok = {"protocol": S.GATEWAY_PROTOCOL, "tool": "studiotwin_get_job_status", "status": "ok", "jobId": UUID,
          "assetIds": ["000a55e7-0001-4000-8000-000000000001"],
          "media": [{"localPath": "/data/hermes-studiotwin/scopes/" + SCOPE_ID + "/media/x.png", "handle": HANDLE,
                     "kind": "image", "mime": "image/png", "assetId": "000a55e7-0001-4000-8000-000000000001"}],
          "summary": "done", "operation": None}
    assert S.errors(ref, ok, docs) == []
    bad_media = copy.deepcopy(ok)
    bad_media["media"][0]["localPath"] = "https://fixture-bucket.s3.invalid/x.png?X-Amz-Signature=1"
    assert not S.is_valid(ref, bad_media, docs)
    bad_media["media"][0]["localPath"] = "/tmp/../etc/passwd"
    assert not S.is_valid(ref, bad_media, docs)
    assert not S.is_valid(ref, {**ok, "downloadUrl": "https://x.invalid/a"}, docs)
    assert not S.is_valid(ref, {**ok, "structuredContent": {}}, docs)
    assert not S.is_valid(ref, {**ok, "assetIds": ["s3://fixture-bucket/k"]}, docs)


# ----------------------------------------------------------------------------- dashboard-v1

DESIGN_ROUTES = {
    ("get", "/status"), ("get", "/capabilities"), ("get", "/assets"), ("get", "/assets/{uuid}"),
    ("get", "/assets/{uuid}/content"), ("get", "/assets/{uuid}/thumbnail"), ("get", "/jobs"), ("get", "/jobs/{id}"),
    ("post", "/uploads"), ("put", "/uploads/{id}/content"), ("post", "/uploads/{id}/complete"), ("post", "/provenance"),
    ("get", "/lineage/{asset}"), ("get", "/local/file"), ("post", "/local/audio/convert"), ("post", "/local/env/preview"),
    ("post", "/local/model/stats"), ("post", "/handoff/blender/plan"), ("post", "/operations/quote"),
    ("get", "/operations/{operationId}"),
}
MEDIA_SRC_ROUTES = {"/assets/{uuid}/content", "/assets/{uuid}/thumbnail", "/local/file"}
# Read-only Concept routes: S15 owns dashboard/services/concepts.py but §5 lists no Concept read.
S03_ADDED_ROUTES = {("get", "/concepts"), ("get", "/concepts/{conceptId}"), ("get", "/concepts/{conceptId}/status"),
                    ("post", "/scope-pause/acknowledge"), ("get", "/capabilities/{tool}/input-schema")}


def _routes(doc):
    return {(m, p) for p, ops in doc["paths"].items() for m in ops if m in ("get", "post", "put", "patch", "delete")}


def test_dashboard_route_table_matches_design_section_5(docs):
    d = docs["dashboard"]
    assert d["servers"] == [{"url": "/api/plugins/hermes-studiotwin"}]
    assert _routes(d) == DESIGN_ROUTES | S03_ADDED_ROUTES
    for m, p in S03_ADDED_ROUTES:
        assert d["paths"][p][m]["x-studiotwin-origin"].startswith("S03 addition"), p


def test_no_dashboard_route_authorizes_or_dispatches(docs):
    d = docs["dashboard"]
    for p, ops in d["paths"].items():
        assert not re.search(r"authori[sz]e|approve|consent|dispatch|execute|submit", p), p
        for m, op in ops.items():
            if m in ("get", "post", "put"):
                assert op["x-billing"] == "nonbilling", (m, p)
    quote = d["components"]["schemas"]["QuotePreviewV1"]
    assert quote["properties"]["authorizes"] == {"const": False}
    assert "enforcementMode" in quote["required"] and "authorizes" in quote["required"]


def test_every_dashboard_operation_has_owner_and_versioned_json(docs):
    d = docs["dashboard"]
    owners = set(d["x-studiotwin-owners"])
    for p, ops in d["paths"].items():
        for m, op in ops.items():
            if m not in ("get", "post", "put"):
                continue
            assert op["x-studiotwin-owner"] in owners, (m, p)
            for code, resp in op["responses"].items():
                for ctype, media in resp.get("content", {}).items():
                    if ctype == "application/json":
                        assert media["schema"].get("$ref", "").startswith("#/components/schemas/"), (m, p, code)
                        target = media["schema"]["$ref"].rsplit("/", 1)[1]
                        schema = d["components"]["schemas"][target]
                        assert schema["properties"]["contract"] == {"const": S.DASHBOARD_CONTRACT}, target
                        assert "contract" in schema["required"], target
            # Every request names its contract version; a mismatch is a 412 refusal, never a guess.
            # Media GETs used directly as <img>/<video> src cannot set headers: an absent header is
            # read as v1, a present mismatching one is still refused.
            params = op.get("parameters", [])
            if op.get("x-studiotwin-media-src") is True:
                assert m == "get" and p in MEDIA_SRC_ROUTES, p
                assert {"$ref": "#/components/parameters/ContractHeaderMediaV1"} in params, (m, p)
            else:
                assert {"$ref": "#/components/parameters/ContractHeaderV1"} in params, (m, p)
            assert op["responses"]["412"]["content"]["application/json"]["schema"]["$ref"].endswith("IncompatibleContractV1")
    header = d["components"]["parameters"]["ContractHeaderV1"]
    assert header["in"] == "header" and header["required"] is True
    assert header["schema"] == {"const": S.DASHBOARD_CONTRACT}
    media = d["components"]["parameters"]["ContractHeaderMediaV1"]
    assert media["name"] == header["name"] and media["required"] is False and media["schema"] == header["schema"]
    assert {p for p, ops in d["paths"].items() for o in ops.values() if isinstance(o, dict) and o.get("x-studiotwin-media-src")} == MEDIA_SRC_ROUTES
    refusal = d["components"]["schemas"]["IncompatibleContractV1"]
    assert refusal["properties"]["code"] == {"const": "INCOMPATIBLE_PROTOCOL_VERSION"}
    assert refusal["properties"]["supported"] == {"const": [S.DASHBOARD_CONTRACT]}


def test_dashboard_bodies_refuse_other_contract_versions(docs):
    ref = "dashboard#/components/schemas/UploadCreateRequestV1"
    ok = {"contract": S.DASHBOARD_CONTRACT, "filename": "a.png", "bytes": 10, "mime": "image/png"}
    assert S.errors(ref, ok, docs) == []
    for bad in ("studiotwin.dashboard.v2", None):
        assert not S.is_valid(ref, {**ok, "contract": bad}, docs)
    # Upload creation returns a plugin-local upload ID, never presigned fields.
    resp = docs["dashboard"]["components"]["schemas"]["UploadCreatedV1"]
    assert set(resp["properties"]) == {"contract", "uploadId", "expiresAtMs", "maxBytes"}


def test_asset_content_route_is_the_only_renderer_url(docs):
    d = docs["dashboard"]
    meta = d["components"]["schemas"]["AssetV1"]
    route = meta["properties"]["contentRoute"]
    assert route["pattern"].startswith("^/api/plugins/hermes-studiotwin/assets/")
    assert S.is_valid("dashboard#/components/schemas/AssetV1/properties/contentRoute",
                      "/api/plugins/hermes-studiotwin/assets/000a55e7-0001-4000-8000-000000000001/content", docs)
    for bad in ("https://fixture-bucket.s3.invalid/x", "/api/plugins/hermes-studiotwin/assets/x/content?sig=1"):
        assert not S.is_valid("dashboard#/components/schemas/AssetV1/properties/contentRoute", bad, docs)


def test_asset_listing_never_claims_server_pagination(docs):
    page = docs["dashboard"]["components"]["schemas"]["AssetPageV1"]
    assert "total" not in page["properties"] and "cursor" not in page["properties"]
    assert page["properties"]["windowing"] == {"const": "local"}


# ----------------------------------------------------------------------- S03 remediation R1

def quote_preview(**changes):
    value = {"contract": S.DASHBOARD_CONTRACT, "authorizes": False,
             "enforcementMode": "interim-local", "tool": "text-to-environment-map",
             "executable": True, "disabledReason": None, "previewId": "pv_" + "d" * 43,
             "estimatedCredits": 20, "estimateLabel": "estimated charge",
             "previewExpiresAtMs": 1793356800000, "balance": {"state": "unknown"},
             "guardRemaining": 100, "scopePaused": False}
    value.update(changes)
    return value


def test_r1_b2_exact_interim_server_maximum_contradiction(docs):
    ref = "dashboard#/components/schemas/QuotePreviewV1"
    assert S.errors(ref, quote_preview(), docs) == []
    # Salt's exact reproduction: change only the label in a complete valid preview.
    assert not S.is_valid(ref, quote_preview(estimateLabel="server-enforced maximum"), docs)


def test_r1_b2_server_maximum_is_distinct_from_estimate(docs):
    ref = "dashboard#/components/schemas/QuotePreviewV1"
    server = quote_preview(enforcementMode="server-max-credits",
                           estimateLabel="server-enforced maximum", maxCredits=25)
    assert S.errors(ref, server, docs) == []
    assert server["estimatedCredits"] != server["maxCredits"]
    for bad in (None, -1, "25"):
        assert not S.is_valid(ref, {**server, "maxCredits": bad}, docs)
    del server["maxCredits"]
    assert not S.is_valid(ref, server, docs)
    assert not S.is_valid(ref, quote_preview(maxCredits=20), docs)
    assert not S.is_valid(ref, quote_preview(enforcementMode="server-max-credits",
                                          maxCredits=25), docs)


def concept(**changes):
    value = {"conceptId": UUID, "title": "Cloned study", "conceptType": "object", "status": "idle",
             "activeAssetId": None, "revision": None, "updatedAtMs": None,
             "sourceConceptId": "000a55e7-0001-4000-8000-000000000001"}
    value.update(changes)
    return value


def test_r1_b6_concept_load_more_without_invented_totals(docs):
    ref = "dashboard#/components/schemas/ConceptPageV1"
    # Exact Salt reproduction starts with a valid old-format Concept; only pagination is new.
    item = concept(revision=0)
    del item["sourceConceptId"]
    page = {"contract": S.DASHBOARD_CONTRACT, "items": [item],
            "hasMore": True, "nextCursor": "cc_" + "a" * 43}
    assert S.errors(ref, page, docs) == []
    assert S.errors(ref, {**page, "hasMore": False, "nextCursor": None}, docs) == []
    for changes in ({"hasMore": False}, {"nextCursor": None}, {"total": 10},
                    {"nextCursor": "https://x.invalid/page"}):
        assert not S.is_valid(ref, {**page, **changes}, docs)
    params = docs["dashboard"]["paths"]["/concepts"]["get"]["parameters"]
    assert {p.get("name") for p in params} >= {"cursor", "limit"}
    assert "total" not in docs["dashboard"]["components"]["schemas"]["ConceptPageV1"]["properties"]


def test_r1_b6_cloned_concept_history_preserves_unknowns_and_failed_attempts(docs):
    ref = "dashboard#/components/schemas/ConceptDetailV1"
    entry = {"kind": "generate", "assetId": None, "jobId": UUID, "sourceAssetId": None,
             "state": "failed", "active": False, "createdAtMs": None, "createdAtRaw": "unparseable time",
             "submittedAtMs": 1793356500000, "reconciledAtMs": 1793356800000,
             "failureMessage": "generation failed"}
    detail = {"contract": S.DASHBOARD_CONTRACT, "concept": concept(), "assetIds": [],
              "history": [entry], "historyHasMore": False, "historyNextCursor": None}
    assert S.errors(ref, detail, docs) == []
    attached = {**entry, "kind": "attach", "assetId": UUID, "jobId": None,
                "state": "completed", "active": True, "failureMessage": None}
    detail["concept"]["activeAssetId"] = UUID
    detail["assetIds"] = [UUID]
    detail["history"].append(attached)
    assert S.errors(ref, detail, docs) == []
    assert S.errors(ref, {**detail, "historyHasMore": True,
                         "historyNextCursor": "ch_" + "b" * 43}, docs) == []
    for changed in ({"historyNextCursor": "ch_" + "b" * 43}, {"historyHasMore": True},
                    {"history": [{**entry, "providerDiagnostic": "raw"}]}):
        assert not S.is_valid(ref, {**detail, **changed}, docs)
    bad = copy.deepcopy(detail)
    bad["concept"]["sourceConceptId"] = "s3://private/source"
    assert not S.is_valid(ref, bad, docs)
    params = docs["dashboard"]["paths"]["/concepts/{conceptId}"]["get"]["parameters"]
    assert {p.get("name") for p in params} >= {"historyCursor", "historyLimit"}


def test_r1_q2_presentation_unknown_times_opus_and_quote_observation(docs):
    for name, field in (("AssetV1", "createdAtRaw"), ("JobV1", "submittedAtRaw")):
        ref = f"dashboard#/components/schemas/{name}/properties/{field}"
        assert field in docs["dashboard"]["components"]["schemas"][name]["properties"]
        assert S.is_valid(ref, None, docs)
        assert S.is_valid(ref, "unparseable server timestamp", docs)
        assert not S.is_valid(ref, "https://private.invalid/t?X-Amz-Signature=fixture", docs)
    ref = "dashboard#/components/schemas/LocalAudioConvertRequestV1/properties/targetFormat"
    assert S.is_valid(ref, "opus", docs)
    assert not S.is_valid(ref, "arbitrary-executable", docs)
    asset = {"assetId": UUID, "category": "image", "name": "study", "mime": "image/png",
             "source": "generated", "pinned": False, "createdAtMs": None,
             "createdAtRaw": "unparseable server timestamp", "jobId": UUID,
             "contentRoute": f"/api/plugins/hermes-studiotwin/assets/{UUID}/content",
             "thumbnailRoute": f"/api/plugins/hermes-studiotwin/assets/{UUID}/thumbnail"}
    job = {"jobId": UUID, "functionName": "text-to-environment-map", "status": "done",
           "submittedAtMs": None, "submittedAtRaw": "unparseable server timestamp",
           "terminalAtMs": None, "terminalAtRaw": None, "outputAssetIds": [UUID], "operationId": None}
    assert S.errors("dashboard#/components/schemas/AssetV1", asset, docs) == []
    assert S.errors("dashboard#/components/schemas/JobV1", job, docs) == []
    conversion = {"contract": S.DASHBOARD_CONTRACT, "sourcePath": "/data/source.wav", "targetFormat": "opus"}
    assert S.errors("dashboard#/components/schemas/LocalAudioConvertRequestV1", conversion, docs) == []
    ref = "dashboard#/components/schemas/QuotePreviewV1"
    assert S.errors(ref, quote_preview(observedAtMs=1793356500000), docs) == []
    assert not S.is_valid(ref, quote_preview(observedAtMs=-1), docs)


@pytest.mark.parametrize("root", ["/home/deploy/.hermes/plugins", "/home/alice/My Project", "C:/Users/Alice/My Project/.hermes"])
def test_r1_b3_supported_local_path_syntax(docs, root):
    path = root + "/hermes-studiotwin/scopes/" + SCOPE_ID + "/media/a file.png"
    assert S.errors("gateway#/$defs/ScopedMediaPathV1", path, docs) == []
    assert S.errors("dashboard#/components/schemas/LocalPathV1", path, docs) == []
    assert S.errors("dashboard#/components/schemas/LocalPathV1", root + "/x.glb", docs) == []
    for segment in ("../", "./", "%2e%2e/", "bad?query/", "bad\x00/"):
        bad = path.replace("media/", "media/" + segment)
        assert not S.is_valid("gateway#/$defs/ScopedMediaPathV1", bad, docs)
        assert not S.is_valid("dashboard#/components/schemas/LocalPathV1", bad, docs)


def test_r1_b3_foreign_scope_is_not_authorized_by_valid_syntax(docs):
    ref = "gateway#/$defs/ScopedMediaPathV1"
    path = "/data/hermes-studiotwin/scopes/" + "b" * 64 + "/media/x.png"
    assert S.is_valid(ref, path, docs)  # syntax alone cannot establish current scope
    assert not S.scoped_media_candidate(path, SCOPE_ID, docs)
    assert S.scoped_media_candidate(path, "b" * 64, docs)


def test_r1_b7_dashboard_acknowledgement_is_scoped_and_nonbilling(docs):
    d = docs["dashboard"]
    assert "/scope-pause/acknowledge" in d["paths"]
    op = d["paths"]["/scope-pause/acknowledge"]["post"]
    assert op["x-studiotwin-owner"] == "S11"
    assert op["x-billing"] == "nonbilling"
    assert op["x-ipc-method"] == "scopePause.acknowledge"
    assert op["x-effects"] == {"write": ["scope_pauses.acknowledged_at_ms"],
                               "settlement": "unchanged", "authorization": "forbidden", "dispatch": "forbidden"}
    req = {"contract": S.DASHBOARD_CONTRACT, "scopeId": SCOPE_ID, "operationId": OP_ID}
    reqref = "dashboard#/components/schemas/ScopePauseAcknowledgeRequestV1"
    assert S.errors(reqref, req, docs) == []
    for extra in ({"authorizes": True}, {"settlement": "SETTLED"}, {"dispatch": True}):
        assert not S.is_valid(reqref, {**req, **extra}, docs)
    result = {"contract": S.DASHBOARD_CONTRACT, "scopeId": SCOPE_ID, "operationId": OP_ID,
              "paused": False, "acknowledgedAtMs": 1793356800000, "authorizes": False, "dispatches": False}
    ref = "dashboard#/components/schemas/ScopePauseAcknowledgedV1"
    assert S.errors(ref, result, docs) == []
    for extra in ({"paused": True}, {"authorizes": True}, {"dispatches": True}, {"actualCost": 0}):
        assert not S.is_valid(ref, {**result, **extra}, docs)
    # Executable effect oracle: the only writable column is the pause acknowledgement.
    before = {"scope_pauses.acknowledged_at_ms": None, "settlement": recon(),
              "authorizations": [interim_auth()], "dispatch_count": 1}
    after = copy.deepcopy(before)
    for field in op["x-effects"]["write"]:
        after[field] = result["acknowledgedAtMs"]
    assert after == {**before, "scope_pauses.acknowledged_at_ms": result["acknowledgedAtMs"]}
    # Runtime mismatch oracle refuses foreign scope and stale operation, not an acknowledgement.
    for expected_scope, expected_op in (("b" * 64, OP_ID), (SCOPE_ID, "op_" + "B" * 43)):
        assert not (req["scopeId"] == expected_scope and req["operationId"] == expected_op)


def test_r1_b4_capture_driven_forms_use_classified_hash_bound_schema(docs):
    assert "ToolInputSchemaV1" in docs["gateway"]["$defs"]
    op = docs["dashboard"]["paths"]["/capabilities/{tool}/input-schema"]["get"]
    assert op["x-studiotwin-owner"] == "S11" and op["x-billing"] == "nonbilling"
    forms = []
    for name in ("text-to-environment-map", "text-to-motion-edit", "tripo-retopology"):
        tool = catalog.tool(name)
        form = S.form_projection(tool)
        envelope = {"contract": S.DASHBOARD_CONTRACT, "tool": name,
                    "schemaHash": catalog.schema_hash(tool), "classification": "classified",
                    "inputSchema": form}
        assert S.errors("dashboard#/components/schemas/ToolInputSchemaResponseV1", envelope, docs) == []
        # This consumer walks one normalized representation, not a second tool/field catalog.
        fields = S.form_controls(form)
        assert {p[0] for p in fields} == set(tool["inputSchema"]["properties"])
        assert {p[0] for p in fields if p[2]} == set(tool["inputSchema"].get("required", []))
        forms.append(fields)
        assert S.form_binding(envelope, name, catalog.schema_hash(tool))
        assert not S.form_binding(envelope, name, "0" * 64)
        bad = {**envelope, "classification": "discovered_unclassified"}
        assert not S.is_valid("dashboard#/components/schemas/ToolInputSchemaResponseV1", bad, docs)
        assert not S.form_binding(bad, name, catalog.schema_hash(tool))
    assert len({json.dumps(f) for f in forms}) == 3
    # Nested animation object/frames array is represented, not flattened into opaque prose.
    nested = S.form_projection(catalog.tool("text-to-motion-edit"))
    animation = next(f for f in nested["fields"] if f["name"] == "animation")
    assert animation["schema"]["kind"] == "object"
    assert animation["schema"]["fields"][0]["schema"]["kind"] == "array"
    assert not S.is_valid("gateway#/$defs/ToolInputSchemaV1", {"kind": "object", "rawSchema": {}}, docs)


def resource(asset_id=None):
    return {"resourceId": "res-1", "kind": "image", "assetId": asset_id,
            "libraryState": "indexed" if asset_id else "not-in-library", "mime": "image/png",
            "source": {"kind": "handle", "handle": HANDLE},
            "contentRoute": "/api/plugins/hermes-studiotwin/local/file?handle=" + HANDLE}


def test_r1_b5_grouped_resources_and_remote_processor_sources(docs):
    assert "ResourceGroupV1" in docs["gateway"]["$defs"]
    present = {"state": "present", "resource": resource()}
    absent = {"state": "absent", "resource": None}
    unknown_slot = {"state": "unknown", "resource": None}
    material = {"kind": "material", "maps": {k: present for k in ("albedo", "normal", "roughness", "metalness")}}
    material["maps"]["height"] = absent
    world = {"kind": "world", "outputs": {"skyMap": present, "worldMesh": absent}}
    sequence = {"kind": "image_sequence", "fps": 24,
                "frames": [{"index": i, "name": f"frame-{i}.png", "resource": {**resource(), "resourceId": f"frame-{i}"}} for i in range(2)],
                "manifest": None}
    bare = {"kind": "single", "resource": resource()}
    sequence_with_manifest = {**sequence, "manifest": {**resource(), "resourceId": "sequence-manifest", "kind": "manifest", "mime": "application/json"}}
    for group in (material, world, sequence, sequence_with_manifest, bare, {"kind": "world", "outputs": {"skyMap": unknown_slot, "worldMesh": absent}}):
        assert S.errors("gateway#/$defs/ResourceGroupV1", group, docs) == []
        job = {"jobId": UUID, "functionName": "text-to-environment-map", "status": "done", "submittedAtMs": None,
               "terminalAtMs": None, "outputAssetIds": [], "operationId": None, "outputGroups": [group]}
        assert S.errors("dashboard#/components/schemas/JobDetailV1", {"contract": S.DASHBOARD_CONTRACT, "job": job}, docs) == []
    assert bare["resource"]["assetId"] is None and bare["resource"]["libraryState"] == "not-in-library"
    bad = copy.deepcopy(material)
    bad["maps"]["height"] = {"state": "absent", "resource": resource()}
    assert not S.is_valid("gateway#/$defs/ResourceGroupV1", bad, docs)
    assert not S.is_valid("gateway#/$defs/ResourceDescriptorV1", {**resource(), "assetId": UUID}, docs)
    assert not S.is_valid("gateway#/$defs/ResourceGroupV1", {**sequence, "fps": 0}, docs)
    assert not S.is_valid("gateway#/$defs/ResourceGroupV1", {**sequence, "frames": []}, docs)
    for name, extra in (("LocalAudioConvertRequestV1", {"targetFormat": "opus"}),
                        ("LocalEnvPreviewRequestV1", {"width": 512}), ("LocalModelStatsRequestV1", {})):
        for source in ({"kind": "asset", "assetId": UUID, "variantId": None},
                       {"kind": "asset", "assetId": UUID, "variantId": "variant-1"},
                       {"kind": "handle", "handle": HANDLE}):
            req = {"contract": S.DASHBOARD_CONTRACT, "source": source, **extra}
            ref = "dashboard#/components/schemas/" + name
            assert S.errors(ref, req, docs) == []  # remote Desktop knows only an asset/variant ID or handle
            assert not S.is_valid(ref, {**req, "sourcePath": "/data/guessed.png"}, docs)
        assert not S.is_valid(ref, {"contract": S.DASHBOARD_CONTRACT,
                                    "source": {"kind": "asset", "assetId": "/data/guess"}, **extra}, docs)
    params = docs["dashboard"]["paths"]["/local/file"]["get"]["parameters"]
    assert {p.get("name") for p in params} >= {"path", "handle"}


def test_r1_b5_ambiguous_recovery_candidates_are_not_submission_authority(docs):
    assert "RecoveryCandidatesV1" in docs["dashboard"]["components"]["schemas"]
    value = {"operationId": OP_ID, "state": "multiple", "dispatchAllowed": False,
             "candidates": [{"jobId": UUID, "functionName": "text-to-environment-map", "submittedAtMs": None,
                             "submittedAtRaw": "unknown time", "inputFingerprint": HASH, "match": "possible"}]}
    value["candidates"].append({**value["candidates"][0], "jobId": "000a55e7-0001-4000-8000-000000000001"})
    ref = "dashboard#/components/schemas/RecoveryCandidatesV1"
    assert S.errors(ref, value, docs) == []
    assert not S.is_valid(ref, {**value, "candidates": value["candidates"][:1]}, docs)
    assert not S.is_valid(ref, {**value, "dispatchAllowed": True}, docs)
    assert S.errors(ref, {**value, "state": "not-visible", "candidates": []}, docs) == []
    job = {"jobId": UUID, "functionName": "text-to-environment-map", "status": "unknown", "submittedAtMs": None,
           "terminalAtMs": None, "outputAssetIds": [], "operationId": OP_ID, "recovery": value}
    assert S.errors("dashboard#/components/schemas/JobV1", job, docs) == []


def gateway_result():
    return {"protocol": S.GATEWAY_PROTOCOL, "tool": "studiotwin_get_job_status", "status": "ok", "jobId": UUID,
            "assetIds": [UUID], "media": [], "summary": "done", "operation": None}


def ipc_job_response():
    job = {"jobId": UUID, "functionName": "text-to-environment-map", "status": "done", "submittedAtMs": None,
           "terminalAtMs": None, "outputAssetIds": [], "operationId": None, "summary": "done"}
    return {"protocol": S.HOST_GATEWAY_PROTOCOL, "requestId": "rq_" + "a" * 22, "ok": True,
            "result": {"method": "jobs.get", "payload": {"contract": S.DASHBOARD_CONTRACT, "job": job}}}


def test_r1_b1_ipc_payloads_are_closed_and_method_specific(docs):
    defs = docs["host_gateway"]["$defs"]
    # Structural assertion deliberately kills reopening result to an unrestricted object.
    assert defs["IpcResponseV1"]["properties"]["result"].get("oneOf")
    assert defs["IpcRequestV1"]["properties"]["params"].get("anyOf")
    assert S.errors("host_gateway#/$defs/IpcResponseV1", ipc_job_response(), docs) == []
    ref = "host_gateway#/$defs/IpcResponseV1"
    assert not S.is_valid(ref, {**ipc_job_response(), "result": {"apiKey": "https://x.invalid/?X-Amz-Signature=1"}}, docs)
    assert not S.is_valid(ref, {**ipc_job_response(), "result": {"method": "status.get", "payload": {"arbitrary": {}}}}, docs)
    req = {"protocol": S.HOST_GATEWAY_PROTOCOL, "requestId": "rq_" + "a" * 22, "nonce": "n" * 43,
           "issuedAtMs": 1793356500000, "mac": "0" * 64, "method": "status.get", "params": {"jobId": UUID}}
    assert not S.is_valid("host_gateway#/$defs/IpcRequestV1", req, docs)
    req.update(method="jobs.get", params={"jobId": UUID})
    assert S.errors("host_gateway#/$defs/IpcRequestV1", req, docs) == []
    assert not S.is_valid(ref, {**ipc_job_response(), "ok": False}, docs)


def test_r1_b1_value_aware_refusal_at_complete_real_sinks(docs):
    assert hasattr(S, "validate_mediated_v1")
    secrets = frozenset(c["value"] for c in CAN.document()["canaries"])
    quote = {"contract": S.DASHBOARD_CONTRACT, "tool": "text-to-environment-map", "schemaHash": HASH,
             "inputs": {"prompt": "study", "seed": 1}}
    cases = [("host_gateway#/$defs/IpcResponseV1", ipc_job_response(), ("result", "payload", "job", "summary")),
             ("gateway#/$defs/GatewayResultV1", gateway_result(), ("summary",)),
             ("dashboard#/components/schemas/ErrorV1", {"contract": S.DASHBOARD_CONTRACT, "code": "UNAVAILABLE", "message": "try later"}, ("message",)),
             ("dashboard#/components/schemas/QuoteRequestV1", quote, ("inputs", "prompt"))]
    for ref, good, path in cases:
        assert S.errors(ref, good, docs) == []
        assert S.validate_mediated_v1(ref, good, sensitive_values=secrets, docs=docs) == good
        for secret in [*secrets, *("prefix " + value + " suffix" for value in secrets)]:
            bad = copy.deepcopy(good)
            sink = bad
            for part in path[:-1]:
                sink = sink[part]
            sink[path[-1]] = secret
            with pytest.raises(ValueError, match="^UNSAFE_PAYLOAD$"):
                S.validate_mediated_v1(ref, bad, sensitive_values=secrets, docs=docs)
    # Exact sensitive-value provenance is independent of synthetic canary/credential prefixes.
    opaque_secret = "ordinary-looking-sensitive-value"
    leaked = gateway_result()
    leaked["summary"] = "prefix " + opaque_secret + " suffix"
    assert S.is_valid("gateway#/$defs/GatewayResultV1", leaked, docs)
    with pytest.raises(ValueError, match="^UNSAFE_PAYLOAD$"):
        S.validate_mediated_v1("gateway#/$defs/GatewayResultV1", leaked,
                               sensitive_values=frozenset({opaque_secret}), docs=docs)
    bad = copy.deepcopy(quote)
    bad["inputs"]["nested"] = {"image": "https://x.invalid/object?X-Amz-Signature=fixture"}
    with pytest.raises(ValueError, match="^UNSAFE_PAYLOAD$"):
        S.validate_mediated_v1("dashboard#/components/schemas/QuoteRequestV1", bad, sensitive_values=secrets, docs=docs)
    bad = copy.deepcopy(quote)
    bad["inputs"]["apiKey"] = "innocent-looking-value"
    with pytest.raises(ValueError, match="^UNSAFE_PAYLOAD$"):
        S.validate_mediated_v1("dashboard#/components/schemas/QuoteRequestV1", bad, sensitive_values=secrets, docs=docs)


def test_r1_q1_relational_invariants_have_concrete_negative_fixtures(docs):
    text = S.LEAF_EXPORTS_PATH.read_text()
    assert "```json relational-checks" in text
    checks = json.loads(text.split("```json relational-checks\n", 1)[1].split("```", 1)[0])
    assert set(checks) == {"binding", "estimate", "debit-equality", "overrun", "time-order", "single-use", "guard", "pause"}
    auth = interim_auth()
    context = {"authorization": auth, "reconciliation": recon(), "nowMs": 1793356550000,
               "preview": {**{k: auth[k] for k in ("scopeId", "trustedSessionId", "runKind", "runId", "operationId",
                                                   "tool", "schemaHash", "canonicalInputHash", "previewId", "estimatedCredits",
                                                   "enforcementMode", "previewExpiresAtMs")}, "observedAtMs": 1793356400000},
               "consumed": False, "heldByOtherOperations": 0, "guardLimit": 200, "pauseActive": False}
    assert S.relational_violations(context) == set()
    mutations = [
        ("binding", ("preview", "scopeId"), "b" * 64),
        ("binding", ("preview", "trustedSessionId"), "another-session"),
        ("binding", ("preview", "runId"), "other-run"),
        ("binding", ("preview", "tool"), "text-to-sound-effect"),
        ("binding", ("preview", "schemaHash"), "b" * 64),
        ("binding", ("preview", "canonicalInputHash"), "b" * 64),
        ("binding", ("preview", "previewId"), "pv_" + "b" * 43),
        ("estimate", ("reconciliation", "reservedCredits"), 19),
        ("estimate", ("authorization", "maxCredits"), 19),
        ("time-order", ("nowMs",), auth["expiresAtMs"]),
        ("time-order", ("authorization", "createdAtMs"), 1793356900000),
        ("time-order", ("preview", "observedAtMs"), 1793356900000),
        ("single-use", ("consumed",), True),
        ("guard", ("heldByOtherOperations",), 190),
        ("pause", ("pauseActive",), True),
    ]
    for rule, path, value in mutations:
        bad = copy.deepcopy(context)
        cursor = bad
        for key in path[:-1]:
            cursor = cursor[key]
        cursor[path[-1]] = value
        assert rule in S.relational_violations(bad), (rule, path)
    settled = copy.deepcopy(context)
    settled["reconciliation"] = recon(state="SETTLED", actualCost={"state": "known", "credits": 19, "derivedFrom": "job-specific-final-debit"},
                                      finalDebit=evidence("job-specific-final-debit", 20, "ledger-1"))
    # Complete schema-valid envelope that only a relational validator can refuse.
    assert S.errors("gateway#/$defs/ReconciliationV1", settled["reconciliation"], docs) == []
    assert "debit-equality" in S.relational_violations(settled)
    over = copy.deepcopy(context)
    over["reconciliation"] = recon(state="SETTLED_OVERRUN", actualCost={"state": "known", "credits": 20, "derivedFrom": "job-specific-final-debit"},
                                   finalDebit=evidence("job-specific-final-debit", 20, "ledger-1"), scopePaused=True)
    assert S.errors("gateway#/$defs/ReconciliationV1", over["reconciliation"], docs) == []
    assert "overrun" in S.relational_violations(over)


def test_r1_b4_form_mediation_checks_values_defaults_and_structural_limits(docs):
    form = S.form_projection(catalog.tool("text-to-environment-map"))
    good = {"contract": S.DASHBOARD_CONTRACT, "tool": "text-to-environment-map", "schemaHash": HASH,
            "classification": "classified", "inputSchema": form}
    ref = "dashboard#/components/schemas/ToolInputSchemaResponseV1"
    assert S.validate_mediated_v1(ref, good, sensitive_values=frozenset(), docs=docs) == good
    duplicate = copy.deepcopy(good)
    duplicate["inputSchema"]["fields"].append(copy.deepcopy(form["fields"][0]))
    wrong_default = copy.deepcopy(good)
    next(f for f in wrong_default["inputSchema"]["fields"] if f["schema"]["kind"] == "string")["schema"]["defaultValue"] = 42
    deep = {"kind": "string"}
    for _ in range(10):
        deep = {"kind": "array", "items": deep}
    too_many = {"kind": "object", "fields": [
        {"name": f"branch{i}", "required": False, "schema": {"kind": "object", "fields": [
            {"name": f"leaf{j}", "required": False, "schema": {"kind": "string"}} for j in range(4)]}}
        for i in range(64)]}
    for bad in (duplicate, wrong_default, {**good, "inputSchema": deep}, {**good, "inputSchema": too_many}):
        assert S.is_valid(ref, bad, docs)  # relations/whole-tree bounds need value-aware mediation
        with pytest.raises(ValueError, match="^UNSAFE_PAYLOAD$"):
            S.validate_mediated_v1(ref, bad, sensitive_values=frozenset(), docs=docs)


# ----------------------------------------------------------------------- S02 fixtures vs contracts

def _fixture(name):
    return json.loads((S.FIXTURES / "contracts" / name).read_text(encoding="utf-8"))


def test_tools_list_summary_rows_validate_as_capability_entries(docs):
    summary = _fixture("tools-list-summary.v1.json")
    assert summary["toolCount"] == 45 == len(summary["tools"])
    ref = "gateway#/$defs/CapabilityEntryV1"
    for row in summary["tools"]:
        entry = {"name": row["name"], "family": row["family"], "schemaHash": row["schemaHash"],
                 "fixedCost": row["fixedCost"], "classification": "classified",
                 "executable": not row["conceptPaid"], "disabledReason": "concept-paid-d22" if row["conceptPaid"] else None}
        assert S.errors(ref, entry, docs) == [], row["name"]
        # A paid Concept tool cannot be marked executable.
        if row["conceptPaid"]:
            assert not S.is_valid(ref, {**entry, "executable": True, "disabledReason": None}, docs)
    unclassified = {"name": summary["unclassifiedFixtureTool"], "family": "generation", "schemaHash": HASH,
                    "fixedCost": None, "classification": "discovered_unclassified", "executable": False,
                    "disabledReason": "unclassified"}
    assert S.errors(ref, unclassified, docs) == []
    assert not S.is_valid(ref, {**unclassified, "executable": True, "disabledReason": None}, docs)


def test_current_core_capability_list_is_setup_only(docs):
    summary = _fixture("tools-list-summary.v1.json")
    ref = "gateway#/$defs/CapabilityListV1"
    entries = [{"name": r["name"], "family": r["family"], "schemaHash": r["schemaHash"], "fixedCost": r["fixedCost"],
                "classification": "classified", "executable": False, "disabledReason": "host-trusted-context-absent"}
               for r in summary["tools"]]
    doc = {"protocol": S.GATEWAY_PROTOCOL, "publishedTiers": ["setup"], "agentCallable": ["studiotwin_setup_status"],
           "tools": entries}
    assert S.errors(ref, doc, docs) == []
    assert not S.is_valid(ref, {**doc, "agentCallable": ["studiotwin_setup_status", "text-to-sound-effect"]}, docs)


def test_fake_modes_consumers_are_slice_ids(docs):
    modes = _fixture("fake-modes.v1.json")
    for m in modes["modes"]:
        for c in m["consumers"]:
            assert S.is_valid("gateway#/$defs/SliceIdV1", c, docs), (m["name"], c)
    assert "S10" in next(m for m in modes["modes"] if m["name"] == "settlement_evidence")["consumers"]


def test_concept_effective_inputs_authorize_only_the_vp_function(docs):
    cases = _fixture("concept-effective-inputs.v1.json")
    fn = cases["function"]
    for case in cases["cases"]:
        assert S.is_valid("gateway#/$defs/AuthorizationV1", interim_auth(tool=fn), docs), case["id"]
        action_tool = {"generate": "studiotwin_conceptlab_generate", "edit": "studiotwin_conceptlab_edit"}[case["action"]]
        assert not S.is_valid("gateway#/$defs/AuthorizationV1", interim_auth(tool=action_tool), docs), case["id"]
        # Effective inputs may contain a resolved storage URI; it never enters any contract value.
        src = case["expected"].get("sourceAsset")
        if src:
            assert not S.is_valid("gateway#/$defs/AssetIdV1", src, docs)
