"""StudioTwin's non-authorizing Desktop backend (S11).

Guard patterns adapted from meshy/dashboard/plugin_api.py @1e326ddd (MIT).
Copyright (c) 2025 Nous Research

Core loads this file by path, not as a package. No profile, credential, socket
or database is opened at import. S28 supplies a per-profile Backend resolver
using configure(), or app.state.studiotwin for an isolated host. Until that
trusted lifecycle is bound, all routes fail closed; no hosted fallback exists.
"""
from __future__ import annotations

import hashlib
import hmac
import importlib
import inspect
import ipaddress
from pathlib import Path
import re
import struct
import sys
import time
import types

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.routing import APIRoute
from starlette.background import BackgroundTask

# Match core's spec_from_file_location loading without changing global sys.path.
if not __package__:
    name = '_hermes_studiotwin_dashboard_v1'
    root = Path(__file__).resolve().parent
    if name not in sys.modules:
        pkg = types.ModuleType(name); pkg.__path__ = [str(root)]; sys.modules[name] = pkg
    elif list(sys.modules[name].__path__) != [str(root)]:
        raise ImportError('StudioTwin package identity mismatch.')
    __package__ = name
ipc_module = importlib.import_module(__package__+'.ipc_client')
redaction, classification = ipc_module.redaction, ipc_module.classification
ProvenanceStore = importlib.import_module(__package__+'.provenance_store').ProvenanceStore
proxy_module = importlib.import_module(__package__+'.proxy')
CONTRACT = 'studiotwin.dashboard.v1'
MAX_JSON = 1048576
_resolver = None


class Refused(ValueError):
    def __init__(self, status=400, code='INVALID_REQUEST', headers=None):
        super().__init__('Request unavailable.')
        self.status,self.code,self.headers = status,code,headers or {}


def configure(resolver):
    """Trusted host lifecycle hook; resolver(request) returns current Backend.

    A resolver must use host-authenticated profile context, never browser scope
    parameters. No default profile/environment lookup is safe across requests.
    """
    global _resolver
    if not callable(resolver): raise ValueError('Backend resolver required.')
    _resolver = resolver


def _validated(schema, value, binding, sensitive=()):
    return redaction.validate_mediated_v1('dashboard#/components/schemas/'+schema,value,
        scope_id=binding[0],generation=binding[1],sensitive_values=sensitive).to_json()


def _json(schema, value, binding, sensitive=(), *, status=200, headers=None):
    safe = _validated(schema,value,binding,sensitive)
    return JSONResponse(safe,status_code=status,headers={'X-StudioTwin-Contract':CONTRACT,
        'X-Content-Type-Options':'nosniff','Cache-Control':'no-store',**(headers or {})})


def _error(error, binding=('0'*64,0)):
    # Static output only. A failed/secret-bearing binding or registry cannot
    # prevent a closed static fallback, and no raw header/exception is echoed.
    value = dict(contract=CONTRACT,code=error.code,message='Request unavailable.')
    schema = 'ErrorV1'
    if error.status==412:
        schema = 'IncompatibleContractV1'
        value.update(code='INCOMPATIBLE_PROTOCOL_VERSION',supported=[CONTRACT],received=None)
    try:
        return _json(schema,value,binding,status=error.status,headers=error.headers)
    except Exception:
        return _json('ErrorV1',dict(contract=CONTRACT,code='UNAVAILABLE',message='Request unavailable.'),
                     ('0'*64,0),status=503)


class GuardedRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()
        async def guarded(request):
            binding = ('0'*64,0)
            try:
                backend = _resolver(request) if _resolver else getattr(request.app.state,'studiotwin',None)
                if type(backend) is not Backend: raise Refused(503,'UNAVAILABLE')
                binding,session = await backend.guard(request)
                request.state.studiotwin_context = (backend,binding,session)
                result = await original(request)
                backend.check(binding)
                return result
            except Refused as e:
                return _error(e,binding)
            except proxy_module.ProxyRefused as e:
                code = {400:'INVALID_REQUEST',416:'INVALID_REQUEST',429:'RATE_LIMITED',415:'UNSUPPORTED_MEDIA'}.get(e.status,'NOT_FOUND')
                return _error(Refused(e.status,code,e.headers),binding)
            except Exception:
                return _error(Refused(503,'UNAVAILABLE'),binding)
        return guarded


class Backend:
    def __init__(self, ipc, store, proxy, *, current_binding, sensitive_values,
                 authenticate, allowed_hosts, allowed_origins, catalog=None, clock=None):
        self.ipc,self.store,self.proxy = ipc,store,proxy
        self._current,self._sensitive,self.authenticate = current_binding,sensitive_values,authenticate
        self.allowed_hosts,self.allowed_origins = frozenset(allowed_hosts),frozenset(allowed_origins)
        if not self.allowed_hosts or not self.allowed_origins or not callable(authenticate):
            raise ValueError('Explicit host authentication and origins required.')
        self.catalog = catalog
        self.limits = proxy_module.SessionLimits(clock=clock or time.monotonic)
        self.provenance = ProvenanceStore(store)
        self._memo = {}

    def __repr__(self): return '<StudioTwinBackend>'

    def check(self, binding):
        if self._current() != binding: raise Refused(404,'NOT_FOUND')
        self.store.require_current(*binding)

    def validate(self, schema, value, binding):
        return _validated(schema,value,binding,tuple(self._sensitive()))

    async def guard(self, request):
        for header in ('host','origin','x-studiotwin-contract','x-studiotwin-csrf','content-length','content-type'):
            if len(request.headers.getlist(header))>1: raise Refused()
        if request.headers.get('host') not in self.allowed_hosts: raise Refused(403)
        # Host admission is an injected trusted adapter, not a browser boolean.
        identity = self.authenticate(request)
        if inspect.isawaitable(identity): identity = await identity
        if type(identity) is not tuple or len(identity)!=2: raise Refused(401)
        session,csrf = identity
        binding = self._current()
        redaction._binding(*binding)
        self.check(binding)
        self.validate('LocalIdV1',session,binding)
        origin = request.headers.get('origin')
        if origin is not None and origin not in self.allowed_origins: raise Refused(403)
        # Native host requests may omit Origin; mutation still needs the
        # independently host-issued CSRF secret. Media tags may omit version.
        if request.method not in ('GET','HEAD'):
            supplied = request.headers.get('x-studiotwin-csrf','')
            if type(csrf) is not str or len(csrf)<16 or not hmac.compare_digest(supplied.encode(),csrf.encode()):
                raise Refused(403)
        media = request.url.path.endswith('/local/file') and request.method=='GET'
        version = request.headers.get('x-studiotwin-contract')
        if version != CONTRACT and not (media and version is None): raise Refused(412)
        self.limits.request((*binding,session))
        return binding,session

    async def body(self, request, schema, binding):
        if request.headers.get('content-type','').split(';')[0].strip().lower()!='application/json': raise Refused(415,'UNSUPPORTED_MEDIA')
        length = request.headers.get('content-length')
        if length is not None:
            if not re.fullmatch(r'[0-9]{1,12}',length): raise Refused()
            if int(length)>MAX_JSON: raise Refused(413,'TOO_LARGE')
        data = bytearray()
        async for chunk in request.stream():
            if len(data)+len(chunk)>MAX_JSON: raise Refused(413,'TOO_LARGE')
            data.extend(chunk)
        try:
            value = ipc_module.ipc.decode(bytes(data))
            return self.validate(schema,value,binding)
        except Exception:
            pass
        raise Refused()

    def response(self, schema, value, binding):
        return _json(schema,value,binding,tuple(self._sensitive()))

    async def call(self, method, params, schema, binding):
        self.check(binding)
        envelope = (await self.ipc.request(method,params)).to_json()
        self.check(binding)
        if not envelope['ok']:
            code = envelope['error']['code']
            raise Refused(503,'SCHEMA_UNAVAILABLE' if code=='SCHEMA_UNAVAILABLE' else 'UNAVAILABLE')
        if envelope['result']['method']!=method: raise Refused(503,'UNAVAILABLE')
        value = self.validate(schema,envelope['result']['payload'],binding)
        if method=='capabilities.inputSchema':
            classification.validate_input_schema_response_v1(envelope,wrapped=True,
                scope_id=binding[0],generation=binding[1],sensitive_values=tuple(self._sensitive()))
            if value['tool']!=params['tool'] or value['schemaHash']!=params['schemaHash']: raise Refused(503,'SCHEMA_UNAVAILABLE')
        return value

    async def cached_read(self, method, schema, kind, ttl, binding):
        key = (binding,method)
        now = self.limits.clock()
        if key in self._memo and now-self._memo[key][0]<ttl:
            return self.validate(schema,self._memo[key][1],binding)
        value = await self.call(method,{},schema,binding)
        self.store.put(kind,'current',value,scope_id=binding[0],generation=binding[1])
        # Reconnect/rotation creates a new Backend. No old-scope memo survives.
        self._memo = {k:v for k,v in self._memo.items() if k[0]==binding}
        self._memo[key] = (now,value)
        return value

    async def source(self, value, binding, session):
        path,handle = value.get('sourcePath'),None
        if 'source' in value:
            source = value['source']
            if source['kind']=='handle': handle = source['handle']
            else:
                descriptor = (await self.ipc.request('resources.resolveStream',{'source':source})).to_json()
                self.check(binding)
                if not descriptor['ok']: raise Refused(404,'NOT_FOUND')
                handle = descriptor['result']['payload']['handle']
            self.proxy.handles.resolve(handle,scope_id=binding[0],generation=binding[1],purpose='resource',operation='process',consume=False)
        lease = self.proxy.prepare(path=path,handle=handle,scope_id=binding[0],generation=binding[1],session=session)
        if lease.headers['Content-Type']!='model/gltf-binary':
            lease.close(); raise Refused(415,'UNSUPPORTED_MEDIA')
        return lease


router = APIRouter(route_class=GuardedRoute)
_services = set()


def register_service(service_id, router):
    """S28 calls once per frozen backend leaf before mounting on core."""
    if type(service_id) is not str or not re.fullmatch(r'[a-z][a-z0-9_]{0,31}',service_id) or service_id in _services:
        raise ValueError('Invalid or duplicate service.')
    if not isinstance(router,APIRouter): raise ValueError('Router required.')
    target = globals()['router']
    existing = {(r.path,m) for r in target.routes for m in r.methods}
    proposed = {(r.path,m) for r in router.routes for m in r.methods}
    if existing & proposed: raise ValueError('Duplicate route.')
    # Include copied leaf routes under the same security wrapper, never mutate
    # a leaf's own router. Shared router.py remains entirely S28-owned.
    for route in router.routes:
        target.add_api_route(route.path,route.endpoint,methods=list(route.methods),response_model=route.response_model)
    _services.add(service_id)


def context(request): return request.state.studiotwin_context


def query(request, allowed):
    if any(k not in allowed or len(request.query_params.getlist(k))!=1 for k in request.query_params): raise Refused()
    return dict(request.query_params)


@router.get('/status')
async def status(request: Request):
    b,binding,_ = context(request); query(request,set())
    return b.response('StatusV1',await b.cached_read('status.get','StatusV1','status',15,binding),binding)


@router.get('/capabilities')
async def capabilities(request: Request):
    b,binding,_ = context(request); query(request,set())
    value = await b.cached_read('capabilities.list','CapabilitiesV1','capabilities',60,binding)
    return b.response('CapabilitiesV1',value,binding)


@router.get('/capabilities/{tool}/input-schema')
async def input_schema(request: Request):
    b,binding,_ = context(request)
    params = query(request,{'schemaHash'})
    params['tool'] = request.path_params['tool']
    if 'schemaHash' not in params: raise Refused()
    return b.response('ToolInputSchemaResponseV1',await b.call('capabilities.inputSchema',params,'ToolInputSchemaResponseV1',binding),binding)


@router.post('/provenance')
async def provenance(request: Request):
    b,binding,_ = context(request); query(request,set())
    value = await b.body(request,'ProvenanceRecordRequestV1',binding)
    return b.response('ProvenanceRecordedV1',b.provenance.record(value,scope_id=binding[0],generation=binding[1]).to_json(),binding)


@router.get('/lineage/{asset}')
async def lineage(request: Request):
    b,binding,_ = context(request); query(request,set())
    asset = request.path_params['asset']
    try: b.validate('UuidV1',asset,binding)
    except Exception: raise Refused() from None
    try:
        value = await b.call('lineage.get',{'assetId':asset},'LineageV1',binding)
    except Refused as e:
        if e.status!=503: raise
    else:
        if value['root']!=asset: raise Refused(503,'UNAVAILABLE')
        b.provenance.merge_server(value,scope_id=binding[0],generation=binding[1])
    value = b.provenance.lineage(asset,scope_id=binding[0],generation=binding[1]).to_json()
    return b.response('LineageV1',value,binding)


@router.get('/local/file')
async def local_file(request: Request):
    b,binding,session = context(request)
    params = query(request,{'path','handle'})
    lease = b.proxy.prepare(**params,scope_id=binding[0],generation=binding[1],session=session,range_header=request.headers.get('range'))
    async def chunks():
        try:
            for chunk in lease.chunks(): yield chunk
        finally:
            lease.close()
    return StreamingResponse(chunks(),status_code=lease.status,headers={**lease.headers,'X-StudioTwin-Contract':CONTRACT},background=BackgroundTask(lease.close))


@router.post('/operations/quote')
async def quote(request: Request):
    b,binding,_ = context(request); query(request,set())
    value = await b.body(request,'QuoteRequestV1',binding)
    try:
        if b.catalog is None: raise Refused()
        b.catalog.candidate_inputs(value['tool'],value['schemaHash'],value['inputs'],scope_id=binding[0],generation=binding[1],sensitive_values=tuple(b._sensitive()))
    except Exception:
        raise Refused() from None
    return b.response('QuotePreviewV1',await b.call('operations.quote',value,'QuotePreviewV1',binding),binding)


@router.get('/operations/{operationId}')
async def operation(request: Request):
    b,binding,_ = context(request); query(request,set())
    identifier = request.path_params['operationId']
    redaction.validate_mediated_v1('gateway#/$defs/OperationIdV1',identifier,scope_id=binding[0],generation=binding[1],sensitive_values=tuple(b._sensitive()))
    value = await b.call('operations.get',{'operationId':identifier},'OperationStateV1',binding)
    if value['operation']['operationId']!=identifier or value['operation']['scopeId']!=binding[0]: raise Refused(404,'NOT_FOUND')
    return b.response('OperationStateV1',value,binding)


@router.post('/scope-pause/acknowledge')
async def acknowledge(request: Request):
    b,binding,_ = context(request); query(request,set())
    value = await b.body(request,'ScopePauseAcknowledgeRequestV1',binding)
    if value['scopeId']!=binding[0]: raise Refused(404,'NOT_FOUND')
    result = await b.call('scopePause.acknowledge',value,'ScopePauseAcknowledgedV1',binding)
    if any(result[k]!=value[k] for k in ('scopeId','operationId')): raise Refused(503,'UNAVAILABLE')
    # The gateway's S10 atomic service is authoritative, not a local pause copy.
    return b.response('ScopePauseAcknowledgedV1',result,binding)


def glb_stats(stream):
    size = __import__('os').fstat(stream.fileno()).st_size
    stream.seek(0)
    head = stream.read(20)
    if len(head)!=20: raise Refused(415,'UNSUPPORTED_MEDIA')
    magic,version,total,length,kind = struct.unpack('<4sIIII',head)
    if magic!=b'glTF' or version!=2 or total!=size or kind!=0x4e4f534a or length>MAX_JSON or length+20>size or length%4:
        raise Refused(415,'UNSUPPORTED_MEDIA')
    model = ipc_module.ipc.decode(stream.read(length))
    if type(model) is not dict or model.get('asset',{}).get('version')!='2.0': raise Refused(415,'UNSUPPORTED_MEDIA')
    meshes,accessors = model.get('meshes',[]),model.get('accessors',[])
    vertices = triangles = 0
    for mesh in meshes:
        for primitive in mesh.get('primitives',[]):
            index = primitive.get('attributes',{}).get('POSITION')
            count = accessors[index]['count'] if type(index) is int and 0<=index<len(accessors) else 0
            indices = primitive.get('indices')
            elements = accessors[indices]['count'] if type(indices) is int and 0<=indices<len(accessors) else count
            if type(count) is not int or type(elements) is not int or min(count,elements)<0: raise Refused(415,'UNSUPPORTED_MEDIA')
            vertices += count
            mode = primitive.get('mode',4)
            if mode==4: triangles += elements//3
            elif mode in (5,6): triangles += max(0,elements-2)
    return dict(contract=CONTRACT,format='glb',bytes=size,meshes=len(meshes),vertices=vertices,triangles=triangles,
                materials=len(model.get('materials',[])),animations=len(model.get('animations',[])))


@router.post('/local/model/stats')
async def model_stats(request: Request):
    b,binding,session = context(request); query(request,set())
    value = await b.body(request,'LocalModelStatsRequestV1',binding)
    key = (*binding,session)
    b.limits.acquire(key,'processor',2)
    lease = None
    try:
        lease = await b.source(value,binding,session)
        result = glb_stats(lease.stream)
        b.check(binding)
        return b.response('ModelStatsV1',result,binding)
    finally:
        if lease: lease.close()
        b.limits.release(key,'processor')


@router.post('/handoff/blender/plan')
async def blender_plan(request: Request):
    b,binding,session = context(request); query(request,set())
    value = await b.body(request,'BlenderPlanRequestV1',binding)
    output = Path(value['outputDir'])
    if not output.is_absolute() or not output.is_dir() or output.resolve(strict=True)!=output or not any(output.is_relative_to(r) for r in b.proxy.sandbox._roots):
        raise Refused(400,'SANDBOX_REFUSED')
    key = (*binding,session)
    b.limits.acquire(key,'blender',1)
    lease = None
    try:
        lease = await b.source(value,binding,session)
        glb_stats(lease.stream)
        digest = hashlib.sha256(); lease.stream.seek(0)
        while True:
            b.check(binding)
            chunk = lease.stream.read(proxy_module.CHUNK)
            if not chunk: break
            digest.update(chunk)
        result = dict(contract=CONTRACT,executes=False,mutatesOpenScene=False,writesNewFiles=True,requiresSeparateConsent=True,
            sourceSha256=digest.hexdigest(),steps=['Verify unchanged source digest.','Request separate explicit consent.','Import into a new Blender scene and write new files without overwriting.'])
        return b.response('BlenderPlanV1',result,binding)
    finally:
        if lease: lease.close()
        b.limits.release(key,'blender')
