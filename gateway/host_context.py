"""Fail-closed receiver for HostContextV1 / TrustedToolContextV1 (S04).

Pinned core has NO D31 sender. Absent bootstrap material accepts nothing; never
infer identity from env, tool arguments, MCP trust, elicitation or another Python.
The optional key/peer binding is for an authenticated spawn adapter (S05) and
explicit offline receiver fixtures only, not a shipped Hermes-core handshake.

Receiver MAC convention: HMAC-SHA256 over ASCII domain + NUL + UTF-8 JSON
(sort_keys=True, separators=(',', ':'), allow_nan=False). Initialize uses domain
host-capabilities-v1 and context uses trusted-tool-context-v1, excluding mac.
D31 must explicitly implement/review this convention before integration; no
claimed interoperability with the absent upstream extension.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from threading import Lock
from types import MappingProxyType

from .capabilities import _authenticated_capabilities

PROTOCOL = "studiotwin.host-gateway.v1"
META_KEY = "hermes.trustedToolContext/v1"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", re.ASCII)
_HOST = re.compile(r"[A-Za-z0-9_-]{43}", re.ASCII)
_TOOL = re.compile(r"[a-z][a-z0-9_-]{0,63}", re.ASCII)
_MAC = re.compile(r"[0-9a-f]{64}", re.ASCII)
_FIELDS = {"hostInstanceNonce", "profileId", "connectionId", "sessionId", "runKind",
           "cronRunId", "toolName", "turnId", "toolCallId", "callNonce", "mac"}
_RESERVED = _FIELDS | {META_KEY, "_meta", "session_id", "cron_run_id", "profile_id",
                       "connection_id", "hostCapabilities", "trusted", "approved",
                       "approval", "consent", "authorized", "authorization", "remember_key"}
_REASONS = {"trusted-context-absent-on-host", "trusted-context-mac-invalid",
            "trusted-context-stale-nonce", "trusted-context-wrong-peer",
            "trusted-context-in-model-arguments", "trusted-context-cross-session-reuse"}


def untrusted(reason):
    if reason not in _REASONS:
        raise ValueError("unknown refusal reason")
    return {"protocol": PROTOCOL, "trusted": False, "reason": reason}


def _model_context(value, depth=0):
    # JSON-like, bounded traversal; fail closed rather than recurse indefinitely.
    if depth > 16:
        return True
    if isinstance(value, dict):
        return any(not isinstance(k, str) or k in _RESERVED or _model_context(v, depth + 1)
                   for k, v in value.items())
    if isinstance(value, list):
        return any(_model_context(v, depth + 1) for v in value)
    return False


def _shape(value):
    if not isinstance(value, dict) or set(value) != _FIELDS:
        return False
    patterns = {"hostInstanceNonce": _HOST, "toolName": _TOOL, "mac": _MAC}
    for name in ("profileId", "connectionId", "sessionId", "turnId", "toolCallId"):
        patterns[name] = _ID
    if any(not isinstance(value[k], str) or not p.fullmatch(value[k]) for k, p in patterns.items()):
        return False
    if value["runKind"] not in ("interactive", "cron", "api", "kanban"):
        return False
    cron = value["cronRunId"]
    if value["runKind"] == "cron":
        if not isinstance(cron, str) or not _ID.fullmatch(cron):
            return False
    elif cron is not None:
        return False
    nonce = value["callNonce"]
    return type(nonce) is int and 0 <= nonce <= 9007199254740991


class HostContextGate:
    """One receiver per authenticated host spawn/connection generation.

    Explicit bootstrap values must originate at authenticated spawn, never MCP
    params. S05 owns that source/peer/ACL proof. A new gate is required on host,
    profile, connection or key rotation; do not transfer its contexts/operations.
    Operation ownership here is volatile transport isolation, NOT the durable
    money ledger/single-dispatch state machine (S09/S10).
    """

    def __init__(self, *, key=None, host_instance_nonce=None, profile_id=None, connection_id=None):
        if key is not None:
            if (not isinstance(key, bytes) or len(key) < 32
                    or not isinstance(host_instance_nonce, str) or not _HOST.fullmatch(host_instance_nonce)
                    or not isinstance(profile_id, str) or not _ID.fullmatch(profile_id)
                    or not isinstance(connection_id, str) or not _ID.fullmatch(connection_id)):
                raise ValueError("invalid authenticated bootstrap")
        self._key = key
        self._peer = (host_instance_nonce, profile_id, connection_id)
        self._nonces = {}
        self._contexts = {}
        self._operations = {}
        self._lock = Lock()

    def _verify_mac(self, payload, mac, domain):
        if self._key is None or not isinstance(mac, str) or not _MAC.fullmatch(mac):
            return False
        try:
            data = json.dumps(payload, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
        except (ValueError, TypeError, RecursionError):
            return False
        if len(data) > 16384:
            return False
        expected = hmac.new(self._key, domain.encode() + b"\0" + data, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, mac)

    def verify_capabilities(self, payload, mac):
        # Snapshot before verification; caller cannot mutate verified capability flags.
        try:
            snapshot = json.loads(json.dumps(payload, allow_nan=False))
        except (ValueError, TypeError, RecursionError):
            return None
        if not self._verify_mac(snapshot, mac, "host-capabilities-v1"):
            return None
        return _authenticated_capabilities(snapshot)

    def receive(self, *, arguments, metadata=None):
        if not isinstance(arguments, dict) or _model_context(arguments):
            return untrusted("trusted-context-in-model-arguments")
        if not isinstance(metadata, dict) or META_KEY not in metadata:
            return untrusted("trusted-context-absent-on-host")
        # Other unauthenticated metadata cannot confer approval/identity either.
        if any(k in _RESERVED for k in metadata if k != META_KEY):
            return untrusted("trusted-context-in-model-arguments")
        value = metadata[META_KEY]
        if not _shape(value):
            return untrusted("trusted-context-mac-invalid")
        value = dict(value)  # freeze scalar snapshot before verification
        mac = value.pop("mac")
        if not self._verify_mac(value, mac, "trusted-tool-context-v1"):
            return untrusted("trusted-context-mac-invalid")
        peer = tuple(value[k] for k in ("hostInstanceNonce", "profileId", "connectionId"))
        if peer != self._peer:
            return untrusted("trusted-context-wrong-peer")
        session = (value["sessionId"], value["runKind"], value["cronRunId"])
        with self._lock:
            if value["callNonce"] <= self._nonces.get(session, -1):
                return untrusted("trusted-context-stale-nonce")
            self._nonces[session] = value["callNonce"]
            result = MappingProxyType({"protocol": PROTOCOL, "trusted": True,
                                       "source": "trusted-tool-context-v1", **value})
            self._contexts[id(result)] = result
            return result

    def _owned(self, context):
        return self._contexts.get(id(context)) is context

    def new_operation(self, context):
        with self._lock:
            if not self._owned(context):
                raise ValueError("receiver-owned context required")
            operation = "op_" + secrets.token_urlsafe(32)
            self._operations[operation] = context
            return operation

    def consume_operation(self, operation, context):
        with self._lock:
            if not self._owned(context) or self._operations.get(operation) is not context:
                return False
            del self._operations[operation]
            return True

    def scope_tuple(self, context, endpoint_origin, principal):
        """ScopeTupleV1 cannot be issued from an unproven account/org dictionary.

        D24 remains unresolved: no /me candidate, API key HMAC, model fields or
        caller boolean is accepted as authenticated principal proof. S05 must
        retain setup-only; future D24 integration needs its own reviewed issuer.
        """
        raise ValueError("D24 authenticated principal contract is unavailable")


def paid_budget(context, *, configured_credits=0, interactive_surface=False):
    """Effective v1 paid budget is zero, regardless of trust/configuration.

    Headless, cron, api and kanban are unconditionally zero. Interactive paid
    authority also needs D24, authenticated host capabilities and exact once-only
    consent + the S09 ledger; a context alone cannot create it. No path here
    reads remembered MCP approval or a manifest spend limit.
    """
    return 0
