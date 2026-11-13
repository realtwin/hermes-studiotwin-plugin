"""Direct Streamable HTTP MCP client. No local server, credential cache or paid submits."""
from __future__ import annotations

import json
from urllib.parse import urljoin, urlsplit

import httpx
from fastapi import HTTPException

# The bundled wake adapter also loads this client directly by file path.
if not __package__:
    import hashlib
    import sys
    import types
    from pathlib import Path
    name = '_hermes_studiotwin_' + hashlib.sha256(str(Path(__file__).resolve().parent).encode()).hexdigest()[:12]
    if name not in sys.modules:
        pkg = types.ModuleType(name)
        pkg.__path__ = [str(Path(__file__).resolve().parent)]
        sys.modules[name] = pkg
    __package__ = name

from .metadata_json import read_metadata

KEY_ENV = 'STUDIOTWIN_API_KEY'
MAX_REPLY = 8 * 1024 * 1024


def origin(url):
    p = urlsplit(url)
    return p.scheme, p.hostname, p.port or (443 if p.scheme == 'https' else 80)


def validate_base(url):
    try:
        p = urlsplit(url)
        _ = p.port
        valid = (p.scheme == 'https' or (p.scheme == 'http' and p.hostname in ('127.0.0.1','localhost')))
        valid = valid and bool(p.hostname) and not p.username and not p.password and not p.query and not p.fragment
    except (ValueError, TypeError):
        valid = False
    if not valid:
        raise HTTPException(400, 'api_base_url requires HTTPS (HTTP is allowed only for loopback tests)')
    return url.rstrip('/')


class StudioTwinClient:
    def __init__(self, base, key):
        self.base = validate_base(base)
        if not isinstance(key, str) or not key or any(ord(c)<33 or ord(c)>126 for c in key):
            raise HTTPException(400, 'configure STUDIOTWIN_API_KEY in this profile')
        self.key = key
        self.session = None
        self.sequence = 0
        self.initialized = False
        self.http = httpx.Client(timeout=httpx.Timeout(45, connect=10), follow_redirects=False, trust_env=False)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        try:
            if self.session:
                try:
                    self.request('DELETE', self.base+'/mcp', headers={
                        'x-api-key':self.key, 'Mcp-Session-Id':self.session,
                        'MCP-Protocol-Version':'2025-06-18'})
                except HTTPException:
                    pass  # optional session cleanup must not mask the operation result
        finally:
            self.http.close()

    def storage_allowed(self, url):
        try:
            p = urlsplit(url)
            if p.username or p.password or p.fragment:
                return False
            if origin(url) == origin(self.base):
                return True
            host = p.hostname or ''
            return (p.scheme == 'https' and (p.port in (None,443)) and
                    (host.endswith('.amazonaws.com') and '.s3' in host or host == 'assets.studiotwin.ai'))
        except (TypeError, ValueError):
            return False

    def request(self, method, url, *, storage=False, cap=MAX_REPLY, metadata_sequence=None, **kwargs):
        def same_api(u):
            try:
                parts = urlsplit(u)
                return not parts.username and not parts.password and not parts.fragment and origin(u) == origin(self.base)
            except (TypeError, ValueError):
                return False
        allowed = self.storage_allowed if storage else same_api
        initial_origin = origin(url) if allowed(url) else None
        for _ in range(5):
            if not allowed(url):
                raise HTTPException(502, 'StudioTwin refused an unexpected network origin')
            try:
                with self.http.stream(method, url, **kwargs) as response:
                    if response.status_code in (301,302,303,307,308):
                        target = urljoin(url, response.headers.get('location',''))
                        if response.status_code not in (307,308) or not allowed(target) or origin(target) != initial_origin:
                            raise HTTPException(502, 'StudioTwin refused a foreign or unsafe redirect')
                        url = target
                        continue
                    if response.status_code >= 400:
                        # Never echo remote bodies or exception strings: upload POST fields
                        # and request credentials can occur in provider diagnostics.
                        raise HTTPException(502, f'StudioTwin request failed (HTTP {response.status_code})')
                    if metadata_sequence is not None:
                        try:
                            envelope = read_metadata(response.iter_bytes(chunk_size=16384),
                                response.headers.get('content-type', ''), metadata_sequence)
                            data = json.dumps(envelope).encode()
                            if len(data) > cap:
                                raise ValueError('retained metadata exceeds budget')
                            return {**response.headers, 'content-type': 'application/json'}, data
                        except (ValueError, UnicodeError, RecursionError):
                            raise HTTPException(502, 'invalid or excessive StudioTwin metadata') from None
                    data = bytearray()
                    for chunk in response.iter_bytes():
                        if len(data)+len(chunk)>cap:
                            raise HTTPException(413, 'StudioTwin response exceeds the media limit')
                        data.extend(chunk)
                    return response.headers, bytes(data)
            except httpx.HTTPError as exc:
                raise HTTPException(502, f'StudioTwin network failure ({type(exc).__name__})') from None
        raise HTTPException(502, 'too many StudioTwin redirects')

    def rpc(self, method, params=None, *, notification=False):
        self.sequence += 1
        payload = {'jsonrpc':'2.0','method':method, 'params':params or {}}
        if not notification:
            payload['id'] = self.sequence
        headers = {'x-api-key':self.key, 'Accept':'application/json, text/event-stream',
                   'MCP-Protocol-Version':'2025-06-18'}
        if self.session:
            headers['Mcp-Session-Id'] = self.session
        # Metadata readers share one bounded input projection. Downloads and
        # upload handshakes retain their existing binary/transport limits.
        metadata = method == 'tools/call' and (params or {}).get('name') in {
            'studiotwin_list_my_jobs', 'studiotwin_get_job_status',
            'studiotwin_list_my_assets', 'studiotwin_resolve_asset',
            'studiotwin_conceptlab_list', 'studiotwin_conceptlab_get',
            'studiotwin_conceptlab_get_status'}
        headers, data = self.request('POST', self.base+'/mcp', json=payload, headers=headers,
                                    **({'metadata_sequence': self.sequence} if metadata else {}))
        if headers.get('mcp-session-id'):
            self.session = headers['mcp-session-id']
        if notification:
            return None
        try:
            if headers.get('content-type','').startswith('text/event-stream'):
                messages = [json.loads(line[5:].strip()) for line in data.decode().splitlines() if line.startswith('data:')]
                envelope = next(m for m in messages if m.get('id') == self.sequence)
            else:
                envelope = json.loads(data)
            if not isinstance(envelope,dict) or envelope.get('id') != self.sequence or 'error' in envelope:
                raise ValueError
            return envelope['result']
        except (ValueError, KeyError, StopIteration, UnicodeError):
            raise HTTPException(502, 'invalid StudioTwin MCP response') from None

    def call(self, name, arguments=None):
        if not self.initialized:
            self.rpc('initialize', {'protocolVersion':'2025-06-18','capabilities':{},
                                   'clientInfo':{'name':'hermes-studiotwin-desktop','version':'0.2.0'}})
            self.rpc('notifications/initialized', notification=True)
            self.initialized = True
        result = self.rpc('tools/call', {'name':name, 'arguments':arguments or {}})
        if not isinstance(result, dict):
            raise HTTPException(502, 'invalid StudioTwin tool result')
        if result.get('isError'):
            text = ' '.join(b.get('text','') for b in result.get('content',[]) if b.get('type')=='text').lower()
            status = 404 if 'not found' in text else 409 if 'cannot be cancelled' in text else 502
            raise HTTPException(status, 'StudioTwin tool request failed')
        if isinstance(result.get('structuredContent'), (dict,list)):
            return result['structuredContent']
        try:
            return json.loads(next(b['text'] for b in result.get('content',[]) if b.get('type')=='text'))
        except (ValueError, KeyError, StopIteration):
            raise HTTPException(502, 'StudioTwin returned no JSON tool result') from None
