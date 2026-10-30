"""S08 offline release classification and actual boundary tests. No hosted I/O."""
import asyncio
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import types

import pytest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
pkg = types.ModuleType('s08_gateway')
pkg.__path__ = [str(ROOT / 'gateway')]
sys.modules[pkg.__name__] = pkg
from s08_gateway import classification as C, redaction as R, capabilities as CAP

TOOLS = json.loads((ROOT/'tests/fixtures/tools-list-2026-10-30.json').read_text())['tools']
BY_NAME = {t['name']: t for t in TOOLS}
BIND = dict(scope_id='a'*64, generation=1, sensitive_values=())
NAME = 'text-to-environment-map'
D22 = {'studiotwin_conceptlab_'+n for n in ('create_and_generate','generate','edit')}
FORM_REF = 'dashboard#/components/schemas/ToolInputSchemaResponseV1'
IPC_REF = 'host_gateway#/$defs/IpcResponseV1'


def digest(t):
    data = {k:t.get(k) for k in ('name','inputSchema','outputSchema')}
    return hashlib.sha256(json.dumps(data,sort_keys=True,separators=(',',':'),ensure_ascii=True).encode()).hexdigest()


def release():
    return C.Classification(TOOLS)


def form(schema=None):
    return dict(contract='studiotwin.dashboard.v1',tool=NAME,schemaHash=digest(BY_NAME[NAME]),
                classification='classified',inputSchema=schema or {'kind':'object','fields':[
                    {'name':'prompt','required':True,'schema':{'kind':'string','maxLength':40}}]})


def envelope(payload):
    return dict(protocol='studiotwin.host-gateway.v1',requestId='rq_'+'a'*22,ok=True,
                result={'method':'capabilities.inputSchema','payload':payload})


def refuse(fn):
    with pytest.raises(R.BoundaryRefused) as e:
        fn()
    assert str(e.value) == 'UNSAFE_PAYLOAD'
    assert e.value.__cause__ is None and e.value.__context__ is None


def test_manifest_exact_inventory_hash_cost_and_policy():
    rows = C.RELEASE['tools']
    assert len(rows) == len(TOOLS) == 45
    assert set(rows) == set(BY_NAME)
    for name, row in rows.items():
        assert row['schemaHash'] == digest(BY_NAME[name])
        assert row['costClass'] in {'free_read','free_compute','paid_fixed','paid_dynamic'}
        assert row['tier'] in {'hosted-read','hosted-mutation','paid'}
        assert row['family'] in {'generation','platform','concept'}
        assert row['mediation']['mode'] == 'classified-summary'
        assert row['inputSchema']['kind'] == 'object'
        C.validate_form_schema_v1(R._thaw(row['inputSchema']), **BIND)
    assert rows['tripo-rig-check']['costClass'] == 'free_compute'
    assert rows['text-to-motion-edit']['fixedCost'] == 5
    assert rows['environment-map-to-world']['fixedCost'] == 80
    assert rows['text-to-motion']['costClass'] == 'paid_dynamic'
    assert rows['studiotwin_cancel_job']['tier'] == 'hosted-mutation'
    assert rows['studiotwin_conceptlab_delete']['tier'] == 'hosted-mutation'


@pytest.mark.parametrize('tool',TOOLS,ids=lambda t:t['name'])
def test_every_hash_drift_is_disabled_and_cannot_bind_or_register(tool):
    changed = copy.deepcopy(tool)
    changed['inputSchema']['properties']['newOption'] = {'type':'boolean'}
    catalog = C.Classification([changed])
    row = catalog.discover(**BIND).to_json()['tools'][0]
    assert row['executable'] is False and row['disabledReason'] == 'schema-changed'
    refuse(lambda: catalog.candidate_inputs(tool['name'],digest(tool),{},**BIND))
    refuse(lambda: C.GatewayRegistry(catalog).add(tool['name'],good_handler))


@pytest.mark.parametrize('part',['name','inputSchema','outputSchema'])
def test_hash_matches_s02_and_ignores_noncanonical_metadata(part):
    original=BY_NAME[NAME]
    assert C.schema_hash_v1(original)==digest(original)
    altered=copy.deepcopy(original)
    altered['description']='safe revised label'
    altered['annotations']={'readOnlyHint':True}
    assert C.schema_hash_v1(altered)==digest(original)
    altered[part] = 'different' if part=='name' else {'type':'object'}
    assert C.schema_hash_v1(altered)!=digest(original)


def test_new_tool_and_d22_stay_disabled_even_with_future_publication(monkeypatch):
    unknown=copy.deepcopy(TOOLS[0]); unknown['name']='future-forty-sixth'
    monkeypatch.setattr(CAP,'published_tools',lambda decision,hosted_tools: ['studiotwin_setup_status',*hosted_tools])
    catalog=C.Classification([*TOOLS,unknown])
    rows={r['name']:r for r in catalog.discover(**BIND).to_json()['tools']}
    assert len(rows)==46
    assert rows[unknown['name']]['disabledReason']=='unclassified'
    assert not rows[unknown['name']]['executable']
    assert rows[NAME]['executable'] and rows[NAME]['disabledReason'] is None
    for name in D22:
        assert not rows[name]['executable'] and rows[name]['disabledReason']=='concept-paid-d22'
        refuse(lambda: C.GatewayRegistry(catalog).add(name,good_handler))
    refuse(lambda: C.GatewayRegistry(catalog).add(unknown['name'],good_handler))


def test_default_and_forged_publication_remain_setup_only():
    catalog=release()
    for decision in (None,{'publishedTiers':['setup','paid','hosted-read','hosted-mutation'],'principalIdentity':'proven'}):
        result=catalog.discover(publication=decision,**BIND).to_json()
        assert result['publishedTiers']==['setup']
        assert result['agentCallable']==['studiotwin_setup_status']
        assert all(not r['executable'] for r in result['tools'])


def test_release_is_immutable_and_no_runtime_updater():
    refuse(lambda:C.Classification(TOOLS,manifest={}))
    for method in ('update','sign','reload'):
        refuse(lambda:getattr(release(),method)({}))
    with pytest.raises(TypeError):
        C.RELEASE['tools'][NAME]['schemaHash']='f'*64
    catalog=release()
    original=copy.deepcopy(TOOLS)
    catalog=C.Classification(original)
    original[0]['inputSchema']['properties']['evil']={}
    assert catalog.is_classified(TOOLS[0]['name'])


def test_duplicate_malformed_and_missing_schema_discovery():
    refuse(lambda:C.Classification([TOOLS[0],TOOLS[0]]))
    malformed=copy.deepcopy(TOOLS[0]); malformed['inputSchema']=None
    row=C.Classification([malformed]).discover(**BIND).to_json()['tools'][0]
    assert not row['executable'] and row['disabledReason']=='schema-unavailable'
    refuse(lambda:C.Classification([{'name':'<script>'}]))


def test_real_s06_identity_binding_and_closed_candidates(monkeypatch):
    assert C.ValidatedCandidateInputs is R.ValidatedCandidateInputs
    catalog=release(); expected=digest(BY_NAME[NAME])
    entered=[]; original=R.candidate_schema_v1
    def spy(*args):
        entered.append(args)
        return original(*args)
    monkeypatch.setattr(R,'candidate_schema_v1',spy)
    value=catalog.candidate_inputs(NAME,expected,{'prompt':'study','seed':2},**BIND)
    assert isinstance(value,C.ValidatedCandidateInputs)
    assert value.schema_hash==expected and value.tool==NAME
    assert entered and entered[0][:2]==(NAME,expected)
    assert value.values['prompt']=='study'
    with pytest.raises(TypeError): value.values['prompt']='changed'
    for bad in ({'prompt':'study'},{'prompt':4,'seed':2},{'prompt':'study','seed':2,'extra':1},
                {'prompt':'STCANARY_secret','seed':2}):
        refuse(lambda:catalog.candidate_inputs(NAME,expected,bad,**BIND))
    entered.clear()
    refuse(lambda:catalog.candidate_inputs(NAME,'f'*64,{'prompt':'study','seed':2},**BIND))
    assert entered==[]
    refuse(lambda:R.validate_candidate_inputs_v1(NAME,expected,{'prompt':'study','seed':2},**BIND))


@pytest.mark.parametrize('tool',[NAME,'text-to-motion-edit','tripo-retopology'])
def test_schema_projection_is_hash_bound_detached_and_mediated(tool,monkeypatch):
    catalog=release(); hash_=digest(BY_NAME[tool]); calls=[]
    original=R.validate_mediated_v1
    def spy(*a,**kw): calls.append(a[0]); return original(*a,**kw)
    monkeypatch.setattr(R,'validate_mediated_v1',spy)
    direct=catalog.input_schema(tool,hash_,**BIND).to_json()
    assert direct['tool']==tool and direct['schemaHash']==hash_
    assert direct['inputSchema']['kind']=='object'
    assert calls[-1]==FORM_REF
    wrapped=catalog.input_schema(tool,hash_,request_id='rq_'+'a'*22,**BIND).to_json()
    assert wrapped['result']['payload']==direct and calls[-1]==IPC_REF
    direct['inputSchema']['fields'].clear()
    assert catalog.input_schema(tool,hash_,**BIND).to_json()['inputSchema']['fields']
    refuse(lambda:catalog.input_schema(tool,'f'*64,**BIND))


@pytest.mark.parametrize('wrapped',[False,True])
@pytest.mark.parametrize('defect',['duplicate','default_type','default_bounds','choices_type','choice_bounds','bounds','depth','nodes','bytes','html','secret'])
def test_cf8_complete_envelopes_refuse_semantic_defects(wrapped,defect):
    schema=form()['inputSchema']; child=schema['fields'][0]['schema']
    if defect=='duplicate': schema['fields']*=2
    elif defect=='default_type': child['defaultValue']=True
    elif defect=='default_bounds': child['defaultValue']='x'*41
    elif defect=='choices_type': child['choices']=[42]
    elif defect=='choice_bounds': child['choices']=['x'*41]
    elif defect=='bounds': child.update(minLength=20,maxLength=10)
    elif defect=='depth':
        for _ in range(9): schema={'kind':'array','items':schema}
    elif defect=='nodes':
        schema={'kind':'object','fields':[{'name':f'f{i}','required':False,'schema':{'kind':'object','fields':[
            {'name':f'x{j}','required':False,'schema':{'kind':'string'}} for j in range(64)]}} for i in range(4)]}
    elif defect=='bytes':
        schema={'kind':'object','fields':[{'name':f'f{i}','required':False,'schema':{'kind':'string','description':'x'*3900}} for i in range(20)]}
    elif defect=='html': child['description']='<img src=x onerror=run()>'
    else: child['defaultValue']='ordinary-hidden-value'
    response=form(schema)
    kwargs={**BIND,'sensitive_values':('ordinary-hidden-value',)}
    refuse(lambda:C.validate_input_schema_response_v1(envelope(response) if wrapped else response,wrapped=wrapped,**kwargs))


async def good_handler(*, context: C.GatewayCallContext, inputs: C.ValidatedCandidateInputs) -> R.MediatedValue:
    return await context.execute(inputs)


def test_registry_exact_contract_registration_and_duplicates():
    registry=C.GatewayRegistry(release())
    assert registry.add(NAME,good_handler) is None
    refuse(lambda:registry.add(NAME,good_handler))
    def sync(*,context,inputs): pass
    async def positional(context,inputs): pass
    async def extra(*,context,inputs,extra=None): pass
    async def defaults(*,context=None,inputs=None): pass
    async def arbitrary(**kw): pass
    for bad in (sync,positional,extra,defaults,arbitrary):
        refuse(lambda:C.GatewayRegistry(release()).add(NAME,bad))


def test_policy_is_real_s07_type_and_bound_to_release():
    from s08_gateway.mediation import OutputPolicy
    policy=release().output_policy(NAME)
    assert type(policy) is OutputPolicy
    assert policy.tool==NAME and policy.schema_hash==digest(BY_NAME[NAME])
    refuse(lambda:release().output_policy('future-forty-sixth'))


def test_context_cannot_be_built_from_model_boolean():
    refuse(lambda:C.GatewayCallContext(scope_id='a'*64,generation=1,trusted_context={'trusted':True},execute=lambda x:x))


def trusted(name=NAME):
    import hmac
    from s08_gateway.host_context import HostContextGate, META_KEY
    key=b'fixture-key-only-32-bytes-long!!!x'
    gate=HostContextGate(key=key,host_instance_nonce='a'*43,profile_id='profile-a',connection_id='local')
    body=dict(hostInstanceNonce='a'*43,profileId='profile-a',connectionId='local',sessionId='chat-a',
              runKind='interactive',cronRunId=None,toolName=name,turnId='turn-1',toolCallId='call-1',callNonce=1)
    data=json.dumps(body,sort_keys=True,separators=(',',':'),allow_nan=False).encode()
    body['mac']=hmac.new(key,b'trusted-tool-context-v1\0'+data,hashlib.sha256).hexdigest()
    context=gate.receive(arguments={},metadata={META_KEY:body})
    assert gate._owned(context)
    return gate,context


def safe_result(tool=NAME,**binding):
    args={**BIND,**binding}
    return R.validate_mediated_v1('gateway#/$defs/GatewayResultV1',dict(protocol='studiotwin.gateway.v1',
        tool=tool,status='ok',jobId=None,assetIds=[],media=[],summary='done',operation=None),**args)


def test_registry_bound_execute_and_real_handler_output(monkeypatch):
    catalog=release(); registry=C.GatewayRegistry(catalog); registry.add(NAME,good_handler)
    gate,verified=trusted(); calls=[]
    async def execute(inputs): calls.append(inputs); return safe_result()
    context=registry.context(NAME,gate=gate,trusted_context=verified,execute=execute,**BIND)
    value=catalog.candidate_inputs(NAME,digest(BY_NAME[NAME]),{'prompt':'study','seed':1},**BIND)
    refuse(lambda:asyncio.run(context.execute(value)))
    assert calls==[]  # unresolved D24/D31, even genuinely receiver-owned context
    monkeypatch.setattr(CAP,'published_tools',lambda decision,hosted_tools:['studiotwin_setup_status',*hosted_tools])
    output=asyncio.run(registry.invoke(NAME,context=context,inputs=value))
    assert output.to_json()['summary']=='done' and calls==[value]
    with pytest.raises((AttributeError,TypeError)):context.generation=2
    for wrong in (value.to_json(),catalog.candidate_inputs(NAME,digest(BY_NAME[NAME]),
            {'prompt':'study','seed':1},**{**BIND,'generation':2}),
            catalog.candidate_inputs(NAME,digest(BY_NAME[NAME]),{'prompt':'study','seed':1},**{**BIND,'scope_id':'b'*64})):
        refuse(lambda:asyncio.run(context.execute(wrong)))
    assert calls==[value]
    foreign=C.GatewayRegistry(catalog); foreign.add(NAME,good_handler)
    refuse(lambda:asyncio.run(foreign.invoke(NAME,context=context,inputs=value)))
    refuse(lambda:registry.context(NAME,gate=gate,trusted_context=dict(verified),execute=execute,**BIND))


@pytest.mark.parametrize('bad_kind',['raw','wrong_tool','wrong_scope','wrong_contract','exception'])
def test_registry_refuses_bad_handler_output_and_sanitizes(bad_kind,monkeypatch):
    catalog=release();registry=C.GatewayRegistry(catalog)
    gate,verified=trusted()
    monkeypatch.setattr(CAP,'published_tools',lambda decision,hosted_tools:['studiotwin_setup_status',*hosted_tools])
    async def execute(inputs):
        if bad_kind=='raw':return safe_result().to_json()
        if bad_kind=='wrong_tool':return safe_result('text-to-motion')
        if bad_kind=='wrong_scope':return safe_result(scope_id='b'*64)
        if bad_kind=='wrong_contract':return R.safe_error_v1()
        raise RuntimeError('STCANARY_provider_diagnostic')
    context=registry.context(NAME,gate=gate,trusted_context=verified,execute=execute,**BIND)
    registry.add(NAME,good_handler)
    value=catalog.candidate_inputs(NAME,digest(BY_NAME[NAME]),{'prompt':'study','seed':1},**BIND)
    refuse(lambda:asyncio.run(registry.invoke(NAME,context=context,inputs=value)))


def test_registration_refuses_wrong_or_missing_annotations():
    async def wrong(*, context: dict, inputs: dict) -> dict: return {}
    async def missing(*, context, inputs): return None
    for handler in (wrong,missing):
        refuse(lambda:C.GatewayRegistry(release()).add(NAME,handler))


@pytest.mark.parametrize('tool',TOOLS,ids=lambda t:t['name'])
def test_all_45_reviewed_form_schemas_are_retrievable(tool):
    value=release().input_schema(tool['name'],digest(tool),request_id='rq_'+'a'*22,**BIND).to_json()
    assert value['result']['payload']['schemaHash']==digest(tool)


@pytest.mark.parametrize('value',['x'*36,'https://foreign.invalid/a','data:image/png;base64,AAAA','STCANARY_secret'])
def test_reviewed_asset_inputs_not_arbitrary_text(value):
    catalog=release();tool='image-to-3d-mesh'
    refuse(lambda:catalog.candidate_inputs(tool,digest(BY_NAME[tool]),{'referenceImage':value,'seed':1},**BIND))


def test_reviewed_safe_resource_projection_and_aliases():
    catalog=release();tool='text-to-material'
    value=catalog.candidate_inputs(tool,digest(BY_NAME[tool]),
        {'resolution':1024,'textPrompt':'brass','maskAssetId':'12345678-1234-4234-8234-123456789abc'},**BIND)
    assert value.values['maskAssetId']=='12345678-1234-4234-8234-123456789abc'
    row=C.RELEASE['tools'][tool]
    assert any(r.get('upstreamField')=='maskUrl' for r in row['inputReferences'])


def test_unsupported_live_construct_never_becomes_a_textbox():
    changed=copy.deepcopy(BY_NAME[NAME]);changed['inputSchema']['properties']['prompt']={'$ref':'https://foreign.invalid/schema'}
    catalog=C.Classification([changed])
    assert not catalog.is_classified(NAME)
    refuse(lambda:catalog.input_schema(NAME,digest(changed),**BIND))
