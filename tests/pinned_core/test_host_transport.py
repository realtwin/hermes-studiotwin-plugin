"""S04: actual pinned transport/approval primitives plus plugin receiver guards.

Signed fixtures exercise the receiver, NOT a claim that D31 or D24 shipped.
No network, live profile installation, synthetic AuthorizationV1 or paid dispatch.
"""
import asyncio
import copy
import hashlib
import hmac
import importlib.util
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


package = type(sys)("st_gateway")
package.__path__ = [str(ROOT / "gateway")]
sys.modules["st_gateway"] = package
cap = load("st_gateway.capabilities", ROOT / "gateway/capabilities.py")
hc = load("st_gateway.host_context", ROOT / "gateway/host_context.py")
contracts = load("s04_contracts", ROOT / "tests/contracts/support.py")
KEY = b"receiver-fixture-key-not-a-live-secret" * 2
HOST = "H" * 43
FLAGS = ("trustedToolContextV1", "onceOnlyElicitation", "noWriteReplay",
         "portableMcpOwnership", "pluginBackendNamespace",
         "profileScopedInterpolationFailClosed", "gatewayMigration")


def sign(payload, domain):
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    return hmac.new(KEY, domain.encode() + b"\0" + encoded, hashlib.sha256).hexdigest()


def context(session="session-a", nonce=0, **changes):
    value = dict(hostInstanceNonce=HOST, profileId="profile-a", connectionId="local",
                 sessionId=session, runKind="interactive", cronRunId=None,
                 toolName="text-to-material", turnId="turn-a", toolCallId=f"call-{nonce}",
                 callNonce=nonce)
    value.update(changes)
    value["mac"] = sign(value, "trusted-tool-context-v1")
    return value


def gate():
    return hc.HostContextGate(key=KEY, host_instance_nonce=HOST,
                              profile_id="profile-a", connection_id="local")


def handshake(version="0.22.3", **flags):
    value = dict(protocol="studiotwin.host-gateway.v1", hostVersion=version,
                 hostVersionStatus="at-or-above-floor", versionSource="running-distribution-metadata",
                 capabilities=dict.fromkeys(FLAGS, True))
    value["capabilities"].update(flags)
    return value


def authenticated(g, session="session-a", nonce=0, **changes):
    return g.receive(arguments={}, metadata={hc.META_KEY: context(session, nonce, **changes)})


def test_pinned_transport_does_not_serialize_trusted_context():
    from tools import mcp_tool_handlers as transport
    from tools import approval_context as sessions
    assert "reference/hermes-agent" in str(Path(transport.__file__).resolve())
    calls = []

    class Peer:
        async def call_tool(self, name, **kwargs):
            calls.append((name, kwargs))
            return gate().receive(arguments=kwargs["arguments"], metadata=kwargs.get("meta", {}))

    async def run():
        async def one(session):
            token = sessions.set_current_session_key(session)
            try:
                await asyncio.sleep(0)
                assert sessions.get_current_session_key() == session
                return await transport._call_tool_racing_stdio_death(
                    SimpleNamespace(session=Peer()), "studiotwin", "studiotwin_setup_status", {})
            finally:
                sessions.reset_current_session_key(token)
        return await asyncio.gather(one("session-a"), one("session-b"))

    results = asyncio.run(run())
    assert all(r == hc.untrusted("trusted-context-absent-on-host") for r in results)
    assert all(kwargs == {"arguments": {}} for _, kwargs in calls)
    decision = cap.publication_decision()
    assert decision["publishedTiers"] == ["setup"]
    assert cap.published_tools(decision, ["text-to-material", "studiotwin_conceptlab_delete"]) == ["studiotwin_setup_status"]
    assert contracts.is_valid("gateway#/$defs/PublicationDecisionV1", decision)


@pytest.mark.parametrize("field", ["session_id", "sessionId", "cron_run_id", "cronRunId", "approved", "approval", "consent", "authorized", "_meta", hc.META_KEY])
def test_model_fields_are_rejected_even_with_valid_mac(field):
    g = gate()
    result = g.receive(arguments={field: True}, metadata={hc.META_KEY: context()})
    assert result == hc.untrusted("trusted-context-in-model-arguments")
    assert contracts.is_valid("host_gateway#/$defs/HostContextV1", result)


def test_nested_model_metadata_rejected():
    result = gate().receive(arguments={"input": {"session_id": "forged"}}, metadata={})
    assert not result["trusted"]


@pytest.mark.parametrize("tamper", ["sessionId", "cronRunId", "mac", "approved"])
def test_unauthenticated_metadata_is_not_authority(tamper):
    value = context()
    value[tamper] = "forged"
    result = gate().receive(arguments={}, metadata={hc.META_KEY: value})
    assert not result["trusted"]
    assert "sessionId" not in result


def test_replay_peer_and_shape_guards():
    g = gate()
    first = authenticated(g)
    assert first["trusted"]
    assert contracts.is_valid("host_gateway#/$defs/HostContextV1", dict(first))
    assert contracts.is_valid("host_gateway#/$defs/TrustedToolContextV1", context())
    assert authenticated(g)["reason"] == "trusted-context-stale-nonce"
    assert authenticated(g, nonce=1, profileId="other")["reason"] == "trusted-context-wrong-peer"
    assert not authenticated(g, nonce=True)["trusted"]
    assert not authenticated(g, nonce=2, runKind="cron", cronRunId=None)["trusted"]
    assert authenticated(g, nonce=3)["trusted"]


def test_concurrent_authenticated_sessions_and_cross_session_operation_reuse():
    from tools import approval_context as sessions
    g = gate()

    async def run():
        async def one(session):
            token = sessions.set_current_session_key(session)
            try:
                await asyncio.sleep(0)
                current = sessions.get_current_session_key()
                return authenticated(g, current)
            finally:
                sessions.reset_current_session_key(token)
        return await asyncio.gather(one("session-a"), one("session-b"))

    a, b = asyncio.run(run())
    assert a["sessionId"] == "session-a" and b["sessionId"] == "session-b"
    op = g.new_operation(a)
    assert op.startswith("op_")
    assert not g.consume_operation(op, b)
    assert g.consume_operation(op, a)
    assert not g.consume_operation(op, a)
    forged = dict(a, sessionId="session-c")
    assert not g.consume_operation(g.new_operation(b), forged)
    with pytest.raises(ValueError):
        g.new_operation(dict(a))  # copying a wire-shaped dict must not mint authority


@pytest.mark.parametrize("version", [None, "unknown", "0.22.2", "0.22.3-rc.1", "0.21.99", "0.22.3junk"])
def test_unknown_below_floor_or_prerelease_is_setup_only(version):
    g = gate()
    h = handshake(version)
    verified = g.verify_capabilities(h, sign(h, "host-capabilities-v1"))
    decision = cap.publication_decision(verified)
    assert decision["hostCapabilities"]["hostVersionStatus"] != "at-or-above-floor"
    assert decision["publishedTiers"] == ["setup"]
    assert contracts.is_valid("gateway#/$defs/PublicationDecisionV1", decision)


@pytest.mark.parametrize("flag", FLAGS)
def test_each_missing_capability_fails_closed(flag):
    g = gate()
    h = handshake(**{flag: False})
    verified = g.verify_capabilities(h, sign(h, "host-capabilities-v1"))
    assert not cap.host_ready(verified)
    assert cap.publication_decision(verified)["publishedTiers"] == ["setup"]


def test_handshake_authentication_and_d24_are_independent_gates():
    g = gate()
    h = handshake()
    assert g.verify_capabilities(h, "0" * 64) is None
    assert not cap.host_ready(h)  # unsigned dict never sufficient
    verified = g.verify_capabilities(h, sign(h, "host-capabilities-v1"))
    assert cap.host_ready(verified)
    # No D24 principal-probe implementation exists. A good fixture handshake is NOT D24.
    decision = cap.publication_decision(verified)
    assert decision["principalIdentity"] == "unproven"
    assert decision["publishedTiers"] == ["setup"]
    assert contracts.is_valid("gateway#/$defs/PublicationDecisionV1", decision)


@pytest.mark.parametrize("run_kind", ["cron", "api", "kanban"])
def test_unattended_zero_budget_even_for_authenticated_context(run_kind):
    g = gate()
    value = authenticated(g, runKind=run_kind, cronRunId="cron-1" if run_kind == "cron" else None)
    assert value["trusted"]
    assert hc.paid_budget(value, configured_credits=200, interactive_surface=True) == 0


def test_core_headless_consent_ignores_remembered_trust(monkeypatch):
    from tools import approval_context as sessions, approval_prompt, approval
    from gateway.session_context import _CRON_SESSION
    monkeypatch.setattr(approval, "is_approved", lambda *a, **kw: True)
    for marker in ("HERMES_CRON_SESSION", "HERMES_SINGLE_QUERY_SESSION"):
        with monkeypatch.context() as local:
            local.setenv(marker, "1")
            token = _CRON_SESSION.set("1" if marker == "HERMES_CRON_SESSION" else "")
            try:
                assert approval_prompt.request_elicitation_consent("paid", "exact operation") == "decline"
                assert hc.paid_budget(hc.untrusted("trusted-context-absent-on-host"), configured_credits=200, interactive_surface=False) == 0
            finally:
                _CRON_SESSION.reset(token)


def test_scope_tuple_requires_receiver_owned_context_and_d24():
    g = gate()
    ctx = authenticated(g)
    with pytest.raises(ValueError, match="D24"):
        g.scope_tuple(ctx, "https://staging.example", {"accountId": "a", "orgId": "o"})
    # A provisional credential generation cannot manufacture account scope.
    assert not cap.publication_decision()["principalIdentity"] == "proven"
