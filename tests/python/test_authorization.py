"""S09 offline tests of real SQLite, reviewed transforms and host consent.
Positive principal/elicitation fixtures are NOT a shipped D24/D31 issuer.
"""
import asyncio
from concurrent.futures import ThreadPoolExecutor
import hashlib
import hmac
import json
from pathlib import Path
import sys
import types

import pytest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
pkg = types.ModuleType('s09_gateway')
pkg.__path__ = [str(ROOT/'gateway')]
sys.modules[pkg.__name__] = pkg
from s09_gateway import classification as C, redaction as R
from s09_gateway import canonical as K, policy_store as P, authorization as A
from s09_gateway.host_context import HostContextGate, META_KEY
from s09_gateway.capabilities import CAPABILITIES

TOOLS = json.loads((ROOT/'tests/fixtures/tools-list-2026-10-30.json').read_text())['tools']
SCOPE = 'a'*64
NAME = 'text-to-environment-map'
UUID = '12345678-1234-1234-1234-123456789abc'
OTHER = '22345678-1234-1234-1234-123456789abc'
KEY = b'offline-test-key-32-bytes-long-xxx'


def mac(payload, domain):
    return hmac.new(KEY,domain.encode()+b'\0'+json.dumps(payload,sort_keys=True,separators=(',',':')).encode(),hashlib.sha256).hexdigest()


def host(name=NAME,session='chat',run='interactive',nonce=1,gate=None):
    gate = gate or HostContextGate(key=KEY,host_instance_nonce='a'*43,profile_id='profile',connection_id='local')
    value = dict(hostInstanceNonce='a'*43,profileId='profile',connectionId='local',sessionId=session,
                 runKind=run,cronRunId='cron-run' if run=='cron' else None,toolName=name,
                 turnId='turn',toolCallId='call',callNonce=nonce)
    value['mac']=mac(value,'trusted-tool-context-v1')
    context=gate.receive(arguments={},metadata={META_KEY:value})
    caps=dict(protocol='studiotwin.host-gateway.v1',hostVersion='0.22.3',hostVersionStatus='at-or-above-floor',
              versionSource='running-distribution-metadata',capabilities={k:True for k in CAPABILITIES})
    return gate,context,gate.verify_capabilities(caps,mac(caps,'host-capabilities-v1'))


@pytest.fixture
def catalog():
    return C.Classification(TOOLS)


@pytest.fixture
def store(tmp_path):
    s=P.PolicyStore(tmp_path/'data')
    s.activate(SCOPE,'b'*64)
    yield s
    s.close()


def candidate(catalog, name=NAME, values=None, generation=1, scope=SCOPE):
    return catalog.candidate_inputs(name,C.RELEASE['tools'][name]['schemaHash'],
        values if values is not None else dict(prompt='harbor',seed=1),
        scope_id=scope,generation=generation,sensitive_values=())


def effective(catalog,store,name=NAME,values=None,**kwargs):
    return K.canonicalize(candidate(catalog,name,values,**kwargs),classification=catalog,store=store,sensitive_values=())


def test_canonical_deterministic_detached_and_effective_digest(catalog,store):
    x=effective(catalog,store)
    y=effective(catalog,store,values=dict(seed=1,prompt='harbor'))
    assert x.canonical_input_hash == y.canonical_input_hash
    assert x.canonical_input_hash == hashlib.sha256(b'{"prompt":"harbor","seed":1}').hexdigest()
    assert x.to_json()==dict(prompt='harbor',seed=1)
    x.to_json()['prompt']='changed'
    assert x.to_json()['prompt']=='harbor'
    with pytest.raises((AttributeError,TypeError)):
        x.values['prompt']='changed'
    with pytest.raises(R.BoundaryRefused):
        K.EffectiveInputs()


@pytest.mark.parametrize('name,values,expected',[
 ('text-to-material',dict(textPrompt='stone',resolution=1024,maskAssetId=UUID,referenceImageAssetId=OTHER),
  dict(textPrompt='stone',resolution=1024,maskUrl='vpc::assets/'+UUID,referenceImageUrl='vpc::assets/'+OTHER)),
 ('openai-gpt-image-2-v4-fn',dict(mode='edit',prompt='blue',masks=[UUID],sourceAsset=OTHER),
  dict(mode='edit',prompt='blue',masks=['vpc::assets/'+UUID],sourceAsset='vpc::assets/'+OTHER)),
 ('prompt-to-dart-translation',dict(inputPrompt='x',prompt='y',maxOutputUnits=5),
  dict(inputPrompt='x',prompt='y',maxTokens=5)),
 ('studiotwin_conceptlab_attach_asset',dict(conceptId=OTHER,assetId=UUID),dict(conceptId=OTHER,assetId=UUID)),
])
def test_reviewed_transforms(catalog,store,name,values,expected):
    store.adopt_asset(SCOPE,1,UUID)
    store.adopt_asset(SCOPE,1,OTHER)
    x=effective(catalog,store,name,values)
    assert x.to_json()==expected
    assert x.canonical_input_hash==hashlib.sha256(json.dumps(expected,sort_keys=True,separators=(',',':')).encode()).hexdigest()


@pytest.mark.parametrize('scope,generation',[(SCOPE,1),('c'*64,1),(SCOPE,0)])
def test_unowned_unknown_foreign_generation_assets_refuse(catalog,store,scope,generation):
    if (scope,generation)!=(SCOPE,1):
        store.adopt_asset(scope,generation,UUID)
    with pytest.raises(R.BoundaryRefused):
        effective(catalog,store,'image-to-environment-map',dict(prompt='x',seed=1,referenceImage=UUID))


@pytest.mark.parametrize('values',[dict(prompt='x',seed=1,unknown=True),dict(prompt='x',seed=1,approved=True),
                                  dict(prompt='https://bad.invalid/?secret=x',seed=1)])
def test_unknown_or_secret_candidates_refuse(catalog,store,values):
    with pytest.raises(R.BoundaryRefused):
        effective(catalog,store,values=values)


@pytest.mark.parametrize('suffix',['create_and_generate','generate','edit'])
def test_d22_refused(catalog,store,suffix):
    with pytest.raises(R.BoundaryRefused):
        effective(catalog,store,'studiotwin_conceptlab_'+suffix,{})


def test_generation_a_b_a_invalidates_candidates_and_handles(catalog,store):
    from s09_gateway.handles import HandleStore,HandleNotFound
    handles=HandleStore()
    token=handles.mint(scope_id=SCOPE,generation=1,purpose='resource',kind='image',role='preview',mime='image/png',size=1,target={})
    old=candidate(catalog)
    assert store.activate('c'*64,'d'*64,handles=handles)==2
    assert store.activate(SCOPE,'b'*64,handles=handles)==3
    with pytest.raises(R.BoundaryRefused):
        K.canonicalize(old,classification=catalog,store=store,sensitive_values=())
    with pytest.raises(HandleNotFound):
        handles.resolve(token,scope_id=SCOPE,generation=1,purpose='resource',operation='read')
    assert store.activate(SCOPE,'b'*64)==3


def preview(tool=NAME,credits=20,now=1000,mode='interim-local'):
    value=dict(contract='studiotwin.dashboard.v1',authorizes=False,enforcementMode=mode,tool=tool,
               executable=True,disabledReason=None,previewId='pv_'+'a'*43,estimatedCredits=credits,
               estimateLabel='estimated charge',observedAtMs=now,previewExpiresAtMs=now+100,
               balance={'state':'unknown'},guardRemaining=200,scopePaused=False)
    if mode=='server-max-credits':
        value.update(maxCredits=25,estimateLabel='server-enforced maximum')
    return value


def binding(x,context):
    return dict(scope_id=x.scope_id,generation=x.generation,session_id=context['sessionId'],
                turn_id=context['turnId'],tool_call_id=context['toolCallId'],tool=x.tool,
                schema_hash=x.schema_hash,canonical_input_hash=x.canonical_input_hash)


def quote(store,x,context,**changes):
    p=preview(x.tool)
    p.update(changes)
    return store.save_quote(p,binding(x,context),price_version=None,server_token=None,now_ms=1000)


async def accept(request):
    return {'action':'accept','elicitationId':request['elicitationId']}


def service(catalog,store,gate,caps):
    return A.AuthorizationService(catalog,store,gate=gate,host_capabilities=caps,endpoint_origin='https://staging.example',
                                  clock_ms=lambda:1001,elicit=accept)


def future_principal(monkeypatch):
    # Explicit absent-future-issuer fixture; never production trust from a boolean.
    monkeypatch.setattr(A,'_principal_scope',lambda *args,**kwargs:SCOPE)
    monkeypatch.setattr(A,'_mode_ready',lambda mode:True)  # S10 capability/risk fixture only


def test_real_d24_missing_cannot_be_bypassed(catalog,store):
    gate,ctx,caps=host()
    x=effective(catalog,store)
    q=quote(store,x,ctx)
    with pytest.raises(R.BoundaryRefused):
        asyncio.run(service(catalog,store,gate,caps).authorize(x,ctx,q))
    assert store.operation_count()==0


@pytest.mark.parametrize('run',['cron','api','kanban'])
@pytest.mark.parametrize('name,values',[(NAME,None),('studiotwin_conceptlab_create',dict(conceptType='object',name='draft'))])
def test_unattended_paid_and_free_mutation_refused(catalog,store,monkeypatch,run,name,values):
    future_principal(monkeypatch)
    gate,ctx,caps=host(name,run=run)
    x=effective(catalog,store,name,values)
    q=quote(store,x,ctx)
    with pytest.raises(R.BoundaryRefused):
        asyncio.run(service(catalog,store,gate,caps).authorize(x,ctx,q))
    assert store.operation_count()==0


def test_host_provenance_and_capabilities(catalog,store,monkeypatch):
    future_principal(monkeypatch)
    gate,ctx,caps=host()
    x=effective(catalog,store); q=quote(store,x,ctx)
    for context,cap in [(dict(ctx),caps),(types.MappingProxyType(dict(ctx)),caps),(ctx,None),(ctx,{'trusted':True})]:
        with pytest.raises(R.BoundaryRefused):
            asyncio.run(service(catalog,store,gate,cap).authorize(x,context,q))
    assert store.operation_count()==0


def test_interactive_consent_and_atomic_reservation(catalog,store,monkeypatch):
    future_principal(monkeypatch)
    gate,ctx,caps=host(); x=effective(catalog,store); q=quote(store,x,ctx)
    svc=service(catalog,store,gate,caps)
    result=asyncio.run(svc.authorize(x,ctx,q))
    assert type(result) is R.MediatedValue
    auth=result.to_json()
    assert auth['maxCredits']==auth['estimatedCredits']==20
    assert auth['trustedSessionId']==auth['runId']=='chat'
    assert auth['canonicalInputHash']==x.canonical_input_hash
    op=store.get_operation(auth['operationId'],binding(x,ctx))
    assert op['state']=='RESERVED_UNSENT' and op['reservedCredits']==20
    assert store.guard_used(SCOPE,'chat')==20
    with pytest.raises(R.BoundaryRefused):
        asyncio.run(svc.authorize(x,ctx,q))
    assert store.operation_count()==1


@pytest.mark.parametrize('response',[True,{'action':'accept'}, {'action':'accept','elicitationId':'el_'+'z'*43},
                                     {'action':'decline'}, {'action':'accept','remember':True}])
def test_forged_or_remembered_consent_refused(catalog,store,monkeypatch,response):
    future_principal(monkeypatch)
    gate,ctx,caps=host(); x=effective(catalog,store); q=quote(store,x,ctx)
    svc=service(catalog,store,gate,caps)
    async def bad(_): return response
    svc._elicit=bad
    with pytest.raises(R.BoundaryRefused): asyncio.run(svc.authorize(x,ctx,q))
    assert store.operation_count()==0


@pytest.mark.parametrize('field,value',[
 ('observedAtMs',1101),('observedAtMs',None),('previewExpiresAtMs',999),
 ('estimateLabel','server-enforced maximum'),('maxCredits',20),('scopePaused',True),
 ('tool','text-to-motion'),('executable',False)])
def test_quote_relations_refuse_before_store(catalog,store,field,value):
    gate,ctx,caps=host(); x=effective(catalog,store)
    with pytest.raises(R.BoundaryRefused): quote(store,x,ctx,**{field:value})
    assert store.quote_count()==0


@pytest.mark.parametrize('field,value',[
 ('session_id','other'),('turn_id','other'),('tool_call_id','other'),('tool','text-to-motion'),
 ('schema_hash','f'*64),('canonical_input_hash','f'*64),('scope_id','c'*64),('generation',2)])
def test_exact_quote_binding(catalog,store,monkeypatch,field,value):
    future_principal(monkeypatch)
    gate,ctx,caps=host(); x=effective(catalog,store); q=quote(store,x,ctx)
    expected=binding(x,ctx); expected[field]=value
    with pytest.raises(R.BoundaryRefused): store.load_quote(q,expected,now_ms=1001)
    assert store.operation_count()==0


def test_expiry_during_host_consent_and_rotation(catalog,store,monkeypatch):
    future_principal(monkeypatch)
    gate,ctx,caps=host(); x=effective(catalog,store); q=quote(store,x,ctx)
    svc=service(catalog,store,gate,caps)
    async def expired(request):
        svc._clock_ms=lambda:1100
        return await accept(request)
    svc._elicit=expired
    with pytest.raises(R.BoundaryRefused): asyncio.run(svc.authorize(x,ctx,q))
    assert store.operation_count()==0


def test_scope_pause_across_sessions(catalog,store,monkeypatch):
    future_principal(monkeypatch)
    gate,ctx,caps=host(session='other'); x=effective(catalog,store); q=quote(store,x,ctx)
    pause=dict(protocol='studiotwin.gateway.v1',scopeId=SCOPE,reason='verified-overrun',operationId='op_'+'z'*43,
               estimatedCredits=10,actualCredits=20,createdAtMs=1000,acknowledgedAtMs=None)
    store.put_pause(pause,generation=1)
    assert store.pause(SCOPE,1).to_json()==pause
    with pytest.raises(R.BoundaryRefused): asyncio.run(service(catalog,store,gate,caps).authorize(x,ctx,q))
    assert store.operation_count()==0


def test_concurrent_same_quote_once_and_restart(catalog,store,tmp_path,monkeypatch):
    future_principal(monkeypatch)
    gate,ctx,caps=host(); x=effective(catalog,store); q=quote(store,x,ctx)
    def worker(_):
        s=P.PolicyStore(tmp_path/'data')
        try:
            try: return asyncio.run(service(catalog,s,gate,caps).authorize(x,ctx,q)).to_json()
            except R.BoundaryRefused: return None
        finally: s.close()
    results=list(ThreadPoolExecutor(8).map(worker,range(8)))
    winners=[r for r in results if r]
    assert len(winners)==1
    assert store.operation_count()==1 and store.guard_used(SCOPE,'chat')==20
    worker(0)
    assert store.operation_count()==1
    assert store.get_operation(winners[0]['operationId'],binding(x,ctx))['state']=='RESERVED_UNSENT'


def test_concurrent_guard_straddle_and_session_isolation(catalog,store,tmp_path,monkeypatch):
    future_principal(monkeypatch)
    gate,ctx,caps=host(); x=effective(catalog,store)
    store.set_guard_limit(SCOPE,'chat',30)
    p1=preview(); p2=preview(); p2['previewId']='pv_'+'b'*43
    qs=[store.save_quote(p,binding(x,ctx),price_version=None,server_token=None,now_ms=1000) for p in [p1,p2]]
    def worker(q):
        s=P.PolicyStore(tmp_path/'data')
        try:
            try: return asyncio.run(service(catalog,s,gate,caps).authorize(x,ctx,q)) is not None
            except R.BoundaryRefused: return False
        finally: s.close()
    assert sum(ThreadPoolExecutor(2).map(worker,qs))==1
    assert store.guard_used(SCOPE,'chat')==20
    assert store.guard_used(SCOPE,'other')==0
    assert store.guard_limit(SCOPE,'other')==200
    with pytest.raises(R.BoundaryRefused): store.set_guard_limit(SCOPE,'other',201)
    store.set_guard_limit(SCOPE,'other',250,explicit_user_setting=True)
    assert store.guard_limit(SCOPE,'other')==250


@pytest.mark.parametrize('mode',['interim-local','server-max-credits'])
def test_mode_proof_is_independent_of_principal(catalog,store,monkeypatch,mode):
    monkeypatch.setattr(A,'_principal_scope',lambda *args:SCOPE)
    gate,ctx,caps=host(); x=effective(catalog,store)
    p=preview(mode=mode)
    q=store.save_quote(p,binding(x,ctx),price_version='price-1',
                       server_token='sqt_'+'s'*43 if mode=='server-max-credits' else None,now_ms=1000)
    with pytest.raises(R.BoundaryRefused): asyncio.run(service(catalog,store,gate,caps).authorize(x,ctx,q))
    assert store.operation_count()==0


def test_server_maximum_not_estimate_and_token_binding(catalog,store,monkeypatch):
    future_principal(monkeypatch)
    gate,ctx,caps=host(); x=effective(catalog,store)
    p=preview(mode='server-max-credits')
    q=store.save_quote(p,binding(x,ctx),price_version='price-1',server_token='sqt_'+'s'*43,now_ms=1000)
    a=asyncio.run(service(catalog,store,gate,caps).authorize(x,ctx,q)).to_json()
    assert a['estimatedCredits']==20 and a['maxCredits']==25
    assert a['serverQuoteToken']=='sqt_'+'s'*43
    assert store.get_operation(a['operationId'],binding(x,ctx))['reservedCredits']==25
    assert store.guard_used(SCOPE,'chat')==25


@pytest.mark.parametrize('field,value',[
 ('canonicalInputHash','f'*64),('schemaHash','f'*64),('trustedSessionId','other'),('runId','other'),
 ('scopeId','c'*64),('tool','text-to-motion'),('previewId','pv_'+'b'*43),
 ('previewExpiresAtMs',1200),('estimatedCredits',19),('maxCredits',19),
 ('createdAtMs',1002),('createdAtMs',999),('expiresAtMs',1001),('expiresAtMs',1101),
 ('enforcementMode','server-max-credits')])
def test_complete_authorization_relations(catalog,store,monkeypatch,field,value):
    future_principal(monkeypatch)
    gate,ctx,caps=host(); x=effective(catalog,store); q=quote(store,x,ctx)
    a=asyncio.run(service(catalog,store,gate,caps).authorize(x,ctx,q)).to_json()
    # Independent complete-envelope relation checker, followed by real reserve
    # probes in other tests. No JSON-schema equality claim.
    a[field]=value
    with pytest.raises(R.BoundaryRefused): P.check_authorization(a,preview(),binding(x,ctx),1001)


def test_server_token_bound_to_exact_quote(catalog,store,monkeypatch):
    future_principal(monkeypatch)
    gate,ctx,caps=host(); x=effective(catalog,store)
    q=quote(store,x,ctx)
    a=asyncio.run(service(catalog,store,gate,caps).authorize(x,ctx,q)).to_json()
    p=preview(mode='server-max-credits'); p['previewId']='pv_'+'b'*43
    q2=store.save_quote(p,binding(x,ctx),price_version='price-2',server_token='sqt_'+'s'*43,now_ms=1000)
    a.update(operationId='op_'+'b'*43,previewId=q2,enforcementMode='server-max-credits',maxCredits=25,
             previewPriceVersion='price-2',serverQuoteToken='sqt_'+'t'*43)
    with pytest.raises(R.BoundaryRefused): store.reserve(a,binding(x,ctx),now_ms=1001)
    assert store.operation_count()==1


def test_operation_id_cannot_be_reused_for_another_quote(catalog,store,monkeypatch):
    future_principal(monkeypatch)
    gate,ctx,caps=host(); x=effective(catalog,store); q=quote(store,x,ctx)
    a=asyncio.run(service(catalog,store,gate,caps).authorize(x,ctx,q)).to_json()
    p=preview(); p['previewId']='pv_'+'b'*43
    q2=store.save_quote(p,binding(x,ctx),price_version=None,server_token=None,now_ms=1000)
    a['previewId']=q2
    with pytest.raises(R.BoundaryRefused): store.reserve(a,binding(x,ctx),now_ms=1001)
    assert store.operation_count()==1 and store.guard_used(SCOPE,'chat')==20


def test_spend_guard_counts_settled_debits_without_double_count(catalog,store,monkeypatch):
    future_principal(monkeypatch)
    gate,ctx,caps=host(); x=effective(catalog,store); q=quote(store,x,ctx)
    a=asyncio.run(service(catalog,store,gate,caps).authorize(x,ctx,q)).to_json()
    # S10 owns certification/transition; seed a ledger row with explicit final
    # evidence result to exercise S09's real aggregation SQL (not settlement proof).
    with store.transaction():
        store._db.execute("UPDATE policy_operations SET state='SETTLED',final_debit=30 WHERE scope_id=? AND operation_id=?",(SCOPE,a['operationId']))
    assert store.guard_used(SCOPE,'chat')==30  # not estimate 20, not 20+30
    store.set_guard_limit(SCOPE,'chat',40)
    p=preview(); p['previewId']='pv_'+'b'*43
    q2=store.save_quote(p,binding(x,ctx),price_version=None,server_token=None,now_ms=1000)
    with pytest.raises(R.BoundaryRefused): asyncio.run(service(catalog,store,gate,caps).authorize(x,ctx,q2))
    assert store.operation_count()==1


def test_n3_preflight_uses_tier_not_cost_class(catalog,store,monkeypatch):
    future_principal(monkeypatch)
    name='studiotwin_conceptlab_create'
    gate,ctx,caps=host(name,run='kanban')
    x=effective(catalog,store,name,dict(conceptType='object',name='draft'))
    assert C.RELEASE['tools'][name]['costClass']=='free_read'
    with pytest.raises(R.BoundaryRefused): service(catalog,store,gate,caps)._context(x,ctx)


@pytest.mark.parametrize('field,value',[('turn_id','STCANARY_binding'),('schema_hash','not-a-hash'),
                                       ('canonical_input_hash','not-a-hash'),('generation',True)])
def test_unsafe_bindings_never_persist(catalog,store,field,value):
    gate,ctx,caps=host(); x=effective(catalog,store)
    b=binding(x,ctx); b[field]=value
    with pytest.raises(R.BoundaryRefused): store.save_quote(preview(),b,price_version=None,server_token=None,now_ms=1000)
    assert store.quote_count()==0


def test_price_metadata_secret_never_persists(catalog,tmp_path):
    s=P.PolicyStore(tmp_path/'secrets',sensitive_values=('ordinary-sensitive-value',))
    try:
        s.activate(SCOPE,'b'*64)
        gate,ctx,caps=host(); x=effective(catalog,s)
        with pytest.raises(R.BoundaryRefused):
            s.save_quote(preview(),binding(x,ctx),price_version='ordinary-sensitive-value',server_token=None,now_ms=1000)
        assert s.quote_count()==0
    finally: s.close()


def test_automatic_settings_cannot_raise_lowered_guard(store):
    store.set_guard_limit(SCOPE,'chat',50)
    with pytest.raises(R.BoundaryRefused): store.set_guard_limit(SCOPE,'chat',100)
    assert store.guard_limit(SCOPE,'chat')==50


def test_real_process_restart_and_concurrent_duplicate(catalog,store,tmp_path,monkeypatch):
    import subprocess
    future_principal(monkeypatch)
    gate,ctx,caps=host(); x=effective(catalog,store); q=quote(store,x,ctx)
    a=asyncio.run(service(catalog,store,gate,caps).authorize(x,ctx,q)).to_json()
    p=preview(); p['previewId']='pv_'+'b'*43
    q2=store.save_quote(p,binding(x,ctx),price_version=None,server_token=None,now_ms=1000)
    a.update(operationId='op_'+'r'*43,previewId=q2)
    payload=json.dumps(dict(auth=a,binding=binding(x,ctx)))
    processes=[subprocess.Popen([sys.executable,__file__,'ledger-probe',str(tmp_path/'data')],
                    stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(2)]
    results=[p.communicate(payload,timeout=30) for p in processes]
    assert all(p.returncode==0 for p in processes),results
    assert sorted(r[0].strip() for r in results)==['refused','reserved']
    restarted=subprocess.run([sys.executable,__file__,'ledger-probe',str(tmp_path/'data')],
                    input=payload,capture_output=True,text=True,timeout=30)
    assert restarted.returncode==0 and restarted.stdout.strip()=='refused'
    assert store.operation_count()==2 and store.guard_used(SCOPE,'chat')==40


@pytest.mark.parametrize('dimension,other',[('profileId','other-profile'),('connectionId','ssh'),
    ('endpointOrigin','https://production.example'),('accountId','other-account'),('orgId','other-org')])
def test_full_scope_tuple_a_b_a_and_credential_rotation(tmp_path,dimension,other):
    s=P.PolicyStore(tmp_path/'tuple-data')
    try:
        identity=dict(profileId='profile',connectionId='local',endpointOrigin='https://staging.example',
                      accountId='account',orgId='organization')
        a,g1=s.activate_scope(identity,scope_key=KEY,credential_epoch='a'*64)
        changed={**identity,dimension:other}
        b,g2=s.activate_scope(changed,scope_key=KEY,credential_epoch='a'*64)
        assert a!=b and g2>g1
        again,g3=s.activate_scope(identity,scope_key=KEY,credential_epoch='a'*64)
        assert again==a and g3>g2
        same,g4=s.activate_scope(identity,scope_key=KEY,credential_epoch='b'*64)
        assert same==a and g4>g3
        with pytest.raises(R.BoundaryRefused): s.require_current(a,g1)
        wire=(tmp_path/'tuple-data/studiotwin.sqlite3').read_bytes()
        assert b'other-account' not in wire and b'organization' not in wire and KEY not in wire
    finally: s.close()


def test_rotation_while_elicitation_waits_quarantines_approval(catalog,store,monkeypatch):
    future_principal(monkeypatch)
    gate,ctx,caps=host(); x=effective(catalog,store); q=quote(store,x,ctx)
    svc=service(catalog,store,gate,caps)
    async def rotate(request):
        store.activate('c'*64,'d'*64)
        store.activate(SCOPE,'b'*64)
        return await accept(request)
    svc._elicit=rotate
    with pytest.raises(R.BoundaryRefused): asyncio.run(svc.authorize(x,ctx,q))
    assert store.quote_count()==store.operation_count()==0


def test_newly_registered_secret_rechecked_after_consent(catalog,tmp_path,monkeypatch):
    future_principal(monkeypatch)
    secrets=[]
    s=P.PolicyStore(tmp_path/'late-secret',sensitive_values=secrets)
    try:
        s.activate(SCOPE,'b'*64)
        gate,ctx,caps=host(); x=effective(catalog,s); q=quote(s,x,ctx)
        svc=service(catalog,s,gate,caps)
        async def changed(request):
            secrets.append('harbor')
            return await accept(request)
        svc._elicit=changed
        svc._sensitive=secrets
        with pytest.raises(R.BoundaryRefused): asyncio.run(svc.authorize(x,ctx,q))
        assert s.operation_count()==0
    finally: s.close()


def test_no_raw_candidate_or_effective_value_can_mint_consent(catalog,store,monkeypatch):
    future_principal(monkeypatch)
    gate,ctx,caps=host(); x=effective(catalog,store); q=quote(store,x,ctx)
    for raw in (x.to_json(),x.candidate,{'approved':True},None):
        with pytest.raises(R.BoundaryRefused): asyncio.run(service(catalog,store,gate,caps).authorize(raw,ctx,q))
    assert store.operation_count()==0


def test_pause_appearing_after_consent_blocks_atomic_reserve(catalog,store,monkeypatch):
    future_principal(monkeypatch)
    gate,ctx,caps=host(); x=effective(catalog,store); q=quote(store,x,ctx)
    auth=asyncio.run(service(catalog,store,gate,caps).authorize(x,ctx,q)).to_json()
    p=preview(); p['previewId']='pv_'+'b'*43
    q2=store.save_quote(p,binding(x,ctx),price_version=None,server_token=None,now_ms=1000)
    auth.update(operationId='op_'+'b'*43,previewId=q2)
    store.put_pause(dict(protocol='studiotwin.gateway.v1',scopeId=SCOPE,reason='verified-overrun',
        operationId='op_'+'z'*43,estimatedCredits=10,actualCredits=20,createdAtMs=1000,acknowledgedAtMs=None),generation=1)
    with pytest.raises(R.BoundaryRefused): store.reserve(auth,binding(x,ctx),now_ms=1001)
    assert store.operation_count()==1 and store.guard_used(SCOPE,'chat')==20


def test_all_required_outbound_envelopes_use_real_s06(catalog,store,monkeypatch):
    future_principal(monkeypatch)
    calls=[]
    actual=R.validate_mediated_v1
    def spy(ref,*args,**kwargs):
        calls.append(ref)
        return actual(ref,*args,**kwargs)
    monkeypatch.setattr(R,'validate_mediated_v1',spy)
    gate,ctx,caps=host(); x=effective(catalog,store); q=quote(store,x,ctx)
    asyncio.run(service(catalog,store,gate,caps).authorize(x,ctx,q))
    store.put_pause(dict(protocol='studiotwin.gateway.v1',scopeId=SCOPE,reason='verified-overrun',
        operationId='op_'+'z'*43,estimatedCredits=10,actualCredits=20,createdAtMs=1000,acknowledgedAtMs=None),generation=1)
    assert {'dashboard#/components/schemas/QuotePreviewV1', 'gateway#/$defs/AuthorizationV1',
            'gateway#/$defs/SpendGuardKeyV1','gateway#/$defs/ScopePauseV1'} <= set(calls)


def test_policy_tables_keep_scope_in_every_unique_key(store):
    names=[r[0] for r in store._db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'policy_%'")]
    assert names
    for name in names:
        columns=list(store._db.execute('PRAGMA table_info('+name+')'))
        assert columns[0][1]=='scope_id'
        primary=[r[1] for r in columns if r[5]]
        assert 'scope_id' in primary,(name,primary)
        for index in store._db.execute('PRAGMA index_list('+name+')'):
            if index[2]:
                fields=[r[2] for r in store._db.execute('PRAGMA index_info('+index[1]+')')]
                assert 'scope_id' in fields,(name,fields)
    store.activate('c'*64,'d'*64)
    store.activate(SCOPE,'b'*64)
    assert store._db.execute('SELECT COUNT(*) FROM policy_active').fetchone()[0]==1


def test_policy_database_uses_private_s05_storage(tmp_path):
    import os
    import stat
    s=P.PolicyStore(tmp_path/'private')
    try:
        s.activate(SCOPE,'b'*64)
        if os.name=='posix':
            assert stat.S_IMODE((tmp_path/'private').stat().st_mode)==0o700
            assert stat.S_IMODE((tmp_path/'private/studiotwin.sqlite3').stat().st_mode)==0o600
    finally: s.close()


if __name__=='__main__' and len(sys.argv)==3 and sys.argv[1]=='ledger-probe':
    payload=json.load(sys.stdin)
    s=P.PolicyStore(Path(sys.argv[2]))
    try:
        try:
            s.reserve(payload['auth'],payload['binding'],now_ms=1001)
            print('reserved')
        except R.BoundaryRefused:
            print('refused')
    finally: s.close()
