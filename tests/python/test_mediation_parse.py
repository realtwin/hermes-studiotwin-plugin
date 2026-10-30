"""S06 real boundary tests; synthetic fixtures only, no hosted calls."""
import base64
import copy
import importlib.util
import json
from pathlib import Path
import sys
from urllib.parse import quote

import pytest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from gateway import mediation_parse as P, redaction as R

spec = importlib.util.spec_from_file_location('s06_contract_oracle', ROOT / 'tests/contracts/support.py')
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)
CANARIES = json.loads((ROOT / 'tests/fixtures/secret_channels/canaries.v1.json').read_text())['canaries']
NEEDLES = [needle for row in CANARIES for needle in row['needles']]
SCOPE = 'a' * 64
BINDING = dict(scope_id=SCOPE, generation=1, sensitive_values=())
UUID = '12345678-1234-1234-1234-123456789abc'
G = 'gateway#/$defs/GatewayResultV1'
H = 'host_gateway#/$defs/IpcResponseV1'
E = 'dashboard#/components/schemas/ErrorV1'
Q = 'dashboard#/components/schemas/QuoteRequestV1'


def result():
    return dict(protocol='studiotwin.gateway.v1', tool='studiotwin_get_job_status', status='ok',
                jobId=UUID, assetIds=[UUID], media=[], summary='done', operation=None)


def envelopes():
    job = dict(jobId=UUID, functionName='text-to-environment-map', status='done', submittedAtMs=None,
               terminalAtMs=None, outputAssetIds=[], operationId=None, summary='done')
    return [(G, result(), ('summary',)),
            (H, dict(protocol='studiotwin.host-gateway.v1', requestId='rq_'+'a'*22, ok=True,
                     result=dict(method='jobs.get', payload=dict(contract='studiotwin.dashboard.v1', job=job))),
             ('result', 'payload', 'job', 'summary')),
            (E, dict(contract='studiotwin.dashboard.v1', code='UNAVAILABLE', message='try later'), ('message',)),
            (Q, dict(contract='studiotwin.dashboard.v1', tool='text-to-environment-map', schemaHash='b'*64,
                     inputs=dict(prompt='study', seed=1)), ('inputs', 'prompt'))]


def inject(obj, path, value):
    obj = copy.deepcopy(obj)
    cursor = obj
    for key in path[:-1]:
        cursor = cursor[key]
    cursor[path[-1]] = value
    return obj


def refused(fn):
    with pytest.raises(R.BoundaryRefused) as caught:
        fn()
    err = caught.value
    assert err.code == 'UNSAFE_PAYLOAD'
    assert str(err) == 'UNSAFE_PAYLOAD'
    assert err.args == ('UNSAFE_PAYLOAD',)
    assert err.__cause__ is None
    assert err.__context__ is None
    return err


@pytest.mark.parametrize('ref,good,path', envelopes())
def test_complete_valid_envelopes_and_detached_immutable_wrapper(ref, good, path):
    assert S.is_valid(ref, good)
    wrapped = R.validate_mediated_v1(ref, good, **BINDING)
    assert wrapped.to_json() == good
    assert wrapped.scope_id == SCOPE and wrapped.generation == 1 and wrapped.contract_ref == ref
    original = wrapped.to_json()
    with pytest.raises((TypeError, AttributeError)):
        wrapped.value['new'] = 1
    with pytest.raises((TypeError, AttributeError)):
        wrapped.scope_id = 'b'*64
    good.clear()
    exported = wrapped.to_json()
    exported.clear()
    assert wrapped.to_json() == original
    assert 'summary' not in repr(wrapped)


@pytest.mark.parametrize('needle', NEEDLES, ids=[f'needle-{i}' for i in range(len(NEEDLES))])
def test_all_s02_canaries_at_complete_real_sinks(needle):
    for ref, good, path in envelopes():
        for value in (needle, 'prefix '+needle+' suffix'):
            bad = inject(good, path, value)
            refused(lambda: R.validate_mediated_v1(ref, bad, **BINDING))
            if ref == Q:
                refused(lambda: R.validate_candidate_inputs_v1(good['tool'], good['schemaHash'], bad['inputs'], **BINDING))


@pytest.mark.parametrize('value', [
    'https://objects.invalid/x?X-Amz-Signature=synthetic',
    'https://objects.invalid/x?Signature=synthetic',
    'https://objects.invalid/x?token=synthetic', 's3://private/object',
    'x-api-key: synthetic', 'Bearer synthetic-credential',
    {'fields': {'Policy': 'ordinary', 'X-Amz-Security-Token': 'ordinary'}},
    {'nested': {'authorization': 'ordinary'}},
])
def test_nested_presigned_and_credential_payloads_refused(value):
    for ref, good, path in envelopes():
        refused(lambda: R.validate_mediated_v1(ref, inject(good, path, value), **BINDING))
    refused(lambda: R.validate_candidate_inputs_v1('text-to-environment-map', 'b'*64,
                                                  {'nested': {'image': value}}, **BINDING))


@pytest.mark.parametrize('encode', [lambda s:s, quote, lambda s:base64.b64encode(s.encode()).decode(),
                                   lambda s:base64.urlsafe_b64encode(s.encode()).decode().rstrip('='),
                                   lambda s:s.encode().hex()])
def test_ordinary_registry_secret_and_recognized_encodings(encode, caplog, capsys):
    secret = 'ordinary sensitive material!+'
    data = result()
    data['summary'] = 'prefix '+encode(secret)+' suffix'
    assert S.is_valid(G, data)
    refused(lambda: R.validate_mediated_v1(G, data, **{**BINDING, 'sensitive_values': {secret}}))
    assert secret not in caplog.text and capsys.readouterr() == ('', '')


CHANNELS = [lambda s:{'content':[{'type':'text','text':s}]},
            lambda s:{'content':[{'type':'text','text':'prose '+json.dumps({'privateKey': s, 'jobId':UUID})+' tail'}]},
            lambda s:{'content':[{'type':'text','text':'```json\n'+json.dumps({'apiKey':s, 'assetId':UUID})+'\n```'}]},
            lambda s:{'structuredContent':{'nested':{'value':s}}},
            lambda s:{'content':[{'type':'resource_link','uri':s,'name':'safe'}]},
            lambda s:{'content':[{'type':'resource','resource':{'uri':s,'text':s}}]},
            lambda s:{'_meta':{'debug':s}},
            lambda s:{'content':[{'type':'text','text':'safe','_meta':{'debug':s}}]},
            lambda s:{'isError':True,'content':[{'type':'text','text':s}]},
            lambda s:{'error':{'message':s,'data':{'debug':s}}},
            lambda s:{'method':'notifications/progress','params':{'message':s,'progress':1,'total':2}},
            lambda s:{'method':'notifications/message','params':{'data':s}},
            lambda s:{'diagnostics':{'httpBody':s,'redirectTrace':s}},
            lambda s:{'extension':{'annotations':{'note':s}}}]


@pytest.mark.parametrize('channel', CHANNELS, ids=[f'channel-{i}' for i in range(len(CHANNELS))])
def test_every_channel_redacted_with_safe_ids_and_metadata_preserved(channel):
    for needle in NEEDLES:
        raw = channel(needle)
        raw.update(assetId=UUID, jobId=UUID, conceptId=UUID, uploadSessionId=UUID,
                   operationId='op_'+'c'*43, label='safe label', count=3)
        safe = R.redact_upstream_v1(raw, sensitive_values=())
        text = json.dumps(safe)
        assert all(n not in text for n in NEEDLES)
        assert safe['assetId'] == safe['jobId'] == safe['conceptId'] == safe['uploadSessionId'] == UUID
        assert safe['operationId'] == 'op_'+'c'*43 and safe['count'] == 3 and safe['label'] == 'safe label'
        assert raw['assetId'] == UUID  # source is never mutated


def test_embedded_json_actually_parsed_not_just_prefix_scrubbed():
    text = 'before {"apiKey":"innocent-looking", "jobId":"'+UUID+'"} after'
    safe = R.redact_upstream_v1({'content':[{'type':'text','text':text}]}, sensitive_values=())
    assert 'innocent-looking' not in json.dumps(safe)
    assert UUID in json.dumps(safe)
    assert 'before' in safe['content'][0]['text'] and 'after' in safe['content'][0]['text']


def test_cf6_known_canary_never_masks_unknown_or_additional_secret():
    known = NEEDLES[0]
    unknown = 'STCANARY_UNREGISTERED_EXTRA_opaque'
    additional = 'ordinary-looking-private-value'
    raw = {'known':known, '_meta':{'extra':unknown}, 'content':[{'type':'text','text':additional}]}
    safe = R.redact_upstream_v1(raw, sensitive_values={known, additional})
    serialized = json.dumps(safe)
    assert known not in serialized and unknown not in serialized and additional not in serialized
    # Unknown secret-shaped data is detected even when a known canary already matched.
    raw = {'known':known, 'other':{'X-Amz-Signature':'not-a-canary'}}
    assert 'not-a-canary' not in json.dumps(R.redact_upstream_v1(raw, sensitive_values={known}))


@pytest.mark.parametrize('raw', ['{"x":1,"x":2}', '{broken', '[NaN]', '[Infinity]', '"'+'x'*1048576+'"'])
def test_bounded_json_parser_refuses_malformed_duplicate_nonfinite_oversized(raw):
    refused(lambda:P.parse_json_v1(raw))


@pytest.mark.parametrize('bad', [float('nan'), float('inf'), {'x':object()}, {1:'not string key'}, {'x':'\ud800'}])
def test_non_json_and_nonfinite_fail_sanitized(bad):
    refused(lambda:R.redact_upstream_v1(bad, sensitive_values=()))
    refused(lambda:R.validate_mediated_v1(G, bad, **BINDING))


def test_limits_apply_before_schema_and_to_embedded_json():
    deep = 'value'
    for _ in range(49):
        deep = [deep]
    for bad in (deep, [None]*100001, {'value':'x'*1048576}, {'text':'prefix '+json.dumps(deep)}):
        refused(lambda:R.redact_upstream_v1(bad, sensitive_values=()))


@pytest.mark.parametrize('bad', [dict(scope_id='foreign'), dict(generation=-1), dict(generation=True), dict(sensitive_values='not a collection of secrets')])
def test_bad_binding_or_registry_refused(bad):
    refused(lambda:R.validate_mediated_v1(G, result(), **{**BINDING, **bad}))


def test_unknown_contract_variant_and_foreign_media_path_refused():
    refused(lambda:R.validate_mediated_v1('https://remote.invalid/schema', result(), **BINDING))
    refused(lambda:R.validate_mediated_v1(G, {**result(), 'unclassified':42}, **BINDING))
    value = result()
    value['media'] = [dict(localPath='/data/hermes-studiotwin/scopes/'+'b'*64+'/media/a.png',
                           handle='sth_'+'c'*43, kind='image', mime='image/png', assetId=UUID)]
    assert S.is_valid(G, value)
    refused(lambda:R.validate_mediated_v1(G, value, **BINDING))


def test_wrappers_cannot_be_directly_constructed():
    for cls in (R.MediatedValue, R.ValidatedCandidateInputs):
        refused(lambda:cls())


def test_candidate_policy_is_backend_bound_exact_schema_not_arbitrary_input_authority():
    inputs = {'prompt':'study', 'seed':1}
    # No reviewed schema binding: safe syntax alone cannot authorize unknown fields.
    refused(lambda:R.validate_candidate_inputs_v1('text-to-environment-map', 'b'*64, inputs, **BINDING))
    schema = {'type':'object','additionalProperties':False,'required':['prompt','seed'],
              'properties':{'prompt':{'type':'string','maxLength':20}, 'seed':{'type':'integer','minimum':0}}}
    with R.candidate_schema_v1('text-to-environment-map', 'b'*64, schema):
        value = R.validate_candidate_inputs_v1('text-to-environment-map', 'b'*64, inputs, **BINDING)
        assert value.to_json() == inputs and value.values['seed'] == 1
        assert value.tool == 'text-to-environment-map' and value.schema_hash == 'b'*64
        assert len(value.canonical_input_hash) == 64
        for bad in ({'prompt':'study'}, {**inputs,'extra':1}, {**inputs,'seed':-1}, {**inputs,'seed':True}):
            refused(lambda:R.validate_candidate_inputs_v1('text-to-environment-map', 'b'*64, bad, **BINDING))
        refused(lambda:R.validate_candidate_inputs_v1('text-to-environment-map', 'c'*64, inputs, **BINDING))
        refused(lambda:R.validate_candidate_inputs_v1('other-tool', 'b'*64, inputs, **BINDING))
        with pytest.raises(TypeError):
            value.values['seed'] = 2
    refused(lambda:R.validate_candidate_inputs_v1('text-to-environment-map', 'b'*64, inputs, **BINDING))


def test_candidate_signed_url_guard_with_bound_permissive_field():
    schema = {'type':'object', 'additionalProperties':False, 'properties':{'image':{'type':'string'}}}
    with R.candidate_schema_v1('image-tool','b'*64,schema):
        refused(lambda:R.validate_candidate_inputs_v1('image-tool','b'*64,
                {'image':'https://objects.invalid/x?Signature=synthetic'}, **BINDING))


def test_safe_fallback_is_static_and_valid():
    assert R.safe_error_v1().to_json() == {'contract':'studiotwin.dashboard.v1','code':'UNAVAILABLE',
                                        'message':'Unsafe upstream payload refused.'}
    assert S.is_valid(E, R.safe_error_v1().to_json())
