"""S07 pre-core classified output coordinator; never a transparent MCP proxy.

OutputPolicy/ResourceRule are BACKEND release-policy seams for S08, not model
or dashboard arguments. S08 must match live/reviewed schemas before supplying
one. S09/S10 own dispatch authorization; S11 owns network/redirect/Range policy.
No hosted calls, logger, or persistent secret store is implemented here.
"""
from __future__ import annotations

from collections.abc import Collection
from contextlib import ExitStack
import base64
import html
from dataclasses import dataclass
import json
import re
import secrets
from threading import RLock
from urllib.parse import urlsplit, parse_qsl, unquote

from .handles import HandleStore, HandleNotFound
from .media_cache import CATEGORY_CAPS, DEFAULT_QUOTA, MediaRefused
from .mediation_parse import (BoundaryRefused, Budget, bounded_copy_v1,
                              embedded_json_v1, decode_json_escapes_v1)
from .redaction import (redact_upstream_v1, validate_mediated_v1, _binding,
                        _BANNED_NAME, _B64)

_MISSING = object()
_LOCATION = re.compile(r'(?:https?|s3)://[^\s"<>]+', re.I)


def _location_views(value):
    """Bounded S06-compatible normalization, not arbitrary recursive decoding."""
    yield value
    for _ in range(3):
        decoded=decode_json_escapes_v1(html.unescape(unquote(value)))
        if decoded==value:
            break
        value=decoded
        yield value
    for match in re.finditer(r'(?<![0-9a-fA-F])(?:[0-9a-fA-F]{2}){8,}(?![0-9a-fA-F])',value):
        yield bytes.fromhex(match.group()).decode('utf-8',errors='replace')
    for match in _B64.finditer(value):
        token=match.group()
        try:
            blob=base64.b64decode(token+'='*(-len(token)%4),altchars=b'-_',validate=True)
        except ValueError:
            continue
        yield blob.decode('utf-8',errors='replace')


class SensitiveValueRegistry(Collection):
    """Ephemeral provenance collection accepted by S06's frozen Collection API.

    S06's implementation calls its internal snapshot _Sensitive, not
    SensitiveValueRegistry. This adapter adds accumulation, never replaces its
    detectors. Do not log/persist/serialize this object.
    """
    def __init__(self, values=()):
        self._values=set()
        for value in values:
            self.register(value)

    def __repr__(self):
        return '<SensitiveValueRegistry>'

    def __contains__(self, value):
        return value in self._values

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def register(self, value):
        if type(value) is str:
            if value:
                self._values.add(value)
        elif type(value) in (dict,list):
            self._values.add(json.dumps(value,sort_keys=True,separators=(',',':')))
            for child in (value.values() if type(value) is dict else value):
                self.register(child)
        elif value is not None and type(value) not in (int,float,bool):
            raise BoundaryRefused()
        if len(self._values) > 10000:
            raise BoundaryRefused()

    def location(self, value):
        self.register(value)
        parsed=urlsplit(value)
        for _, part in parse_qsl(parsed.query,keep_blank_values=False):
            self.register(part)
        # Credential-labelled path segments are privileged too. Ordinary public
        # path labels (e.g. /file) are not by themselves credential provenance.
        parts=unquote(parsed.path).split('/')
        for index, part in enumerate(parts):
            if _BANNED_NAME.search(part):
                if '=' in part:
                    self.register(part.split('=',1)[1])
                elif index+1<len(parts):
                    self.register(parts[index+1])
        if parsed.scheme.lower()=='s3':
            self.register(unquote(parsed.netloc))
            if parsed.path.strip('/'):
                self.register(unquote(parsed.path.strip('/')))
        if parsed.username: self.register(unquote(parsed.username))
        if parsed.password: self.register(unquote(parsed.password))

    def collect(self, candidate):
        """All channels, including encoded strings and dictionary keys."""
        budget=Budget()
        def walk(value, depth=0):
            budget.visit(depth)
            if type(value) is dict:
                for key, child in value.items():
                    walk(key,depth+1)
                    if _BANNED_NAME.search(key) or key == 'fields':
                        self.register(child)
                    walk(child,depth+1)
            elif type(value) is list:
                for child in value: walk(child,depth+1)
            elif type(value) is str:
                for view in _location_views(value):
                    budget.visit(depth+1)
                    for location in _LOCATION.findall(view): self.location(location)
                    for _,_,parsed in embedded_json_v1(view):
                        walk(bounded_copy_v1(parsed,budget=budget,depth=depth+1),depth+1)
        walk(candidate)


@dataclass(frozen=True, slots=True)
class ResourceRule:
    path: tuple
    kind: str
    role: str
    mime: str
    size: int | None = None
    asset_id_path: tuple | None = None


@dataclass(frozen=True, slots=True)
class OutputPolicy:
    tool: str
    schema_hash: str
    resources: tuple[ResourceRule,...] = ()
    group: str = 'single'
    summary_path: tuple | None = None
    job_path: tuple | None = None
    upload_path: tuple | None = None
    upload_id_path: tuple | None = None
    fps: float | None = None
    manifest: bool = False


def _get(value, path):
    if path is None:
        return _MISSING
    if type(path) is not tuple or not path or len(path) > 16:
        raise BoundaryRefused()
    for part in path:
        if type(value) is str:
            # A reviewed path may traverse ONE bounded JSON container inside a
            # text block/fence. Ambiguous multiple containers are never guessed.
            containers=[parsed for _,_,parsed in embedded_json_v1(value) if type(parsed) in (dict,list)]
            if len(containers)!=1:
                return _MISSING
            value=bounded_copy_v1(containers[0])
        if type(value) is dict and type(part) is str:
            value=value.get(part,_MISSING)
        elif type(value) is list and type(part) is int and 0 <= part < len(value):
            value=value[part]
        else:
            return _MISSING
    return value


def _location(value):
    if type(value) is not str or len(value)>16384:
        raise BoundaryRefused()
    parsed=urlsplit(value)
    if (parsed.scheme not in ('https','s3') or not parsed.netloc or parsed.fragment or
            parsed.username or parsed.password or any(c.isspace() or ord(c)<32 for c in value)):
        raise BoundaryRefused()
    return parsed.scheme


class Mediator:
    def __init__(self, handles: HandleStore, *, cache=None, loader=None, storage_resolver=None):
        self.handles, self.cache = handles, cache
        # Backend-only hooks. A loader MUST enforce S11's host/redirect policy;
        # it returns bounded bytes, never an outbound URL or exception string.
        self.loader, self.storage_resolver = loader, storage_resolver
        self._lock=RLock()

    def mediate(self, upstream, *, scope_id, generation, policy, live_schema_hash,
                sensitive_values=()):
        failed=False
        result=None
        minted=[]
        try:
            with self._lock, ExitStack() as transaction:
                if self.cache is not None:
                    transaction.enter_context(self.cache.batch())
                _binding(scope_id,generation)
                self.handles.bind(scope_id,generation)
                if (type(policy) is not OutputPolicy or policy.schema_hash != live_schema_hash or
                        not re.fullmatch('[0-9a-f]{64}',policy.schema_hash) or
                        type(policy.resources) is not tuple or len(policy.resources)>4096):
                    raise BoundaryRefused()
                raw=bounded_copy_v1(upstream)
                registry=SensitiveValueRegistry(sensitive_values)
                # Complete provenance is collected BEFORE ANY upstream fields
                # are discarded. Ordinary-looking POST values matter too.
                registry.collect(raw)
                extracted=[]
                seen_paths=set()
                total=0
                for rule in policy.resources:
                    if type(rule) is not ResourceRule or rule.path in seen_paths:
                        raise BoundaryRefused()
                    seen_paths.add(rule.path)
                    location=_get(raw,rule.path)
                    if location is _MISSING or location is None:
                        if policy.group=='image_sequence':
                            raise BoundaryRefused()
                        continue
                    if policy.group=='material' and (rule.kind!='image' or not rule.mime.startswith('image/')):
                        raise BoundaryRefused()
                    if policy.group=='world' and ((rule.role=='worldMesh' and rule.kind!='model') or
                            (rule.role=='skyMap' and rule.kind not in ('image','environment'))):
                        raise BoundaryRefused()
                    if policy.group=='image_sequence' and rule.role!='image':
                        # Sequence manifests are generated locally below, not
                        # trusted remote JSON (which may contain secret URLs).
                        raise BoundaryRefused()
                    scheme=_location(location)
                    registry.location(location)
                    if rule.size is not None:
                        if type(rule.size) is not int or not 0 <= rule.size <= CATEGORY_CAPS.get(rule.kind,0):
                            raise BoundaryRefused()
                        total += rule.size
                    if total > DEFAULT_QUOTA:
                        raise BoundaryRefused()
                    asset_id=_get(raw,rule.asset_id_path)
                    if asset_id is _MISSING:
                        asset_id=None
                    extracted.append((rule,location,scheme,asset_id))
                session=_get(raw,policy.upload_path)
                if session is not _MISSING:
                    if policy.upload_id_path is not None:
                        # Captured platform response: {uuid,preSignedPost:{url,fields}}.
                        # Paths are release-classified, never inferred from a
                        # random credential-shaped object in unknown metadata.
                        if type(session) is not dict or set(session)!={'url','fields'}:
                            raise BoundaryRefused()
                        session=dict(session,uploadSessionId=_get(raw,policy.upload_id_path))
                    if (type(session) is not dict or set(session)-{'url','fields','uploadSessionId','expiresAt'} or
                            type(session.get('fields')) is not dict or
                            type(session.get('uploadSessionId')) is not str):
                        raise BoundaryRefused()
                    if _location(session.get('url')) != 'https':
                        raise BoundaryRefused()
                    registry.register(session)
                    registry.location(session['url'])
                # Scan every channel; only explicitly classified scalar/resource
                # fields below may enter the outbound candidate.
                redact_upstream_v1(raw,sensitive_values=registry)
                resources=[]
                media=[]
                for rule,location,scheme,asset_id in extracted:
                    can_resolve=scheme=='https' or self.storage_resolver is not None
                    source=route=None
                    if can_resolve:
                        token=self.handles.mint(scope_id=scope_id,generation=generation,purpose='resource',
                            kind=rule.kind,role=rule.role,mime=rule.mime,size=rule.size,
                            target={'location':location,'assetId':asset_id},operations=('read','process'))
                        minted.append(token)
                        source={'kind':'handle','handle':token}
                        route='/api/plugins/hermes-studiotwin/local/file?handle='+token
                    descriptor=dict(resourceId='res_'+secrets.token_hex(16),kind=rule.kind,assetId=asset_id,
                        libraryState='indexed' if asset_id is not None else 'not-in-library',
                        mime=rule.mime,source=source,contentRoute=route)
                    resources.append((rule.role,descriptor))
                    # Optional actual byte materialization. No fictitious MEDIA
                    # path is ever emitted when no bytes were safely cached.
                    if can_resolve and self.cache is not None and (self.loader if scheme=='https' else self.storage_resolver):
                        item=self.materialize(token,scope_id=scope_id,generation=generation)
                        minted.append(item.handle)
                        media.append(dict(localPath=item.path,handle=item.handle,kind=item.kind,mime=item.mime,assetId=asset_id))
                if session is not _MISSING:
                    if resources:
                        raise BoundaryRefused()
                    token=self.handles.mint(scope_id=scope_id,generation=generation,purpose='upload',
                        kind='other',role='upload',mime='application/json',size=None,target=session,
                        operations=('put','complete'),expires_at=session.get('expiresAt'))
                    minted.append(token)
                    resources.append(('upload',dict(resourceId='res_'+secrets.token_hex(16),kind='other',assetId=None,
                        libraryState='not-in-library',mime='application/json',source={'kind':'handle','handle':token},contentRoute=None)))
                groups=self._groups(policy,resources)
                if type(policy.manifest) is not bool:
                    raise BoundaryRefused()
                if policy.manifest:
                    if policy.group!='image_sequence' or self.cache is None:
                        raise BoundaryRefused()
                    safe_group=validate_mediated_v1('gateway#/$defs/ResourceGroupV1',groups[0],
                        scope_id=scope_id,generation=generation,sensitive_values=registry).to_json()
                    payload=json.dumps({'fps':safe_group['fps'],'frames':safe_group['frames']},
                        sort_keys=True,separators=(',',':')).encode()
                    item=self.cache.put(scope_id=scope_id,generation=generation,data=payload,
                        mime='application/json',kind='manifest',extension='.json')
                    minted.append(item.handle)
                    groups[0]['manifest']=dict(resourceId='res_'+secrets.token_hex(16),kind='manifest',assetId=None,
                        libraryState='not-in-library',mime='application/json',source={'kind':'handle','handle':item.handle},
                        contentRoute='/api/plugins/hermes-studiotwin/local/file?handle='+item.handle)
                summary=_get(raw,policy.summary_path)
                if summary is _MISSING or type(summary) is not str:
                    summary='Upstream result mediated.'
                summary=redact_upstream_v1(summary,sensitive_values=registry)
                job_id=_get(raw,policy.job_path)
                if job_id is _MISSING:
                    job_id=None
                candidate=dict(protocol='studiotwin.gateway.v1',tool=policy.tool,
                    status='error' if type(raw) is dict and (raw.get('isError') is True or 'error' in raw) else 'ok',jobId=job_id,
                    assetIds=list(dict.fromkeys(d['assetId'] for _,d in resources if d['assetId'] is not None)),
                    media=media,summary=summary,operation=None,outputGroups=groups)
                result=validate_mediated_v1('gateway#/$defs/GatewayResultV1',candidate,
                    scope_id=scope_id,generation=generation,sensitive_values=registry)
        except Exception:
            # Roll back all capabilities even on backend/cache/validator faults;
            # never forward upstream-bearing exception strings or chains.
            failed=True
        if failed:
            for token in minted: self.handles.revoke(token)
            raise BoundaryRefused()
        return result

    @staticmethod
    def _groups(policy, resources):
        def slot(role):
            found=[d for r,d in resources if r==role]
            if len(found)>1:
                raise BoundaryRefused()
            return {'state':'present','resource':found[0]} if found else {'state':'absent','resource':None}
        if policy.group=='single':
            return [{'kind':'single','resource':d} for _,d in resources]
        if policy.group=='image_sequence':
            frames=[d for r,d in resources if r=='image']
            if any(d['kind']!='image' or not (d['mime'] or '').startswith('image/') for d in frames):
                raise BoundaryRefused()
            manifests=[d for r,d in resources if r=='manifest']
            if (len(manifests)>1 or len(frames)+len(manifests)!=len(resources) or
                    any(d['kind']!='manifest' or d['mime']!='application/json' for d in manifests)):
                raise BoundaryRefused()
            return [dict(kind='image_sequence',frames=[dict(index=i,name=f'frame_{i:04d}',resource=d) for i,d in enumerate(frames)],
                         fps=policy.fps,manifest=manifests[0] if manifests else None)]
        if policy.group in ('material','world'):
            roles=('albedo','normal','roughness','metalness','height') if policy.group=='material' else ('skyMap','worldMesh')
            if any(role not in roles for role,_ in resources):
                raise BoundaryRefused()
            return [dict(kind=policy.group,**{'maps' if policy.group=='material' else 'outputs':{r:slot(r) for r in roles}})]
        if policy.group in ('image_set','environment','motion'):
            return [dict(kind=policy.group,members=[dict(role=r,slot={'state':'present','resource':d}) for r,d in resources])]
        raise BoundaryRefused()

    def stream_response(self, token, *, request_id, scope_id, generation, method='resources.resolveStream', sensitive_values=()):
        if method not in ('resources.resolveStream','assets.resolveStream','assets.thumbnail'):
            raise BoundaryRefused()
        row=self.handles.resolve(token,scope_id=scope_id,generation=generation,purpose='resource',operation='read',consume=False)
        registry=SensitiveValueRegistry(sensitive_values)
        registry.collect(dict(row.target))
        candidate=dict(protocol='studiotwin.host-gateway.v1',requestId=request_id,ok=True,
            result=dict(method=method,payload=dict(handle=token,mime=row.mime,bytes=row.size,assetId=row.target.get('assetId'))))
        return validate_mediated_v1('host_gateway#/$defs/IpcResponseV1',candidate,
            scope_id=scope_id,generation=generation,sensitive_values=registry)

    def materialize(self, token, *, scope_id, generation):
        failed=False
        result=None
        try:
            result=self._materialize(token,scope_id=scope_id,generation=generation)
        except Exception:
            # External loader exceptions can contain signed request traces.
            # Neither direct callers nor mediate() receive the original chain.
            failed=True
        if failed:
            raise MediaRefused()
        return result

    def _materialize(self, token, *, scope_id, generation):
        """Consume a resource capability, cache bytes, reapply open/fstat checks.

        The injected S11 loader gets a backend-only HandleRecord. It must bound
        streaming and apply host/redirect policy before returning (bytes,suffix).
        The cache enforces type/sniff/category/quota again. Not a URL passthrough.
        """
        row=self.handles.resolve(token,scope_id=scope_id,generation=generation,purpose='resource',operation='read')
        if self.cache is None:
            raise MediaRefused()
        location=row.target.get('location')
        if location is None:
            path=row.target.get('localPath')
            with self.cache.open(path,scope_id=scope_id,generation=generation,mime=row.mime,kind=row.kind):
                pass
            raise MediaRefused()  # already-local callers should open_source()
        loader=self.storage_resolver if urlsplit(location).scheme=='s3' else self.loader
        if loader is None:
            raise MediaRefused()
        data,suffix=loader(row)
        if row.size is not None and len(data)!=row.size:
            raise MediaRefused()
        return self.cache.put(scope_id=scope_id,generation=generation,data=data,mime=row.mime,kind=row.kind,extension=suffix)

    def open_source(self, token, *, scope_id, generation):
        row=self.handles.resolve(token,scope_id=scope_id,generation=generation,purpose='resource',operation='process')
        if self.cache is None or 'localPath' not in row.target:
            raise MediaRefused()
        return self.cache.open(row.target['localPath'],scope_id=scope_id,generation=generation,mime=row.mime,kind=row.kind)
