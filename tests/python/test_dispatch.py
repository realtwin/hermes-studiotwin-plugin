"""Offline S10: actual S09 consent/SQLite and S02 upstream, never live spend."""
import asyncio
import json
from pathlib import Path
import sys

import pytest
import test_authorization as H
from s09_gateway import dispatch as D, reconcile as Q, scope_pause as SP
from s09_gateway.mediation import Mediator
from s09_gateway.handles import HandleStore
from tests.fixtures.fake_mcp import FakeStudioTwin, scenario
from tests.fixtures.fake_mcp.state import Hang
from tests.fixtures.fake_mcp.server import to_wire


def run(awaitable):
    return asyncio.run(awaitable)


class OfflineProof(D.ChargePolicy):
    """Proposed D30 issuer fixture, NOT advertised-capability-as-proof."""
    def __init__(self, fake):
        super().__init__(interim_risk_accepted=True)
        self.fake = fake

    def server_binding_verified(self, authorization, binding):
        return (self.fake.scenario.server_max_credits and
                authorization.get('serverQuoteToken') == 'sqt_'+'s'*43 and
                authorization['canonicalInputHash'] == binding['canonical_input_hash'])

    def predebit_rejection_verified(self, authorization, binding, response):
        return (self.server_binding_verified(authorization, binding) and
                not self.fake.jobs and any(e['event']=='rejected_price_exceeds_max' for e in self.fake.ledger))


class Upstream:
    def __init__(self, fake, store=None, binding=None, operation=None):
        self.fake, self.store, self.binding, self.operation = fake, store, binding, operation
        self.fail = None
        self.paid_calls = 0
        self.durable_seen = []

    async def __call__(self, tool, inputs, event):
        if tool == H.NAME or tool == 'studiotwin_conceptlab_create':
            self.paid_calls += 1
            if self.store is not None:
                # An independent connection proves committed state before RPC.
                other=H.P.PolicyStore(self.store_path)
                self.durable_seen.append(other.get_operation(self.operation,self.binding)['state'])
                other.close()
        out = self.fake.call(tool, inputs)
        if isinstance(out, Hang):
            raise TimeoutError('offline transport loss')
        for p in out.progress:
            event({'progress':p})
        for log in out.logs:
            event({'log':log})
        if self.fail and tool == H.NAME:
            raise RuntimeError(self.fail)
        return to_wire(out)


@pytest.fixture
def harness(tmp_path, monkeypatch):
    H.future_principal(monkeypatch)  # Explicit missing D24/D31/S09 mode fixture.
    catalog=H.C.Classification(H.TOOLS)
    path=tmp_path/'private'
    store=H.P.PolicyStore(path)
    store.activate(H.SCOPE,'b'*64)
    made=[]
    def build(mode='normal', enforcement='interim-local', name=H.NAME, values=None):
        fake=FakeStudioTwin(scenario(mode))
        gate,ctx,caps=H.host(name)
        x=H.effective(catalog,store,name,values)
        now=fake.clock_ms
        p=H.preview(name,credits=0 if name=='studiotwin_conceptlab_create' else 20,now=now,mode=enforcement)
        p['previewExpiresAtMs']=now+100000
        if enforcement=='server-max-credits': p['maxCredits']=20
        b=H.binding(x,ctx)
        store.save_quote(p,b,price_version='price-a',server_token='sqt_'+'s'*43 if enforcement=='server-max-credits' else None,
                         clock_ms=lambda:fake.clock_ms)
        auth=H.A.AuthorizationService(catalog,store,gate=gate,host_capabilities=caps,
            endpoint_origin='https://staging.example',elicit=H.accept,clock_ms=lambda:fake.clock_ms)
        op=run(auth.authorize(x,ctx,p['previewId'])).value['operationId']
        upstream=Upstream(fake,store,b,op); upstream.store_path=path
        service=D.DispatchService(auth,mediator=Mediator(HandleStore()),transport=upstream,
                                  charge_policy=OfflineProof(fake))
        made.append((fake,upstream,service,x,ctx,op,b))
        return made[-1]
    yield build,store,path,catalog
    store.close()


def test_durable_dispatch_once_duplicate_and_restart(harness):
    build,store,path,_=harness
    fake,u,s,x,ctx,op,b=build()
    result=run(s.dispatch(x,ctx,op)).to_json()
    assert u.durable_seen==['DISPATCHING']
    assert result['jobId'] in fake.jobs
    assert result['operation']['submissionCost']['credits']==20
    assert result['operation']['finalDebit']=={'state':'unknown'}
    assert result['operation']['reservationHeld'] is True
    run(s.dispatch(x,ctx,op))
    other=H.P.PolicyStore(path)
    other_auth=H.service(s.authorization._classification,other,s.authorization._gate,s.authorization._host_capabilities)
    other_auth._clock_ms=lambda:fake.clock_ms
    restarted=D.DispatchService(other_auth,mediator=Mediator(HandleStore()),transport=u,charge_policy=OfflineProof(fake))
    run(restarted.dispatch(x,ctx,op)); other.close()
    assert u.paid_calls==1 and len(fake.jobs)==1


@pytest.mark.parametrize('mode',['ambiguous_no_structured_content','ambiguous_empty_content','ambiguous_malformed_ack',
                                 'ambiguous_protocol_error_after_create','ambiguous_timeout_after_create'])
def test_ambiguous_no_replay_even_if_recovery_finds_job(harness,mode):
    build,store,_,_=harness
    fake,u,s,x,ctx,op,b=build(mode)
    result=run(s.dispatch(x,ctx,op)).to_json()
    assert result['operation']['reservationHeld'] is True
    assert store.get_operation(op,b)['state']=='AMBIGUOUS_UNRESOLVED'
    run(s.dispatch(x,ctx,op)); recovery=run(s.recover(op,b)).to_json()
    assert recovery['recovery']['dispatchAllowed'] is False
    assert len(recovery['recovery']['candidates'])==1
    assert recovery['operation']['finalDebit']=={'state':'unknown'}
    assert len(fake.jobs)==1 and u.paid_calls==1


def test_structured_content_error_and_delayed_zero_candidates_hold(harness):
    build,store,_,_=harness
    fake,u,s,x,ctx,op,b=build('delayed_list_visibility')
    u.fail='Tool has an output schema but did not return structured content'
    result=run(s.dispatch(x,ctx,op)).to_json()
    assert result['operation']['reservationHeld'] is True
    for _ in range(2):
        r=run(s.recover(op,b)).to_json()
        assert r['recovery']['state']=='not-visible'
        assert r['recovery']['candidates']==[]
        assert r['operation']['state']=='UNKNOWN_NOT_VISIBLE'
        assert r['operation']['reservationHeld'] is True
        assert store.guard_used(H.SCOPE,'chat')==20
    r=run(s.recover(op,b)).to_json()
    assert r['recovery']['state']=='matched'
    run(s.dispatch(x,ctx,op))
    assert u.paid_calls==1


def test_crash_after_commit_before_rpc_never_replays(harness):
    build,store,_,_=harness
    fake,u,s,x,ctx,op,b=build()
    class Crash(BaseException): pass
    async def crash(*args): raise Crash()
    s._transport=crash
    with pytest.raises(Crash): run(s.dispatch(x,ctx,op))
    assert store.get_operation(op,b)['state']=='DISPATCHING'
    s._transport=u
    r=run(s.dispatch(x,ctx,op)).to_json()
    assert r['operation']['reservationHeld'] is True
    assert u.paid_calls==0 and not fake.jobs


def test_server_max_price_change_rejects_before_debit(harness):
    build,store,_,_=harness
    fake,u,s,x,ctx,op,b=build('price_change_server_max','server-max-credits')
    r=run(s.dispatch(x,ctx,op)).to_json()['operation']
    assert r['state']=='RELEASED' and r['reservationHeld'] is False
    assert fake.balance==500 and not fake.jobs
    args=next(c['args'] for c in fake.calls if c['name']==H.NAME)
    assert args['maxCredits']==20 and args['serverQuoteToken']=='sqt_'+'s'*43
    assert not any(e['event']=='debit' for e in fake.ledger)
    run(s.dispatch(x,ctx,op)); assert u.paid_calls==1


@pytest.mark.parametrize('policy',[D.ChargePolicy(),D.ChargePolicy(interim_risk_accepted=False)])
def test_default_interim_risk_fails_closed(harness,policy):
    build,store,_,_=harness
    fake,u,s,x,ctx,op,b=build()
    s.charge_policy=policy
    with pytest.raises(H.R.BoundaryRefused): run(s.dispatch(x,ctx,op))
    assert not fake.jobs and store.get_operation(op,b)['state']=='RESERVED_UNSENT'


def test_advertised_max_is_not_proof(harness):
    build,store,_,_=harness
    fake,u,s,x,ctx,op,b=build('max_credits_advertised_not_enforced','server-max-credits')
    with pytest.raises(H.R.BoundaryRefused): run(s.dispatch(x,ctx,op))
    assert not fake.jobs


def test_immediate_estimate_change_releases_only_unsent(harness):
    build,store,_,_=harness
    fake,u,s,x,ctx,op,b=build()
    fake.estimate_for=lambda *_:21
    r=run(s.dispatch(x,ctx,op)).to_json()['operation']
    assert r['state']=='RELEASED'
    assert r['reservationHeld'] is False and not fake.jobs and u.paid_calls==0


def test_dispatch_checks_post_lock_expiry(harness):
    build,store,_,_=harness
    fake,u,s,x,ctx,op,b=build()
    original=store.transaction
    from contextlib import contextmanager
    @contextmanager
    def waited():
        with original():
            fake.clock_ms+=200000
            yield
    store.transaction=waited
    with pytest.raises(H.R.BoundaryRefused): run(s.dispatch(x,ctx,op))
    assert not fake.jobs and u.paid_calls==0


@pytest.mark.parametrize('run_kind',['cron','api','kanban'])
def test_free_mutation_never_unattended_read_path(harness,run_kind):
    build,store,_,catalog=harness
    fake,u,s,x,ctx,op,b=build(name='studiotwin_conceptlab_create',values=dict(conceptType='object',name='draft'))
    gate,unattended,caps=H.host(x.tool,run=run_kind)
    s.authorization._gate=gate; s.authorization._host_capabilities=caps
    with pytest.raises(H.R.BoundaryRefused): run(s.read(x,unattended))
    assert u.paid_calls==0


def test_all_channels_mediate_and_validate_no_persisted_secrets(harness,monkeypatch):
    build,store,_,_=harness
    fake,u,s,x,ctx,op,b=build('secret_channels')
    from tests.fixtures.fake_mcp import canaries
    seen=[]
    old=s.mediator.mediate
    def mediate(raw,**kwargs):
        seen.append(raw)
        return old(raw,**kwargs)
    monkeypatch.setattr(s.mediator,'mediate',mediate)
    r=run(s.dispatch(x,ctx,op)).to_json()
    assert len(seen)>=3
    assert canaries.find(json.dumps(r))==[]
    persisted=' '.join(str(row) for row in store._db.iterdump())
    assert canaries.find(persisted)==[]
    assert 'https://' not in persisted and 'structuredContent' not in persisted
