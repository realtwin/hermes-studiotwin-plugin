"""S07 offline runtime tests; no hosted connection or credentials."""
import base64
import copy
import json
import os
from pathlib import Path
import re
import sys
import types
from urllib.parse import quote

import pytest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
pkg = types.ModuleType('s07_gateway')
pkg.__path__ = [str(ROOT / 'gateway')]
sys.modules[pkg.__name__] = pkg
from s07_gateway import handles as H, media_cache as C, mediation as M, redaction as R
from s07_gateway.mediation_parse import BoundaryRefused

A, B = 'a'*64, 'b'*64
UUID = '12345678-1234-1234-1234-123456789abc'
PNG = (ROOT/'tests/fixtures/media/image/concept-64.png').read_bytes()


def mint(store, **changes):
    args = dict(scope_id=A, generation=1, purpose='resource', kind='image', role='image',
                mime='image/png', size=123, target={'location':'https://offline.invalid/private'},
                ttl=60, max_reads=2, operations=('read',))
    args.update(changes)
    return store.mint(**args)


def resolve(store, token, **changes):
    args = dict(scope_id=A, generation=1, purpose='resource', operation='read')
    args.update(changes)
    return store.resolve(token, **args)


def test_handles_random_bound_purpose_operation_and_read_limit():
    store = H.HandleStore()
    token = mint(store)
    assert re.fullmatch(r'sth_[A-Za-z0-9_-]{43}', token)
    assert token != mint(store)
    for args in [dict(scope_id=B), dict(generation=2), dict(purpose='upload'), dict(operation='complete')]:
        with pytest.raises(H.HandleNotFound, match='not found'):
            resolve(store, token, **args)
    assert resolve(store, token).size == 123
    assert resolve(store, token).mime == 'image/png'
    with pytest.raises(H.HandleNotFound):
        resolve(store, token)
    for bad in [token[:-1]+'!', 'sth_'+'x'*43, 'https://offline.invalid/private']:
        with pytest.raises(H.HandleNotFound):
            resolve(store, bad)
    assert 'offline' not in repr(store)


def test_expiry_boundary_rotation_and_explicit_purge():
    now = [10.0]
    store = H.HandleStore(clock=lambda:now[0])
    token = mint(store, ttl=5)
    now[0] = 15
    with pytest.raises(H.HandleNotFound):
        resolve(store, token)
    token = mint(store)
    store.purge_scope(A)
    with pytest.raises(H.HandleNotFound):
        resolve(store, token)
    token = mint(store)
    store.rotate(A, 2)
    with pytest.raises(H.HandleNotFound):
        resolve(store, token)
    with pytest.raises(H.HandleNotFound):
        mint(store, generation=1)


@pytest.mark.parametrize('changes', [dict(scope_id='bad'),dict(generation=True),dict(ttl=0),
    dict(ttl=float('nan')),dict(size=-1),dict(max_reads=0),dict(purpose='unknown'),dict(mime='bad')])
def test_invalid_handle_metadata(changes):
    with pytest.raises((BoundaryRefused,H.HandleNotFound)):
        mint(H.HandleStore(), **changes)


@pytest.fixture
def cache(tmp_path):
    return C.MediaCache(tmp_path/'hermes-studiotwin', H.HandleStore())


def put(cache, **changes):
    args = dict(scope_id=A,generation=1,data=PNG,mime='image/png',kind='image',extension='.png')
    args.update(changes)
    return cache.put(**args)


def test_local_media_open_and_purge(cache):
    item = put(cache)
    assert '/scopes/'+A+'/media/' in item.path
    assert Path(item.path).name != 'concept-64.png'
    assert cache.media_line(item, scope_id=A,generation=1) == 'MEDIA:'+item.path
    with cache.open(item.path,scope_id=A,generation=1,mime='image/png',kind='image') as f:
        assert f.read() == PNG
    for scope, gen in [(B,1),(A,2)]:
        with pytest.raises(C.MediaRefused):
            cache.open(item.path,scope_id=scope,generation=gen,mime='image/png',kind='image')
    cache.purge_scope(A)
    assert not Path(item.path).exists()
    with pytest.raises(H.HandleNotFound):
        resolve(cache.handles,item.handle)


@pytest.mark.parametrize('attack',['hardlink','symlink','public','directory','traversal','foreign','mime','missing'])
def test_local_file_guards(cache, tmp_path, attack):
    item = put(cache)
    path = Path(item.path)
    candidate = str(path)
    mime = 'image/png'
    if attack == 'hardlink': os.link(path,path.with_name('alias.png'))
    if attack == 'symlink':
        saved=path.read_bytes(); path.unlink(); other=tmp_path/'foreign.png'; other.write_bytes(saved); path.symlink_to(other)
    if attack == 'public': path.chmod(0o644)
    if attack == 'directory': path.unlink(); path.mkdir()
    if attack == 'traversal': candidate=str(path.parent/'..'/'media'/path.name)
    if attack == 'foreign': candidate=str(tmp_path/'foreign.png'); Path(candidate).write_bytes(PNG)
    if attack == 'mime': mime='audio/wav'
    if attack == 'missing': path.unlink()
    with pytest.raises(C.MediaRefused):
        cache.open(candidate,scope_id=A,generation=1,mime=mime,kind='image')


def test_nofollow_open_is_actual_guard(cache, monkeypatch):
    item=put(cache)
    real=os.open
    seen=[]
    def spy(path, flags, *args, **kw):
        seen.append(flags)
        return real(path,flags,*args,**kw)
    monkeypatch.setattr(C.os,'open',spy)
    with cache.open(item.path,scope_id=A,generation=1,mime='image/png',kind='image') as f:
        assert f.read()==PNG
    assert seen and all(flags & os.O_NOFOLLOW for flags in seen)


def test_open_fstat_owner_and_inode_swap(cache, monkeypatch):
    item=put(cache)
    real=C.os.fstat
    def foreign(fd):
        st=real(fd)
        values=list(st); values[4]=st.st_uid+1
        return os.stat_result(values)
    monkeypatch.setattr(C.os,'fstat',foreign)
    with pytest.raises(C.MediaRefused):
        cache.open(item.path,scope_id=A,generation=1,mime='image/png',kind='image')


def test_mime_sniff_caps_and_quota_ttl_pins(tmp_path):
    assert C.CATEGORY_CAPS['model']==128*1024*1024
    assert C.CATEGORY_CAPS['audio']==60*1024*1024
    assert C.DEFAULT_QUOTA==2*1024*1024*1024
    assert C.DEFAULT_TTL==30*24*60*60
    now=[100.0]
    cache=C.MediaCache(tmp_path/'hermes-studiotwin',H.HandleStore(),quota=len(PNG)*2,ttl=10,clock=lambda:now[0])
    first=put(cache,pinned=True); now[0]+=1
    second=put(cache); now[0]+=1
    third=put(cache)
    assert Path(first.path).exists() and not Path(second.path).exists() and Path(third.path).exists()
    now[0]+=11; cache.evict()
    assert Path(first.path).exists() and not Path(third.path).exists()
    with pytest.raises(H.HandleNotFound): resolve(cache.handles,second.handle)
    with pytest.raises(C.MediaRefused): put(cache,data=b'not a png')
    with pytest.raises(C.MediaRefused): put(cache,extension='.exe')
    monkey_caps=copy.copy(C.CATEGORY_CAPS)
    C.CATEGORY_CAPS['image']=len(PNG)-1
    try:
        with pytest.raises(C.MediaRefused): put(cache)
    finally:
        C.CATEGORY_CAPS.clear(); C.CATEGORY_CAPS.update(monkey_caps)


def test_quota_is_global_across_scopes_and_pins_cannot_be_evicted(tmp_path):
    cache=C.MediaCache(tmp_path/'hermes-studiotwin',H.HandleStore(),quota=len(PNG))
    a=put(cache,pinned=True)
    with pytest.raises(C.MediaRefused): put(cache,scope_id=B)
    assert Path(a.path).exists()


def policy(**changes):
    args=dict(tool='studiotwin_resolve_asset', schema_hash='c'*64,
              resources=(M.ResourceRule(path=('structuredContent','download'),kind='image',role='image',mime='image/png',size=123),),
              group='single', summary_path=('structuredContent','summary'), job_path=('structuredContent','jobId'))
    args.update(changes)
    return M.OutputPolicy(**args)


def upstream():
    return {'structuredContent':{'download':'https://offline.invalid/file?signature=ordinary-private-review',
                                'summary':'done','jobId':UUID},
            'content':[{'type':'text','text':'diagnostics'}]}


def mediate(raw=None, pol=None, **changes):
    med=M.Mediator(H.HandleStore())
    args=dict(scope_id=A,generation=1,policy=pol or policy(),live_schema_hash='c'*64)
    args.update(changes)
    return med, med.mediate(raw or upstream(),**args)


def test_extract_register_then_redact_and_validate(monkeypatch):
    calls=[]
    real_redact=M.redact_upstream_v1
    real_validate=M.validate_mediated_v1
    location=upstream()['structuredContent']['download']
    def redact(raw, *, sensitive_values):
        assert location in sensitive_values
        calls.append('redact')
        return real_redact(raw,sensitive_values=sensitive_values)
    def validate(ref,candidate,**kw):
        assert location in kw['sensitive_values']
        calls.append('validate')
        return real_validate(ref,candidate,**kw)
    monkeypatch.setattr(M,'redact_upstream_v1',redact)
    monkeypatch.setattr(M,'validate_mediated_v1',validate)
    med,result=mediate()
    data=result.to_json()
    assert data['jobId']==UUID and data['summary']=='done'
    resource=data['outputGroups'][0]['resource']
    token=resource['source']['handle']
    assert resource['contentRoute'].endswith(token)
    assert resolve(med.handles,token).target['location']==location
    assert location not in json.dumps(data)
    assert calls.index('redact') < calls.index('validate')


@pytest.mark.parametrize('encode',[lambda s:s,quote,lambda s:base64.b64encode(s.encode()).decode(),lambda s:s.encode().hex()])
def test_extracted_ordinary_value_cannot_survive_in_summary(encode):
    raw=upstream(); raw['structuredContent']['download']='https://offline.invalid/ordinary[123]private+material'
    raw['structuredContent']['summary']=encode(raw['structuredContent']['download'])
    _,result=mediate(raw)
    assert encode(raw['structuredContent']['download']) not in json.dumps(result.to_json())


def test_upload_fields_registered_as_whole_and_individuals(monkeypatch):
    fields={'key':'ordinary-object-key','Policy':'ordinary-private-policy','X-Amz-Signature':'ordinary-private-signature'}
    raw={'structuredContent':{'session':{'url':'https://offline.invalid/post','fields':fields,'uploadSessionId':'private-session'}}}
    pol=policy(resources=(),upload_path=('structuredContent','session'),summary_path=None,job_path=None)
    original=M.validate_mediated_v1
    def spy(ref,candidate,**kw):
        assert set(fields.values()) <= set(kw['sensitive_values'])
        assert 'private-session' in kw['sensitive_values']
        return original(ref,candidate,**kw)
    monkeypatch.setattr(M,'validate_mediated_v1',spy)
    med,result=mediate(raw,pol)
    token=result.to_json()['outputGroups'][0]['resource']['source']['handle']
    record=med.handles.resolve(token,scope_id=A,generation=1,purpose='upload',operation='put')
    assert dict(record.target['fields'])==fields
    assert not any(v in json.dumps(result.to_json()) for v in fields.values())


def test_bare_s3_is_nonlibrary_and_unresolvable_without_resolver():
    raw=upstream(); raw['structuredContent']['download']='s3://private-bucket/private-object'
    _,result=mediate(raw)
    resource=result.to_json()['outputGroups'][0]['resource']
    assert resource['assetId'] is None and resource['libraryState']=='not-in-library'
    assert resource['source'] is None and resource['contentRoute'] is None
    assert 's3://' not in json.dumps(result.to_json())


def test_sequence_material_world_and_relations():
    rules=tuple(M.ResourceRule(path=('frames',i),kind='image',role='image',mime='image/png',size=10) for i in range(2))
    raw={'frames':['https://offline.invalid/1','https://offline.invalid/2']}
    _,result=mediate(raw,policy(resources=rules,group='image_sequence',fps=24,summary_path=None,job_path=None))
    group=result.to_json()['outputGroups'][0]
    assert [f['index'] for f in group['frames']]==[0,1] and group['fps']==24 and group['manifest'] is None
    for kind, key, roles in [('material','maps',('albedo','normal','roughness','metalness','height')),('world','outputs',('skyMap','worldMesh'))]:
        rule=M.ResourceRule(path=('output',),kind='image',role=roles[0],mime='image/png',size=10)
        _,result=mediate({'output':'https://offline.invalid/1'},policy(resources=(rule,),group=kind,summary_path=None,job_path=None))
        slots=result.to_json()['outputGroups'][0][key]
        assert tuple(slots)==roles
        assert slots[roles[0]]['state']=='present'
        assert all(slots[r]=={'state':'absent','resource':None} for r in roles[1:])
    with pytest.raises(BoundaryRefused):
        mediate(raw,policy(resources=(rules[0],rules[0]),group='image_sequence',summary_path=None,job_path=None))
    with pytest.raises(BoundaryRefused):
        mediate(raw,policy(resources=rules,group='image_sequence',fps=0,summary_path=None,job_path=None))
    with pytest.raises(BoundaryRefused):
        mediate(raw,policy(resources=rules,group='image_sequence',summary_path=None,job_path=None),live_schema_hash='d'*64)


def test_complete_ipc_stream_envelope_and_sink_no_raw_values():
    med,result=mediate()
    token=result.to_json()['outputGroups'][0]['resource']['source']['handle']
    response=med.stream_response(token,request_id='rq_'+'a'*22,scope_id=A,generation=1)
    data=response.to_json()
    assert data['result']['method']=='resources.resolveStream'
    assert data['result']['payload']=={'handle':token,'mime':'image/png','bytes':123,'assetId':None}
    sink=[]; sink.append(json.dumps(data))
    assert 'offline.invalid' not in ''.join(sink)
    with pytest.raises(H.HandleNotFound):
        med.stream_response(token,request_id='rq_'+'a'*22,scope_id=B,generation=1)


CANARIES=json.loads((ROOT/'tests/fixtures/secret_channels/canaries.v1.json').read_text())['canaries']
NEEDLES=[s for row in CANARIES for s in row['needles']]
@pytest.mark.parametrize('needle',NEEDLES)
@pytest.mark.parametrize('channel',['content','structuredContent','_meta','error','progress'])
def test_all_channels_no_secrets_and_safe_ids(needle,channel):
    raw=upstream(); raw[channel]={'unknown':needle} if channel!='structuredContent' else {**raw[channel],'unknown':needle}
    _,result=mediate(raw)
    text=json.dumps(result.to_json())
    assert needle not in text and UUID in text
