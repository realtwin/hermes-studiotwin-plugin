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
