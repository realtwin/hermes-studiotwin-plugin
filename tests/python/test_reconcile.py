"""Real settlement/evidence/ack store diffs; proposed ledger issuer is offline only."""
import json
import pytest
from tests.python.test_dispatch import harness, run, H, D, Q, SP


def ledger_verifier(fake):
    def verify(*,scope_id,generation,operation_id,job_id,kind,ref,credits):
        if scope_id!=H.SCOPE or generation!=1 or ref!='fixture-ledger-'+job_id: return False
        job=fake.jobs.get(job_id)
        if job is None: return False
        if kind=='job-specific-final-debit':
            return credits==job.cost and any(e.get('jobId')==job_id and e['event']=='debit' for e in fake.ledger)
        return (kind=='job-specific-refund' and credits==job.refunded and
                any(e.get('jobId')==job_id and e['event']=='refund' for e in fake.ledger))
    return verify


def observe(s,op,b,job,**changes):
    row=dict(jobId=job.uuid,status='done',submittedAtMs=job.created_ms,terminalAtMs=job.created_ms+1000,
             submittedCredits=job.cost,finalDebitCredits=None,refundedCredits=None,ledgerRef=None)
    row.update(changes)
    return s.reconciler.observe(op,b,row).to_json()


@pytest.mark.parametrize('actual',[0,19,20,21,32])
def test_only_verified_interim_overrun_pauses_atomically(harness,actual):
    build,store,_,_=harness
    fake,u,s,x,ctx,op,b=build('price_change_interim')
    run(s.dispatch(x,ctx,op)); job=next(iter(fake.jobs.values()))
    job.cost=actual
    s.reconciler.ledger_verifier=ledger_verifier(fake)
    fake.clock_ms=job.created_ms+2000
    r=observe(s,op,b,job,finalDebitCredits=actual,ledgerRef='fixture-ledger-'+job.uuid)
    assert r['submissionCost']['credits']==32  # originally observed at submit; never overwritten
    assert r['finalDebit']['credits']==actual and r['actualCost']['credits']==actual
    assert r['state']==('SETTLED_OVERRUN' if actual>20 else 'SETTLED')
    assert r['reservationHeld'] is False
    pause=SP.ScopePauseService(store,clock_ms=lambda:fake.clock_ms).get(H.SCOPE,1)
    assert (pause is not None)==(actual>20)
    assert store.guard_used(H.SCOPE,'chat')==actual
    assert store._db.execute('SELECT final_debit FROM policy_operations WHERE operation_id=?',(op,)).fetchone()==(actual,)


@pytest.mark.parametrize('submitted',[0,20,200])
def test_submission_and_shared_wallet_never_settle_or_pause(harness,submitted):
    build,store,_,_=harness
    fake,u,s,x,ctx,op,b=build()
    run(s.dispatch(x,ctx,op)); job=next(iter(fake.jobs.values())); fake.clock_ms+=2000
    r=observe(s,op,b,job,submittedCredits=submitted,accountBalanceContext=dict(level='account',balanceBefore=500,balanceAfter=100,attributedToJob=False))
    assert r['finalDebit']=={'state':'unknown'} and r['actualCost']=={'state':'unknown'}
    assert r['reservationHeld'] is True and r['scopePaused'] is False
    assert store.guard_used(H.SCOPE,'chat')==20
    assert store._db.execute('SELECT final_debit FROM policy_operations WHERE operation_id=?',(op,)).fetchone()==(None,)


def test_forged_same_job_ref_foreign_ledger_does_not_settle(harness):
    build,store,_,_=harness
    fake,u,s,x,ctx,op,b=build()
    run(s.dispatch(x,ctx,op)); job=next(iter(fake.jobs.values())); fake.clock_ms+=2000
    s.reconciler.ledger_verifier=ledger_verifier(fake)
    r=observe(s,op,b,job,finalDebitCredits=99,ledgerRef='fixture-ledger-'+H.OTHER)
    assert r['finalDebit']=={'state':'unknown'} and r['reservationHeld']
    r=observe(s,op,b,job,finalDebitCredits=99,ledgerRef='fixture-ledger-'+job.uuid)
    assert r['finalDebit']=={'state':'unknown'} and r['reservationHeld']
    assert store.pause(H.SCOPE,1) is None


def test_server_over_max_quarantines_not_interim_overrun(harness):
    build,store,_,_=harness
    fake,u,s,x,ctx,op,b=build('normal','server-max-credits')
    # Test a faulty certified future server: proof independent of its actual breach.
    s.charge_policy.server_binding_verified=lambda *_:True
    run(s.dispatch(x,ctx,op)); job=next(iter(fake.jobs.values())); job.cost=32; fake.clock_ms+=2000
    s.reconciler.ledger_verifier=ledger_verifier(fake)
    r=observe(s,op,b,job,finalDebitCredits=32,ledgerRef='fixture-ledger-'+job.uuid)
    assert store.get_operation(op,b)['state']=='CAPABILITY_BREACH'
    assert r['state']=='ACCEPTED' and r['reservationHeld']
    assert r['finalDebit']['credits']==32
    assert r['scopePaused'] is False and store.pause(H.SCOPE,1) is None
    run(s.dispatch(x,ctx,op)); assert u.paid_calls==1


@pytest.mark.parametrize('bad',[
    dict(submittedAtMs=100,terminalAtMs=99),dict(terminalAtMs=253402300799999),dict(jobId=H.OTHER),
    dict(submittedCredits=-1),dict(finalDebitCredits=True),dict(ledgerRef='https://bad.invalid/?secret=x')])
def test_invalid_evidence_binding_time_or_values_refuse_without_write(harness,bad):
    build,store,_,_=harness
    fake,u,s,x,ctx,op,b=build();run(s.dispatch(x,ctx,op));job=next(iter(fake.jobs.values()));fake.clock_ms+=2000
    before=list(store._db.iterdump())
    with pytest.raises(H.R.BoundaryRefused): observe(s,op,b,job,**bad)
    assert list(store._db.iterdump())==before


def test_old_generation_response_quarantined(harness):
    build,store,_,_=harness
    fake,u,s,x,ctx,op,b=build();run(s.dispatch(x,ctx,op));job=next(iter(fake.jobs.values()))
    store.activate('c'*64,'d'*64)
    before=list(store._db.iterdump())
    with pytest.raises(H.R.BoundaryRefused): observe(s,op,b,job)
    assert list(store._db.iterdump())==before


@pytest.mark.parametrize('prior',['queued','submitted','running'])
def test_cancel_only_queued_submitted_with_verified_refund(harness,prior):
    build,store,_,_=harness
    fake,u,s,x,ctx,op,b=build();run(s.dispatch(x,ctx,op));job=next(iter(fake.jobs.values()));fake.clock_ms+=2000
    observe(s,op,b,job,status=prior,terminalAtMs=None)
    fake._refund(job,job.cost)
    s.reconciler.ledger_verifier=ledger_verifier(fake)
    if prior=='running':
        before=list(store._db.iterdump())
        with pytest.raises(H.R.BoundaryRefused): observe(s,op,b,job,status='cancelled',refundedCredits=20,ledgerRef='fixture-ledger-'+job.uuid)
        assert list(store._db.iterdump())==before
    else:
        r=observe(s,op,b,job,status='cancelled',refundedCredits=20,ledgerRef='fixture-ledger-'+job.uuid)
        assert r['state']=='REFUNDED_VERIFIED' and r['refund']['credits']==20
        assert r['finalDebit']=={'state':'unknown'}  # refund is NOT debit evidence


def test_cancel_without_refund_evidence_stays_held(harness):
    build,store,_,_=harness
    fake,u,s,x,ctx,op,b=build();run(s.dispatch(x,ctx,op));job=next(iter(fake.jobs.values()));fake.clock_ms+=2000
    r=observe(s,op,b,job,status='cancelled',refundedCredits=20,ledgerRef='fake-unverified')
    assert r['refund']=={'state':'unknown'} and r['reservationHeld']


def paused(harness):
    build,store,_,_=harness
    fake,u,s,x,ctx,op,b=build('price_change_interim');run(s.dispatch(x,ctx,op))
    job=next(iter(fake.jobs.values())); fake.clock_ms+=2000
    s.reconciler.ledger_verifier=ledger_verifier(fake)
    observe(s,op,b,job,finalDebitCredits=32,ledgerRef='fixture-ledger-'+job.uuid)
    return fake,u,s,op,b,SP.ScopePauseService(store,clock_ms=lambda:fake.clock_ms)


def test_ack_only_pause_timestamp_idempotent_no_settlement_consent_dispatch(harness):
    fake,u,s,op,b,pauses=paused(harness); store=harness[1]
    before={t:list(store._db.execute('SELECT * FROM '+t)) for t in ('policy_operations','policy_quotes','dispatch_records')}
    p=pauses.get(H.SCOPE,1).to_json(); fake.clock_ms+=10
    request=dict(contract='studiotwin.dashboard.v1',scopeId=H.SCOPE,operationId=op)
    a=pauses.acknowledge(request,scope_id=H.SCOPE,generation=1).to_json()
    assert a['paused'] is False and a['authorizes'] is False and a['dispatches'] is False
    assert a['acknowledgedAtMs']==fake.clock_ms
    fake.clock_ms+=100
    assert pauses.acknowledge(request,scope_id=H.SCOPE,generation=1).to_json()==a
    after=pauses.get(H.SCOPE,1).to_json()
    assert {k:v for k,v in after.items() if k!='acknowledgedAtMs'}=={k:v for k,v in p.items() if k!='acknowledgedAtMs'}
    assert before=={t:list(store._db.execute('SELECT * FROM '+t)) for t in before}
    assert u.paid_calls==1 and store.guard_used(H.SCOPE,'chat')==32


@pytest.mark.parametrize('change',[dict(scopeId='c'*64),dict(operationId='op_'+'z'*43),dict(generation=2),dict(clock=0)])
def test_stale_foreign_or_early_ack_no_write(harness,change):
    fake,u,s,op,b,pauses=paused(harness);store=harness[1]
    req=dict(contract='studiotwin.dashboard.v1',scopeId=H.SCOPE,operationId=op)
    generation=change.pop('generation',1)
    if 'clock' in change: pauses.clock_ms=lambda:change['clock']
    else: req.update(change)
    before=list(store._db.iterdump())
    with pytest.raises(H.R.BoundaryRefused): pauses.acknowledge(req,scope_id=H.SCOPE,generation=generation)
    assert list(store._db.iterdump())==before


def another_reservation(s,x,ctx,fake,mode='interim-local'):
    b=H.binding(x,ctx)
    p=H.preview(x.tool,now=fake.clock_ms,mode=mode)
    p['previewId']='pv_'+'b'*43; p['previewExpiresAtMs']=fake.clock_ms+100000
    if mode=='server-max-credits': p['maxCredits']=20
    s.store.save_quote(p,b,price_version='price-a',server_token='sqt_'+'s'*43 if mode=='server-max-credits' else None,
                       clock_ms=lambda:fake.clock_ms)
    return run(s.authorization.authorize(x,ctx,p['previewId'])).value['operationId']


def test_newer_pause_cannot_be_replaced_by_reobserving_older_settlement(harness):
    fake,u,s,op,b,pauses=paused(harness); store=harness[1]
    latest=pauses.get(H.SCOPE,1).to_json(); latest.update(operationId='op_'+'z'*43,createdAtMs=fake.clock_ms+1)
    fake.clock_ms+=10
    store.put_pause(latest,generation=1)  # backend-only fixture for another operation's pause
    before=pauses.get(H.SCOPE,1).to_json()
    job=next(iter(fake.jobs.values()))
    observe(s,op,b,job,finalDebitCredits=32,ledgerRef='fixture-ledger-'+job.uuid)
    assert pauses.get(H.SCOPE,1).to_json()==before
    with pytest.raises(H.R.BoundaryRefused):
        pauses.acknowledge(dict(contract='studiotwin.dashboard.v1',scopeId=H.SCOPE,operationId=op),scope_id=H.SCOPE,generation=1)


def test_scope_pause_blocks_preexisting_unsent_reservation(harness):
    build,store,_,_=harness
    fake,u,s,x,ctx,op,b=build('price_change_interim')
    second=another_reservation(s,x,ctx,fake)
    run(s.dispatch(x,ctx,op));job=next(iter(fake.jobs.values()));fake.clock_ms+=2000
    s.reconciler.ledger_verifier=ledger_verifier(fake)
    observe(s,op,b,job,finalDebitCredits=32,ledgerRef='fixture-ledger-'+job.uuid)
    with pytest.raises(H.R.BoundaryRefused): run(s.dispatch(x,ctx,second))
    assert u.paid_calls==1 and store.get_operation(second,b)['state']=='RESERVED_UNSENT'


def test_capability_breach_blocks_other_server_submissions(harness):
    build,store,_,_=harness
    fake,u,s,x,ctx,op,b=build('normal','server-max-credits')
    s.charge_policy.server_binding_verified=lambda *_:True
    second=another_reservation(s,x,ctx,fake,'server-max-credits')
    run(s.dispatch(x,ctx,op));job=next(iter(fake.jobs.values()));job.cost=32;fake.clock_ms+=2000
    s.reconciler.ledger_verifier=ledger_verifier(fake)
    observe(s,op,b,job,finalDebitCredits=32,ledgerRef='fixture-ledger-'+job.uuid)
    with pytest.raises(H.R.BoundaryRefused): run(s.dispatch(x,ctx,second))
    assert u.paid_calls==1 and store.get_operation(op,b)['state']=='CAPABILITY_BREACH'


def test_overrun_and_pause_rollback_together_on_sink_failure(harness,monkeypatch):
    build,store,_,_=harness
    fake,u,s,x,ctx,op,b=build('price_change_interim');run(s.dispatch(x,ctx,op))
    job=next(iter(fake.jobs.values()));fake.clock_ms+=2000
    s.reconciler.ledger_verifier=ledger_verifier(fake)
    before=list(store._db.iterdump())
    def fail(*args,**kwargs):
        assert store._db.execute('SELECT 1 FROM policy_pauses WHERE scope_id=?',(H.SCOPE,)).fetchone()==(1,)
        raise H.R.BoundaryRefused()
    monkeypatch.setattr(s.reconciler,'_write',fail)
    with pytest.raises(H.R.BoundaryRefused): observe(s,op,b,job,finalDebitCredits=32,ledgerRef='fixture-ledger-'+job.uuid)
    assert list(store._db.iterdump())==before
