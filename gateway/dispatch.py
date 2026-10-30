"""S10 submit-once worker. No replay/retry loop exists, including after restart.

Only this backend coordinator uses the injected hosted transport, and every
response/event/error terminates at the real S07 Mediator.mediate then S06.
S07's actual API is Mediator.mediate (not a module-level mediate_result_v1).
D24/D31/S09 authorization remain fail-closed. No live capability issuer is shipped.
"""
import json
import time

from . import redaction as R
from .mediation import OutputPolicy
from .mediation_parse import BoundaryRefused, bounded_copy_v1
from .policy_store import check_authorization, _json
from .reconcile import Reconciler, timestamp_ms
from .scope_pause import ScopePauseService


class ChargePolicy:
    """Trusted backend configuration ONLY, never constructed from RPC/model JSON.

    Interim acceptance must be the owner's explicit risk decision; default false.
    Server proof adapters must certify actual field validation and quote binding
    against the authenticated current server, not an advertised capability bit.
    No production proof adapter exists pending D30. Test subclasses are offline.
    """
    def __init__(self, *, interim_risk_accepted=False):
        self._interim=interim_risk_accepted is True

    def server_binding_verified(self, authorization, binding):
        return False

    def predebit_rejection_verified(self, authorization, binding, response):
        return False

    def require(self, authorization, binding):
        if authorization['enforcementMode']=='interim-local':
            if not self._interim: raise BoundaryRefused()
        elif not self.server_binding_verified(authorization,binding):
            raise BoundaryRefused()


def _payload(raw):
    """Private bounded parsing for money/job facts, NEVER a display bypass."""
    if type(raw) is not dict: return None
    structured=raw.get('structuredContent')
    texts=raw.get('content',[])
    parsed=[]
    if type(texts) is list:
        for block in texts:
            if type(block) is dict and block.get('type')=='text' and type(block.get('text')) is str:
                try: parsed.append(bounded_copy_v1(json.loads(block['text'])))
                except (ValueError,TypeError): pass
    if structured is not None:
        if parsed and any(p!=structured for p in parsed): return None
        return structured
    return parsed[0] if len(parsed)==1 else None


class DispatchService:
    def __init__(self, authorization, *, mediator, transport, charge_policy=None, ledger_verifier=None):
        self.authorization=authorization
        self.store=authorization._store
        self.mediator,self._transport=mediator,transport
        self.charge_policy=charge_policy or ChargePolicy()
        self.reconciler=Reconciler(self.store,clock_ms=authorization._clock_ms,ledger_verifier=ledger_verifier)

    def mediate_result_v1(self, tool, raw, binding, *, event=False):
        """Adapter to S07's real frozen implementation; not a replacement redactor."""
        self.store.require_current(binding['scope_id'],binding['generation'])
        policy=self.authorization._classification.output_policy(tool)
        # Side channels have no producing job. An invalid jobId is ambiguous, not
        # permission to leak a raw response or skip the complete-channel scan.
        if event:
            policy=OutputPolicy(tool=tool,schema_hash=policy.schema_hash)
        try:
            result=self.mediator.mediate(raw,scope_id=binding['scope_id'],generation=binding['generation'],
                policy=policy,live_schema_hash=policy.schema_hash,sensitive_values=self.authorization._sensitive)
        except BoundaryRefused:
            # Still process ALL upstream channels with a no-extraction policy.
            result=self.mediator.mediate(raw,scope_id=binding['scope_id'],generation=binding['generation'],
                policy=OutputPolicy(tool=tool,schema_hash=policy.schema_hash),live_schema_hash=policy.schema_hash,
                sensitive_values=self.authorization._sensitive)
        return R.validate_mediated_v1('gateway#/$defs/GatewayResultV1',result.to_json(),
            scope_id=binding['scope_id'],generation=binding['generation'],sensitive_values=self.authorization._sensitive)

    async def _rpc(self, tool, inputs, binding):
        # No raw side-channel callback ever escapes to a UI/logger/transcript.
        def event(raw):
            self.mediate_result_v1(tool,raw,binding,event=True)
        failed=False; raw=None
        try:
            raw=bounded_copy_v1(await self._transport(tool,inputs,event))
        except Exception as exc:
            # Collect full error material inside mediation, never interpolate it
            # into a thrown exception, stored row, log, or result summary.
            failed=True
            self.mediate_result_v1(tool,{'error':str(exc)},binding,event=True)
        if failed: return None
        self.mediate_result_v1(tool,raw,binding)
        return raw

    def _result(self, operation, binding):
        snapshot=self.reconciler.snapshot(operation,binding).to_json()
        value=dict(protocol='studiotwin.gateway.v1',tool=binding['tool'],status='unknown' if snapshot['reservationHeld'] else 'ok',
                   jobId=snapshot['jobId'],assetIds=[],media=[],summary='Operation state recorded; do not resubmit.',operation=snapshot)
        return R.validate_mediated_v1('gateway#/$defs/GatewayResultV1',value,
            scope_id=binding['scope_id'],generation=binding['generation'],sensitive_values=self.authorization._sensitive)

    def _check_locked(self, operation, binding, now):
        self.store.require_current(binding['scope_id'],binding['generation'])
        row=self.store.get_operation(operation,binding)
        if row['state']!='RESERVED_UNSENT': return False
        a=row['authorization']
        q=self.store._db.execute('''SELECT binding_json,preview_json,price_version,server_token,consumed_by
            FROM policy_quotes WHERE scope_id=? AND generation=? AND preview_id=?''',
            (binding['scope_id'],binding['generation'],a['previewId'])).fetchone()
        if q is None or json.loads(q[0])!=binding or q[4]!=operation: raise BoundaryRefused()
        check_authorization(a,json.loads(q[1]),binding,now,self.authorization._sensitive)
        if (a['previewPriceVersion']!=q[2] or a.get('serverQuoteToken')!=q[3] or
                row['reservedCredits']!=a['maxCredits']): raise BoundaryRefused()
        self.charge_policy.require(a,binding)
        if self.store._db.execute("SELECT 1 FROM policy_operations WHERE scope_id=? AND generation=? AND state='CAPABILITY_BREACH' LIMIT 1",
                                  (binding['scope_id'],binding['generation'])).fetchone():
            raise BoundaryRefused()
        pause=ScopePauseService(self.store,clock_ms=self.authorization._clock_ms).get(binding['scope_id'],binding['generation'])
        if pause is not None and pause.value['acknowledgedAtMs'] is None: raise BoundaryRefused()
        if self.store.guard_used(binding['scope_id'],binding['session_id'])>self.store.guard_limit(binding['scope_id'],binding['session_id']):
            raise BoundaryRefused()
        return True

    async def dispatch(self, effective, context, operation):
        binding=self.authorization._context(effective,context)
        row=self.store.get_operation(operation,binding)
        # Duplicate/restart never turns an existing operation into dispatch authority.
        if row['state']!='RESERVED_UNSENT': return self._result(operation,binding)
        self.charge_policy.require(row['authorization'],binding)
        classification=self.authorization._classification._row(effective.tool,effective.schema_hash)
        if context['runKind']!='interactive': raise BoundaryRefused()
        if classification['tier']=='hosted-read' and classification['costClass']=='free_read': raise BoundaryRefused()
        if row['authorization']['enforcementMode']=='interim-local' and classification['costClass']!='free_read':
            estimate=await self._rpc('studiotwin_estimate_cost',dict(functionName=effective.tool,inputs=effective.to_json()),binding)
            facts=_payload(estimate)
            if (type(facts) is not dict or facts.get('functionName')!=effective.tool or
                type(facts.get('estimatedCost')) is not int or facts['estimatedCost']!=row['reservedCredits'] or
                facts.get('providerAvailable') is not True or facts.get('canRun') is not True):
                # No mutation bytes have been sent. Recheck state in release:
                # a concurrent dispatch may already own it, in which case never release.
                with self.store.transaction():
                    current=self.store.get_operation(operation,binding)['state']
                    if current!='RESERVED_UNSENT': return self._result(operation,binding)
                self.reconciler.release(operation,binding)
                return self._result(operation,binding)
        with self.store.transaction():
            now=self.authorization._clock_ms()  # trusted sample AFTER BEGIN IMMEDIATE
            if self.authorization._context(effective,context)!=binding: raise BoundaryRefused()
            if not self._check_locked(operation,binding,now): return self._result(operation,binding)
            self.reconciler.start_in_transaction(operation,binding,now)
        # Committed DISPATCHING BEFORE invoking transport. Process death or even
        # BaseException here leaves a held row; no recovery path can resend it.
        args=effective.to_json()
        if row['authorization']['enforcementMode']=='server-max-credits':
            args.update(maxCredits=row['reservedCredits'],serverQuoteToken=row['authorization']['serverQuoteToken'])
        raw=await self._rpc(effective.tool,args,binding)
        facts=_payload(raw)
        if (raw is not None and raw.get('isError') is True and
            row['authorization']['enforcementMode']=='server-max-credits' and
            type(facts) is dict and facts.get('code')=='PRICE_EXCEEDS_MAX' and
            self.charge_policy.predebit_rejection_verified(row['authorization'],binding,raw)):
            self.reconciler.release(operation,binding,expected_state='DISPATCHING')
        elif raw is not None and raw.get('isError') is not True and type(facts) is dict:
            try:
                job_id=facts.get('jobId')
                R._schema_validate('gateway#/$defs/JobIdV1',job_id)
                cost=facts.get('cost')
                if cost is not None: R._schema_validate('gateway#/$defs/CreditsV1',cost)
            except (ValueError,TypeError):
                self.reconciler.ambiguous(operation,binding)
            else:
                self.reconciler.accept(operation,binding,job_id=job_id,submitted_credits=cost)
        else:
            self.reconciler.ambiguous(operation,binding)
        return self._result(operation,binding)

    async def recover(self, operation, binding):
        self.store.get_operation(operation,binding)
        raw=await self._rpc('studiotwin_list_my_jobs',dict(limit=100,offset=0),binding)
        facts=_payload(raw)
        if type(facts) is not list:
            # Failure/delayed visibility is never proof of no billing.
            facts=[]
        return self.reconciler.recover(operation,binding,facts)

    async def poll(self, operation, binding):
        snapshot=self.reconciler.snapshot(operation,binding).to_json()
        if snapshot['jobId'] is None: return self.reconciler.snapshot(operation,binding)
        raw=await self._rpc('studiotwin_get_job_status',dict(jobId=snapshot['jobId']),binding)
        facts=_payload(raw)
        if type(facts) is not dict or facts.get('uuid')!=snapshot['jobId']: return self.reconciler.snapshot(operation,binding)
        settlement=facts.get('settlement')
        if type(settlement) is not dict: settlement={}
        return self.reconciler.observe(operation,binding,dict(jobId=snapshot['jobId'],status=str(facts.get('status','unknown')).lower(),
            submittedAtMs=timestamp_ms(facts.get('createdAt')),terminalAtMs=timestamp_ms(facts.get('finishedAt')),
            finalDebitCredits=settlement.get('finalDebitCredits'),refundedCredits=settlement.get('refundCredits'),
            ledgerRef=settlement.get('ledgerRef')))

    async def read(self, effective, context):
        binding=self.authorization._context(effective,context)
        row=self.authorization._classification._row(effective.tool,effective.schema_hash)
        # N3: costClass alone includes free mutations; BOTH conditions required.
        if row['tier']!='hosted-read' or row['costClass']!='free_read': raise BoundaryRefused()
        # Object-specific unattended reads require S14/S24 adoption. No generic
        # read facade authorizes an arbitrary UUID or cross-run monitor.
        if effective.to_json(): raise BoundaryRefused()
        raw=await self._rpc(effective.tool,effective.to_json(),binding)
        if raw is None: raise BoundaryRefused()
        return self.mediate_result_v1(effective.tool,raw,binding)
