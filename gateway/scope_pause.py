"""Scope-wide verified-overrun pause. Acknowledgement is strictly nonbilling.

S11 supplies authenticated scope/generation from IPC, never request params.
The frozen pause ID is its operationId (there is no separate pauseId field).
"""
import json
from .mediation_parse import BoundaryRefused
from .policy_store import mediated, _json
from . import redaction as R


def _pause_in_transaction(store, authorization, actual, now_ms, generation):
    """Only Reconciler calls this AFTER verified same-job debit, in its transaction."""
    if authorization['enforcementMode']!='interim-local' or actual<=authorization['maxCredits']:
        raise BoundaryRefused()
    p=dict(protocol='studiotwin.gateway.v1',scopeId=authorization['scopeId'],reason='verified-overrun',
           operationId=authorization['operationId'],estimatedCredits=authorization['estimatedCredits'],
           actualCredits=actual,createdAtMs=now_ms,acknowledgedAtMs=None)
    p=mediated('ScopePauseV1',p,p['scopeId'],generation,store._sensitive).to_json()
    old=store._db.execute('SELECT generation,pause_json FROM policy_pauses WHERE scope_id=?',(p['scopeId'],)).fetchone()
    # Repeated reconciliation must not re-arm an already acknowledged same pause.
    if old and old[0]==generation and json.loads(old[1])['operationId']==p['operationId']:
        return
    store._db.execute('INSERT OR REPLACE INTO policy_pauses VALUES (?,?,?)',(p['scopeId'],generation,_json(p)))


class ScopePauseService:
    def __init__(self, store, *, clock_ms):
        self.store, self.clock_ms=store,clock_ms

    def get(self, scope_id, generation):
        self.store.require_current(scope_id,generation)
        row=self.store._db.execute('SELECT generation,pause_json FROM policy_pauses WHERE scope_id=?',(scope_id,)).fetchone()
        if row is None or row[0]!=generation:
            return None
        return mediated('ScopePauseV1',json.loads(row[1]),scope_id,generation,self.store._sensitive)

    def acknowledge(self, request, *, scope_id, generation):
        request=R.validate_mediated_v1('dashboard#/components/schemas/ScopePauseAcknowledgeRequestV1',request,
            scope_id=scope_id,generation=generation,sensitive_values=self.store._sensitive).to_json()
        if request['scopeId']!=scope_id:
            raise BoundaryRefused()
        with self.store.transaction():
            self.store.require_current(scope_id,generation)
            p=self.get(scope_id,generation)
            if p is None or p.value['operationId']!=request['operationId']:
                raise BoundaryRefused()
            value=p.to_json()
            now=self.clock_ms()
            R._schema_validate('gateway#/$defs/EpochMsV1',now)
            if now<value['createdAtMs']:
                raise BoundaryRefused()
            if value['acknowledgedAtMs'] is None:
                value['acknowledgedAtMs']=now
                # The ONLY write: no operation, quote, guard or reservation updates.
                self.store._db.execute('UPDATE policy_pauses SET pause_json=? WHERE scope_id=? AND generation=?',
                                       (_json(value),scope_id,generation))
            result=dict(contract='studiotwin.dashboard.v1',scopeId=scope_id,operationId=request['operationId'],
                        paused=False,acknowledgedAtMs=value['acknowledgedAtMs'],authorizes=False,dispatches=False)
            return R.validate_mediated_v1('dashboard#/components/schemas/ScopePauseAcknowledgedV1',result,
                scope_id=scope_id,generation=generation,sensitive_values=self.store._sensitive)
