"""Real settlement/evidence/ack store diffs; proposed ledger issuer is offline only."""
import json
import pytest
from tests.python.test_dispatch import harness, run, H, D, Q, SP


def recovery_transition(harness, later):
    build,store,_,_=harness
    fake,u,s,x,ctx,op,b=build('ambiguous_no_structured_content')
    run(s.dispatch(x,ctx,op))
    first=run(s.recover(op,b)).to_json()
    assert first['recovery']['state']=='matched'
    job=fake.jobs[first['operation']['jobId']]
    if later=='multiple':
        fake.call(H.NAME,x.to_json())  # independent identical job, not dispatch replay
        second=run(s.recover(op,b)).to_json()
    else:
        second=s.reconciler.recover(op,b,[]).to_json()
    assert second['recovery']['state']==later
    assert second['recovery']['dispatchAllowed'] is False
    assert second['operation']['reservationHeld'] is True
    assert store.get_operation(op,b)['state']=='AMBIGUOUS_UNRESOLVED'
    assert store.guard_used(H.SCOPE,'chat')==20 and u.paid_calls==1
    return fake,u,s,x,ctx,op,b,job,second


@pytest.mark.parametrize('later',['multiple','not-visible'])
def test_recovery_transition_clears_provisional_job_id(harness,later):
    fake,u,s,x,ctx,op,b,job,r=recovery_transition(harness,later)
    assert r['operation']['jobId'] is None
    assert s.reconciler.snapshot(op,b).value['jobId'] is None
    assert r['operation']['state']==('UNKNOWN' if later=='multiple' else 'UNKNOWN_NOT_VISIBLE')


@pytest.mark.parametrize('later',['multiple','not-visible'])
def test_recovery_transition_no_status_rpc_or_stale_settlement(harness,later):
    fake,u,s,x,ctx,op,b,job,r=recovery_transition(harness,later)
    store=harness[1]
    before=list(store._db.iterdump())
    run(s.poll(op,b))
    assert sum(c['name']=='studiotwin_get_job_status' for c in fake.calls)==0
    fake.clock_ms+=2000
    s.reconciler.ledger_verifier=ledger_verifier(fake)
    with pytest.raises(H.R.BoundaryRefused):
        observe(s,op,b,job,finalDebitCredits=job.cost,ledgerRef='fixture-ledger-'+job.uuid)
    assert list(store._db.iterdump())==before
    assert s.reconciler.snapshot(op,b).value['actualCost']=={'state':'unknown'}


@pytest.mark.parametrize('later',['multiple','not-visible'])
@pytest.mark.parametrize('action',['poll','observe'])
def test_ambiguous_recovery_guards_legacy_stale_persisted_id(harness,later,action):
    fake,u,s,x,ctx,op,b,job,r=recovery_transition(harness,later)
    store=harness[1]
    # Old S10 databases can already contain this inconsistent provisional ID.
    snapshot=r['operation']; snapshot['jobId']=job.uuid
    with store.transaction():
        store._db.execute('UPDATE dispatch_records SET snapshot_json=? WHERE scope_id=? AND operation_id=?',
                          (json.dumps(snapshot),H.SCOPE,op))
    before=list(store._db.iterdump()); fake.clock_ms+=2000
    s.reconciler.ledger_verifier=ledger_verifier(fake)
    if action=='poll':
        # Either refusal API is safe only if it sends no status request. A
        # downstream observe() refusal cannot excuse an already issued RPC.
        try:
            run(s.poll(op,b))
        except H.R.BoundaryRefused:
            pass
        assert sum(c['name']=='studiotwin_get_job_status' for c in fake.calls)==0
    else:
        with pytest.raises(H.R.BoundaryRefused):
            observe(s,op,b,job,finalDebitCredits=job.cost,ledgerRef='fixture-ledger-'+job.uuid)
    assert list(store._db.iterdump())==before
    assert store.get_operation(op,b)['state']=='AMBIGUOUS_UNRESOLVED'


@pytest.mark.parametrize('later',['multiple','not-visible'])
def test_unique_recovery_reestablished_allows_poll_without_replay(harness,later):
    fake,u,s,x,ctx,op,b,job,r=recovery_transition(harness,later)
    if later=='multiple':
        other=next(k for k in fake.jobs if k!=job.uuid)
        del fake.jobs[other]
    restored=run(s.recover(op,b)).to_json()
    assert restored['recovery']['state']=='matched'
    assert restored['operation']['jobId']==job.uuid
    run(s.poll(op,b)); run(s.dispatch(x,ctx,op))
    assert sum(c['name']=='studiotwin_get_job_status' for c in fake.calls)==1
    assert u.paid_calls==1


def test_direct_submission_binding_survives_empty_or_multiple_recovery(harness):
    build,store,_,_=harness
    fake,u,s,x,ctx,op,b=build()
    result=run(s.dispatch(x,ctx,op)).to_json()
    job=result['operation']['jobId']
    fake.call(H.NAME,x.to_json())
    for recovery in (run(s.recover(op,b)),s.reconciler.recover(op,b,[])):
        assert recovery.value['operation']['jobId']==job
        assert 'recovery' not in recovery.value
    run(s.poll(op,b)); run(s.dispatch(x,ctx,op))
    assert sum(c['name']=='studiotwin_get_job_status' for c in fake.calls)==1
    assert u.paid_calls==1


@pytest.mark.parametrize('later',['multiple','not-visible'])
@pytest.mark.parametrize('observation',['poll','observe'])
def test_post_poll_provisional_recovery_refresh(harness,later,observation):
    build,store,_,_=harness
    fake,u,s,x,ctx,op,b=build('ambiguous_no_structured_content')
    run(s.dispatch(x,ctx,op))
    first=run(s.recover(op,b)).to_json()
    job=fake.jobs[first['operation']['jobId']]
    if observation=='poll':
        run(s.poll(op,b))
    else:
        fake.clock_ms+=2000
        observe(s,op,b,job)
    assert store.get_operation(op,b)['state']=='AMBIGUOUS_UNRESOLVED'
    if later=='multiple':
        fake.call(H.NAME,x.to_json())
        result=run(s.recover(op,b)).to_json()
    else:
        result=s.reconciler.recover(op,b,[]).to_json()
    assert result['operation']['jobId'] is None
    assert result['recovery']['state']==later
    assert len(result['recovery']['candidates'])==(2 if later=='multiple' else 0)
    assert result['recovery']['dispatchAllowed'] is False
    assert store.get_operation(op,b)['state']=='AMBIGUOUS_UNRESOLVED'
    assert result['operation']['reservationHeld'] is True
    assert store.guard_used(H.SCOPE,'chat')==20
    before=list(store._db.iterdump())
    calls=sum(c['name']=='studiotwin_get_job_status' for c in fake.calls)
    run(s.poll(op,b))
    assert sum(c['name']=='studiotwin_get_job_status' for c in fake.calls)==calls
    with pytest.raises(H.R.BoundaryRefused):
        s.reconciler.observe(op,b,dict(jobId=job.uuid,status='done'))
    assert list(store._db.iterdump())==before
    for key in list(fake.jobs):
        if key!=job.uuid: del fake.jobs[key]
    restored=run(s.recover(op,b)).to_json()
    assert restored['operation']['jobId']==job.uuid
    assert restored['recovery']['state']=='matched'
    run(s.poll(op,b)); run(s.dispatch(x,ctx,op))
    assert sum(c['name']=='studiotwin_get_job_status' for c in fake.calls)==calls+1
    assert u.paid_calls==1


def test_legacy_post_poll_unknown_provisional_record_can_refresh(harness):
    build,store,_,_=harness
    fake,u,s,x,ctx,op,b=build('ambiguous_no_structured_content')
    run(s.dispatch(x,ctx,op)); run(s.recover(op,b))
    # Already persisted by pre-R2 observe(): provenance survives the lost state.
    with store.transaction():
        store._db.execute("UPDATE policy_operations SET state='UNKNOWN' WHERE operation_id=?",(op,))
    result=s.reconciler.recover(op,b,[]).to_json()
    assert result['operation']['jobId'] is None
    assert result['recovery']['state']=='not-visible'
    assert store.get_operation(op,b)['state']=='AMBIGUOUS_UNRESOLVED'


def test_direct_submission_recovery_after_poll_is_unchanged(harness):
    build,store,_,_=harness
    fake,u,s,x,ctx,op,b=build()
    job=run(s.dispatch(x,ctx,op)).to_json()['operation']['jobId']
    run(s.poll(op,b))
    before=s.reconciler.operation_state(op,b).to_json()
    fake.call(H.NAME,x.to_json())
    assert run(s.recover(op,b)).to_json()==before
    assert s.reconciler.recover(op,b,[]).to_json()==before
    assert s.reconciler.poll_target(op,b)==job
    assert u.paid_calls==1


@pytest.mark.parametrize('mode,actual,expected',[
    ('interim-local',20,'SETTLED'),('interim-local',32,'SETTLED_OVERRUN'),
    ('server-max-credits',32,'CAPABILITY_BREACH')])
def test_provisional_verified_ledger_transition_stops_recovery(harness,mode,actual,expected):
    build,store,_,_=harness
    fake,u,s,x,ctx,op,b=build('ambiguous_no_structured_content',mode)
    if mode=='server-max-credits': s.charge_policy.server_binding_verified=lambda *_:True
    run(s.dispatch(x,ctx,op))
    job=next(iter(fake.jobs.values()))
    if mode=='server-max-credits':
        # The fake persists injected max/token fields; recovery correlates the
        # canonical effective inputs, not transport-only charge metadata.
        s.reconciler.recover(op,b,[dict(uuid=job.uuid,functionName=x.tool,
            inputs=x.to_json(),createdAt=job.created_ms)])
    else:
        run(s.recover(op,b))
    run(s.poll(op,b))
    job.cost=actual; fake.clock_ms+=2000
    s.reconciler.ledger_verifier=ledger_verifier(fake)
    result=observe(s,op,b,job,finalDebitCredits=actual,ledgerRef='fixture-ledger-'+job.uuid)
    assert store.get_operation(op,b)['state']==expected
    assert result['actualCost']['credits']==actual
    assert result['reservationHeld']==(expected=='CAPABILITY_BREACH')
    before=s.reconciler.operation_state(op,b).to_json()
    assert s.reconciler.recover(op,b,[]).to_json()==before
    assert run(s.recover(op,b)).to_json()==before
    run(s.dispatch(x,ctx,op)); assert u.paid_calls==1


def test_provisional_verified_refund_without_debit_remains_recoverable(harness):
    build,store,_,_=harness
    fake,u,s,x,ctx,op,b=build('ambiguous_no_structured_content')
    run(s.dispatch(x,ctx,op)); run(s.recover(op,b))
    job=next(iter(fake.jobs.values())); fake.clock_ms+=2000
    fake._refund(job,job.cost); fake.clock_ms+=2000
    s.reconciler.ledger_verifier=ledger_verifier(fake)
    observe(s,op,b,job,status='queued',terminalAtMs=None)
    result=observe(s,op,b,job,status='cancelled',refundedCredits=20,ledgerRef='fixture-ledger-'+job.uuid)
    assert result['state']=='REFUNDED_VERIFIED' and result['reservationHeld']
    assert result['finalDebit']=={'state':'unknown'}
    assert store.get_operation(op,b)['state']=='AMBIGUOUS_UNRESOLVED'
    assert s.reconciler.recover(op,b,[]).to_json()['operation']['jobId'] is None
    assert u.paid_calls==1


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
        assert r['reservationHeld'] is True  # missing final-debit evidence cannot release the hold
        assert store.guard_used(H.SCOPE,'chat')==20


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


def test_fake_interim_price_change_real_poll_to_verified_overrun(harness):
    build,store,_,_=harness
    fake,u,s,x,ctx,op,b=build('price_change_interim')
    run(s.dispatch(x,ctx,op))
    assert s.reconciler.snapshot(op,b).value['submissionCost']['credits']==32
    assert s.reconciler.snapshot(op,b).value['finalDebit']['state']=='unknown'
    assert store.pause(H.SCOPE,1) is None
    s.reconciler.ledger_verifier=ledger_verifier(fake)
    for _ in range(3): r=run(s.poll(op,b)).to_json()
    assert r['state']=='SETTLED_OVERRUN' and r['finalDebit']['credits']==32
    assert store.pause(H.SCOPE,1).value['actualCredits']==32
    run(s.dispatch(x,ctx,op))
    assert u.paid_calls==1 and len(fake.jobs)==1
