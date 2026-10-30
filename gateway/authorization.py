"""S09 exact-call consent orchestrator. No network/dispatch/REST authority.

D24 has no reviewed principal issuer and D30/interim-risk proof belongs to S10.
The production path fails closed at those seams. Offline tests replace those
seams explicitly; they do not create a shipped boolean-based enablement path.
Only a trusted spawn adapter may supply the gate, verified capabilities and
in-flight host elicitation callable. Never populate them from browser/tool JSON.
"""
from __future__ import annotations

import inspect
import secrets
import time

from . import redaction as R
from .canonical import EffectiveInputs, canonicalize
from .classification import Classification, VerifiedHostContext
from .capabilities import host_ready
from .host_context import HostContextGate
from .startup import ManagedHostGate
from .mediation_parse import BoundaryRefused
from .policy_store import check_authorization, mediated


def _principal_scope(gate, context, endpoint_origin):
    # Current S04 always raises: no /me candidate or caller principal boolean is
    # accepted. A future reviewed D24 adapter must issue an authenticated scope,
    # bind full tuple + credential epoch and coordinate PolicyStore.activate.
    gate.scope_tuple(context,endpoint_origin,None)
    raise BoundaryRefused()


def _mode_ready(mode):
    # S10 supplies authenticated D30 capability proof or explicit accepted
    # interim risk. Labels/tokens/preview.executable are not that proof.
    return False


class AuthorizationService:
    def __init__(self, classification, store, *, gate, host_capabilities,
                 endpoint_origin, elicit=None, clock_ms=None, sensitive_values=()):
        if type(classification) is not Classification or type(gate) not in (HostContextGate,ManagedHostGate):
            raise BoundaryRefused()
        self._classification, self._store, self._gate = classification,store,gate
        self._host_capabilities, self._endpoint_origin = host_capabilities,endpoint_origin
        self._elicit = elicit
        self._clock_ms = clock_ms or (lambda:int(time.time()*1000))
        self._sensitive = sensitive_values

    def _context(self, effective, context):
        if isinstance(self._gate,ManagedHostGate):
            self._gate.expire()
        if (type(effective) is not EffectiveInputs or type(context) is not VerifiedHostContext or
                not self._gate._owned(context) or not host_ready(self._host_capabilities) or
                context['toolName'] != effective.tool):
            raise BoundaryRefused()
        self._store.require_current(effective.scope_id,effective.generation)
        row=self._classification._row(effective.tool,effective.schema_hash)
        # N3: free_read is a cost label used for writes too. Mutation tier is
        # independently interactive-only, even when its estimate is zero.
        if context['runKind'] != 'interactive' and (row['tier'] != 'hosted-read' or row['costClass'] != 'free_read'):
            raise BoundaryRefused()
        failed=False
        scope=None
        try:
            scope=_principal_scope(self._gate,context,self._endpoint_origin)
        except Exception:
            failed=True
        if failed or scope != effective.scope_id:
            raise BoundaryRefused()
        checked=canonicalize(effective.candidate,classification=self._classification,store=self._store,
                             sensitive_values=self._sensitive)
        if checked.canonical_input_hash != effective.canonical_input_hash or checked.to_json()!=effective.to_json():
            raise BoundaryRefused()
        return dict(scope_id=effective.scope_id,generation=effective.generation,session_id=context['sessionId'],
                    turn_id=context['turnId'],tool_call_id=context['toolCallId'],tool=effective.tool,
                    schema_hash=effective.schema_hash,canonical_input_hash=effective.canonical_input_hash)

    async def authorize(self, effective: EffectiveInputs, context: VerifiedHostContext, preview_id: str):
        """Only this coroutine creates AuthorizationV1. The host callback runs
        INSIDE the exact original call and receives a detached safe form summary.
        Its reply cannot come from an IPC/browser method or remembered MCP trust.
        The callback must preserve the host's in-flight call context. D31 sender
        integration remains external; this is its fail-closed receiver seam.
        """
        binding=self._context(effective,context)
        # Reads use the S10 read path, never a paid AuthorizationV1 envelope.
        if context['runKind'] != 'interactive' or not inspect.iscoroutinefunction(self._elicit):
            raise BoundaryRefused()
        p,price,token=self._store.load_quote(preview_id,binding,now_ms=self._clock_ms())
        if not _mode_ready(p['enforcementMode']):
            raise BoundaryRefused()
        pause=self._store.pause(effective.scope_id,effective.generation)
        if pause is not None and pause.value['acknowledgedAtMs'] is None:
            raise BoundaryRefused()
        operation='op_'+secrets.token_urlsafe(32)
        elicitation='el_'+secrets.token_urlsafe(32)
        now=self._clock_ms()
        auth=dict(protocol='studiotwin.gateway.v1',operationId=operation,scopeId=effective.scope_id,
                  trustedSessionId=context['sessionId'],runKind='interactive',runId=context['sessionId'],
                  tool=effective.tool,schemaHash=effective.schema_hash,canonicalInputHash=effective.canonical_input_hash,
                  enforcementMode=p['enforcementMode'],previewId=preview_id,previewPriceVersion=price,
                  previewExpiresAtMs=p['previewExpiresAtMs'],estimatedCredits=p['estimatedCredits'],
                  maxCredits=p['estimatedCredits'] if p['enforcementMode']=='interim-local' else p['maxCredits'],
                  expiresAtMs=p['previewExpiresAtMs'],createdAtMs=now,
                  consent=dict(channel='mcp-elicitation-form',action='accept',rememberKey=None,elicitationId=elicitation),
                  contextSource='trusted-tool-context-v1')
        if token is not None:
            auth['serverQuoteToken']=token
        check_authorization(auth,p,binding,now,self._sensitive)
        # No effective vpc resource string or raw candidate values reach the
        # presentation boundary. UUID-only validated candidates plus their hash
        # are sufficient for an exact operation summary; never signed locations.
        request=dict(elicitationId=elicitation,operationId=operation,tool=effective.tool,
                     canonicalInputHash=effective.canonical_input_hash,inputs=effective.candidate.to_json(),
                     preview=p,scopeId=effective.scope_id,generation=effective.generation,
                     sessionId=context['sessionId'],turnId=context['turnId'],toolCallId=context['toolCallId'],
                     rememberKey=None)
        failed=False
        reply=None
        try:
            reply=await self._elicit(request)
        except Exception:
            failed=True
        if (failed or type(reply) is not dict or set(reply)!={'action','elicitationId'} or
                reply['action']!='accept' or reply['elicitationId']!=elicitation):
            raise BoundaryRefused()
        # Expiry, receiver lifetime, principal, generation, ownership, canonical
        # input, pause, quote consumption and guard are rechecked after consent.
        if self._context(effective,context)!=binding:
            raise BoundaryRefused()
        return self._store.reserve(auth,binding,now_ms=self._clock_ms())
