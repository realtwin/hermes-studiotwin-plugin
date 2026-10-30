"""Durable S10 reconciliation. Ledger provenance is a backend adapter, not JSON.

Production has no certified StudioTwin ledger issuer: without ledger_verifier,
final debit/refund remain unknown. Never allocate a wallet delta to an operation.
Internal AMBIGUOUS_UNRESOLVED maps to frozen UNKNOWN/UNKNOWN_NOT_VISIBLE on wire;
the schema has no AMBIGUOUS_UNRESOLVED or CAPABILITY_BREACH enum.
"""
import hashlib
import json
from datetime import datetime

from . import redaction as R
from .mediation_parse import BoundaryRefused, bounded_copy_v1
from .policy_store import mediated, _json
from .scope_pause import _pause_in_transaction, ScopePauseService


def _validate(ref, value):
    failed=False
    try:
        R._schema_validate(ref,value)
    except Exception:
        failed=True
    if failed: raise BoundaryRefused()


def timestamp_ms(value):
    if type(value) is int:
        _validate('gateway#/$defs/EpochMsV1',value)
        return value
    if type(value) is dict and set(value)=={'$date'}:
        value=value['$date']
    if type(value) is str:
        try:
            dt=datetime.fromisoformat(value.replace('Z','+00:00'))
            if dt.tzinfo is None: return None
            ms=int(dt.timestamp()*1000)
            _validate('gateway#/$defs/EpochMsV1',ms)
            return ms
        except (ValueError,OverflowError): pass
    return None


def fingerprint(inputs):
    return hashlib.sha256(_json(inputs).encode()).hexdigest()


def dashboard(kind, value, binding, sensitive):
    return R.validate_mediated_v1('dashboard#/components/schemas/'+kind,value,
        scope_id=binding['scope_id'],generation=binding['generation'],sensitive_values=sensitive)


class Reconciler:
    def __init__(self, store, *, clock_ms, ledger_verifier=None):
        self.store,self.clock_ms,self.ledger_verifier=store,clock_ms,ledger_verifier
        with store.transaction():
            store._db.execute('''CREATE TABLE IF NOT EXISTS dispatch_records(
                scope_id TEXT NOT NULL, generation INTEGER NOT NULL, operation_id TEXT NOT NULL,
                snapshot_json TEXT NOT NULL, recovery_json TEXT, started_ms INTEGER NOT NULL,
                job_status TEXT, submitted_ms INTEGER, terminal_ms INTEGER,
                PRIMARY KEY(scope_id,operation_id),
                FOREIGN KEY(scope_id,operation_id) REFERENCES policy_operations(scope_id,operation_id))''')

    def _record(self, operation, binding):
        self.store.get_operation(operation,binding)
        return self.store._db.execute('''SELECT snapshot_json,recovery_json,started_ms,job_status,submitted_ms,terminal_ms
            FROM dispatch_records WHERE scope_id=? AND generation=? AND operation_id=?''',
            (binding['scope_id'],binding['generation'],operation)).fetchone()

    def _initial(self, operation, binding, state=None):
        row=self.store.get_operation(operation,binding); a=row['authorization']
        return dict(protocol='studiotwin.gateway.v1',operationId=operation,scopeId=binding['scope_id'],jobId=None,
            enforcementMode=a['enforcementMode'],state=state or row['state'],estimatedCredits=a['estimatedCredits'],
            reservedCredits=row['reservedCredits'],submissionCost={'state':'unknown'},finalDebit={'state':'unknown'},
            refund={'state':'unknown'},actualCost={'state':'unknown'},reservationHeld=True,scopePaused=False)

    def _validated(self, value, binding):
        return mediated('ReconciliationV1',value,binding['scope_id'],binding['generation'],self.store._sensitive)

    def snapshot(self, operation, binding):
        row=self._record(operation,binding)
        return self._validated(json.loads(row[0]) if row else self._initial(operation,binding),binding)

    @staticmethod
    def _job_bound(value, row):
        """No recovery record means accept()'s direct submission binding.

        Recovery JSON is the durable provenance marker for provisional IDs,
        including databases written before non-unique recovery cleared them.
        Never promote a correlation to direct authority merely by observing it.
        """
        if row is None or value['jobId'] is None: return False
        if row[1] is None: return True
        recovery=json.loads(row[1])
        return (recovery['state']=='matched' and len(recovery['candidates'])==1 and
                recovery['candidates'][0]['jobId']==value['jobId'])

    def poll_target(self, operation, binding):
        value=self.snapshot(operation,binding).to_json()
        return value['jobId'] if self._job_bound(value,self._record(operation,binding)) else None

    def operation_state(self, operation, binding):
        row=self._record(operation,binding)
        result=dict(contract='studiotwin.dashboard.v1',operation=self.snapshot(operation,binding).to_json())
        if row and row[1] is not None: result['recovery']=json.loads(row[1])
        return dashboard('OperationStateV1',result,binding,self.store._sensitive)

    def _write(self, operation, binding, value, *, internal_state=None, recovery=None):
        value=self._validated(value,binding).to_json()
        args=(internal_state or value['state'],value['finalDebit'].get('credits'),value['refund'].get('credits'),
              binding['scope_id'],binding['generation'],operation)
        self.store._db.execute('''UPDATE policy_operations SET state=?,final_debit=?,refund=?
            WHERE scope_id=? AND generation=? AND operation_id=?''',args)
        if recovery is None:
            self.store._db.execute('UPDATE dispatch_records SET snapshot_json=? WHERE scope_id=? AND operation_id=?',
                                  (_json(value),binding['scope_id'],operation))
        else:
            recovery=dashboard('RecoveryCandidatesV1',recovery,binding,self.store._sensitive).to_json()
            self.store._db.execute('UPDATE dispatch_records SET snapshot_json=?,recovery_json=? WHERE scope_id=? AND operation_id=?',
                                  (_json(value),_json(recovery),binding['scope_id'],operation))
        return self._validated(value,binding)

    def start_in_transaction(self, operation, binding, now):
        value=self._initial(operation,binding,'DISPATCHING')
        value=self._validated(value,binding).to_json()
        self.store._db.execute('INSERT INTO dispatch_records VALUES (?,?,?,?,NULL,?,NULL,NULL,NULL)',
            (binding['scope_id'],binding['generation'],operation,_json(value),now))
        self._write(operation,binding,value)

    def ambiguous(self, operation, binding):
        with self.store.transaction():
            value=self.snapshot(operation,binding).to_json()
            if value['state'] not in ('DISPATCHING','UNKNOWN','UNKNOWN_NOT_VISIBLE'): return self._validated(value,binding)
            value.update(state='UNKNOWN',reservationHeld=True)
            return self._write(operation,binding,value,internal_state='AMBIGUOUS_UNRESOLVED')

    def release(self, operation, binding, *, expected_state='RESERVED_UNSENT'):
        """Internal dispatch hook ONLY for proved unsent failure/certified predebit rejection."""
        with self.store.transaction():
            value=self.snapshot(operation,binding).to_json()
            state=self.store.get_operation(operation,binding)['state']
            if state != expected_state: raise BoundaryRefused()
            value.update(state='RELEASED',reservationHeld=False)
            if self._record(operation,binding) is None:
                now=self.clock_ms()
                self.store._db.execute('INSERT INTO dispatch_records VALUES (?,?,?,?,NULL,?,NULL,NULL,NULL)',
                    (binding['scope_id'],binding['generation'],operation,_json(value),now))
            return self._write(operation,binding,value)

    def accept(self, operation, binding, *, job_id, submitted_credits):
        _validate('gateway#/$defs/JobIdV1',job_id)
        if submitted_credits is not None: _validate('gateway#/$defs/CreditsV1',submitted_credits)
        with self.store.transaction():
            value=self.snapshot(operation,binding).to_json()
            if self.store.get_operation(operation,binding)['state']!='DISPATCHING': raise BoundaryRefused()
            value.update(jobId=job_id,state='ACCEPTED')
            if submitted_credits is not None:
                value['submissionCost']=dict(state='reported',credits=submitted_credits,evidence=dict(kind='job-reported-submission-cost'))
            self.store._db.execute("UPDATE dispatch_records SET job_status='submitted' WHERE scope_id=? AND operation_id=?",(binding['scope_id'],operation))
            return self._write(operation,binding,value)

    def _evidence(self, kind, credits, ref, operation, binding, job):
        if credits is None or ref is None or self.ledger_verifier is None: return None
        failed=False
        verified=False
        try:
            verified=self.ledger_verifier(scope_id=binding['scope_id'],generation=binding['generation'],operation_id=operation,
                job_id=job,kind=kind,ref=ref,credits=credits) is True
        except Exception: failed=True
        if failed or not verified: return None
        return dict(state='reported',credits=credits,evidence=dict(kind=kind,ref=ref))

    def observe(self, operation, binding, job_record):
        """Backend-only observation after complete response mediation. No state/actualCost inputs.
        External ledger verifier must independently match scope/generation/operation/job/ref/amount.
        A ref string or a 'settlement' key is never evidence by itself.
        """
        record=bounded_copy_v1(job_record)
        allowed={'jobId','status','submittedAtMs','terminalAtMs','submittedCredits','finalDebitCredits','refundedCredits','ledgerRef','accountBalanceContext'}
        if type(record) is not dict or set(record)-allowed or not {'jobId','status'}<=set(record): raise BoundaryRefused()
        for field in ('submittedCredits','finalDebitCredits','refundedCredits'):
            if record.get(field) is not None: _validate('gateway#/$defs/CreditsV1',record[field])
        if record.get('ledgerRef') is not None:
            _validate('gateway#/$defs/EvidenceRefV1',record['ledgerRef'])
            R._walk(record['ledgerRef'],R._Sensitive(self.store._sensitive),redact=False)
        if record['status'] not in ('submitted','queued','running','done','failed','cancelled','unknown'): raise BoundaryRefused()
        with self.store.transaction():
            now=self.clock_ms()
            _validate('gateway#/$defs/EpochMsV1',now)
            value=self.snapshot(operation,binding).to_json(); row=self._record(operation,binding)
            if not self._job_bound(value,row) or value['jobId']!=record['jobId']: raise BoundaryRefused()
            for key in ('submittedAtMs','terminalAtMs'):
                if record.get(key) is not None: _validate('gateway#/$defs/EpochMsV1',record[key])
            submitted=record.get('submittedAtMs',row[4]); terminal=record.get('terminalAtMs',row[5])
            if ((submitted is not None and not row[2]<=submitted<=now) or
                (terminal is not None and not (submitted if submitted is not None else row[2])<=terminal<=now)):
                raise BoundaryRefused()
            if record['status']=='cancelled' and row[3] not in ('queued','submitted','cancelled'): raise BoundaryRefused()
            if record.get('accountBalanceContext') is not None: value['accountBalanceContext']=record['accountBalanceContext']
            if value['submissionCost']['state']=='unknown' and record.get('submittedCredits') is not None:
                value['submissionCost']=dict(state='reported',credits=record['submittedCredits'],evidence=dict(kind='job-reported-submission-cost'))
            for field,kind,source in (('finalDebit','job-specific-final-debit','finalDebitCredits'),('refund','job-specific-refund','refundedCredits')):
                evidence=self._evidence(kind,record.get(source),record.get('ledgerRef'),operation,binding,value['jobId'])
                if evidence is not None:
                    if value[field]['state']=='reported' and value[field]!=evidence: raise BoundaryRefused()
                    value[field]=evidence
            was_overrun=value['state']=='SETTLED_OVERRUN'
            internal=None
            if value['finalDebit']['state']=='reported':
                actual=value['finalDebit']['credits']
                value['actualCost']=dict(state='known',credits=actual,derivedFrom='job-specific-final-debit')
                if actual>value['reservedCredits'] and value['enforcementMode']=='server-max-credits':
                    # Certified remote maximum breached: held/quarantined, never interim settlement.
                    internal='CAPABILITY_BREACH'; value.update(state='ACCEPTED',reservationHeld=True)
                else:
                    overrun=actual>value['reservedCredits']
                    value.update(state='SETTLED_OVERRUN' if overrun else 'SETTLED',reservationHeld=False,scopePaused=overrun)
                    if overrun and not was_overrun:
                        a=self.store.get_operation(operation,binding)['authorization']
                        _pause_in_transaction(self.store,a,actual,now,binding['generation'])
            if value['refund']['state']=='reported' and record['status']=='cancelled' and internal is None and value['state']!='SETTLED_OVERRUN':
                # A verified refund is a distinct fact, not proof of the gross
                # final debit. Keep the hold (and S09 guard accounting) until
                # debit evidence is independently known.
                value.update(state='REFUNDED_VERIFIED',reservationHeld=value['finalDebit']['state']!='reported')
            # Status and refund-only observations cannot promote correlation to
            # binding authority. Only verified gross debit settles/quarantines it.
            if row[1] is not None and value['finalDebit']['state']!='reported':
                internal='AMBIGUOUS_UNRESOLVED'
            self.store._db.execute('UPDATE dispatch_records SET job_status=?,submitted_ms=?,terminal_ms=? WHERE scope_id=? AND operation_id=?',
                (record['status'],submitted,terminal,binding['scope_id'],operation))
            return self._write(operation,binding,value,internal_state=internal)

    def recover(self, operation, binding, jobs):
        """Bounded same-authenticated-scope list response; correlation is NOT settlement."""
        jobs=bounded_copy_v1(jobs)
        if type(jobs) is not list or len(jobs)>100: raise BoundaryRefused()
        with self.store.transaction():
            now=self.clock_ms(); value=self.snapshot(operation,binding).to_json(); row=self._record(operation,binding)
            state=self.store.get_operation(operation,binding)['state']
            if row is None or value['finalDebit']['state']=='reported':
                return self.operation_state(operation,binding)
            # Existing recovery provenance remains refreshable even in old rows
            # where an ordinary observation overwrote the recoverable state.
            if row[1] is None and state not in ('DISPATCHING','AMBIGUOUS_UNRESOLVED'):
                return self.operation_state(operation,binding)
            matches=[]; seen=set()
            for job in jobs:
                if type(job) is not dict or job.get('functionName')!=binding['tool']: continue
                job_id=job.get('uuid'); _validate('gateway#/$defs/JobIdV1',job_id)
                when=timestamp_ms(job.get('createdAt'))
                if when is None or not row[2]<=when<=now: continue
                digest=fingerprint(job.get('inputs'))
                if digest!=binding['canonical_input_hash'] or job_id in seen: continue
                seen.add(job_id)
                matches.append(dict(jobId=job_id,functionName=binding['tool'],submittedAtMs=when,
                    submittedAtRaw=None,inputFingerprint=digest,match='verified'))
            recovery=dict(operationId=operation,state='not-visible' if not matches else 'matched' if len(matches)==1 else 'multiple',
                          dispatchAllowed=False,candidates=matches)
            value.update(state='UNKNOWN' if matches else 'UNKNOWN_NOT_VISIBLE',reservationHeld=True)
            # Every recoverable ID is provisional; direct accept() bindings are
            # excluded by the provenance/state gate above.
            value['jobId']=matches[0]['jobId'] if len(matches)==1 else None
            self._write(operation,binding,value,internal_state='AMBIGUOUS_UNRESOLVED',recovery=recovery)
            return self.operation_state(operation,binding)
