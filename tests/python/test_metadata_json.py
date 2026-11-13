"""Boundary negative controls and streaming-reader compatibility."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('metadata_json_test', ROOT / 'dashboard/metadata_json.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


def read(value, size=7, sse=False):
    data = json.dumps(value, ensure_ascii=True).encode()
    if sse:
        data = b': keepalive\r\nevent: message\r\n\r\ndata: ' + data + b'\r\n\r\n'
    return m.read_metadata((data[i:i+size] for i in range(0,len(data),size)),
                           'text/event-stream' if sse else 'application/json', 3)


@pytest.mark.parametrize('sse', [False, True])
def test_tiny_chunks_preserve_unicode_urls_and_non_json_metadata_text(sse):
    value = {'id':3, 'result': {'structuredContent': {'inputs': {'imageUrl': 'https://example.org/?signature='+'a'*18000,
        'ref': 's3://bucket/key', 'prompt': 'é 😃 \\ \"\n'}, 'text': '[ordinary prose]'}}}
    assert read(value, sse=sse) == value


def test_input_budget_does_not_erase_later_short_prompt():
    row = {'inputs': {'image': 'data:image/png;base64,'+'A'*100000, 'prompt': 'keep'}, 'status':'failed'}
    result = read({'id':3,'result':{'structuredContent':row}})['result']['structuredContent']
    assert result['inputs']['prompt'] == 'keep'
    assert result['inputs_truncated'] is True
    assert len(json.dumps(result)) < 1000


@pytest.mark.parametrize('data', [b'{"x":1,}', b'[1,]', b'{"x":"\\q"}', b'{"x":01}', b'{"x":true}garbage'])
def test_invalid_json_fails_closed(data):
    with pytest.raises(ValueError):
        m.read_metadata([data], 'application/json', 1)


def test_sse_multiline_data_and_empty_events():
    data = b': heartbeat\r\n\r\nevent: message\r\ndata: {"id":3,\r\ndata: "result":{"structuredContent":{"ok":true}}}\r\n\r\n'
    assert m.read_metadata((bytes([c]) for c in data), 'text/event-stream', 3)['result']['structuredContent'] == {'ok':True}


def test_ancillary_prose_does_not_break_structured_result():
    value = {'id':3,'result':{'structuredContent':[{'uuid':'ok'}],
        'content':[{'type':'text','text':'[ordinary prose]'}, {'type':'text','text':'{summary}'}]}}
    assert read(value) == value


def test_dropped_values_refund_budget_for_later_prompt():
    row = {'inputs': {**{f'image{i}':'data:image/png;base64,'+'A'*100000 for i in range(4)}, 'prompt':'keep me'}}
    result = read({'id':3,'result':{'structuredContent':row}})['result']['structuredContent']
    assert result['inputs']['prompt'] == 'keep me'
    assert result['inputs_truncated'] is True


def test_wire_budget_remains_enforced():
    with pytest.raises(ValueError):
        m.read_metadata([b'{"inputs":{"image":"'+b'A'*1000+b'"}}'], 'application/json', 1, wire_limit=100)
