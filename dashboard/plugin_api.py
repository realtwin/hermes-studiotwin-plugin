"""StudioTwin Desktop backend, loaded by the host at /api/plugins/hermes-studiotwin.

The host owns authentication and profile context. Settings, secrets and storage roots
are resolved per request. This router only reads, uploads, cancels and records lineage;
paid generation stays on the remote MCP server behind Hermes's native approval UI.
File/range patterns adapted from Nous Research's Meshy and ElevenLabs SFX (MIT).
Copyright (c) 2025 Nous Research (Meshy).
Copyright (c) 2026 Nous Research (ElevenLabs SFX).
"""
from __future__ import annotations

import base64
import importlib
import io
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import types
import uuid
from email.parser import BytesParser
from email.policy import default as email_policy
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.concurrency import run_in_threadpool

# The host imports plugin_api.py by file path, without a package. Give sibling
# helpers an install-specific namespace; never alter global sys.path.
if not __package__:
    import hashlib
    name = '_hermes_studiotwin_' + hashlib.sha256(str(Path(__file__).resolve().parent).encode()).hexdigest()[:12]
    if name not in sys.modules:
        pkg = types.ModuleType(name)
        pkg.__path__ = [str(Path(__file__).resolve().parent)]
        sys.modules[name] = pkg
    __package__ = name

client_module = importlib.import_module(__package__ + '.studiotwin_client')
sandbox = importlib.import_module(__package__ + '.sandbox')
store = importlib.import_module(__package__ + '.store')
proxy = importlib.import_module(__package__ + '.proxy')
ProvenanceStore = importlib.import_module(__package__ + '.provenance_store').ProvenanceStore
router = APIRouter()
KEY_ENV = 'STUDIOTWIN_API_KEY'
DEFAULTS = {'api_base_url':'https://api.studiotwin.ai', 'show_credits':True, 'inline_cards':True,
            'auto_rotate':True, 'webgl_limit':4, 'gallery_limit':24, 'blender_handoff':'ask', 'blender_path':''}
TYPES = {'image','image_sequence','3d_model','animation','audio','video','unknown','jpg','png'}
CONVERSIONS = {'mp3':['-c:a','libmp3lame','-b:a','192k'], 'wav':['-c:a','pcm_s16le'],
               'ogg':['-c:a','libvorbis','-q:a','5'], 'flac':['-c:a','flac']}
AUDIO = {'.wav','.mp3','.ogg','.opus','.flac'}


def _settings():
    from hermes_cli.config import load_config_readonly
    saved = (((load_config_readonly() or {}).get('plugins') or {}).get('entries') or {}).get('hermes-studiotwin') or {}
    saved = saved.get('settings') if isinstance(saved, dict) else {}
    saved = saved if isinstance(saved, dict) else {}
    out = {k:saved.get(k, v) if type(saved.get(k,v)) is type(v) else v for k,v in DEFAULTS.items()}
    out['api_base_url'] = client_module.validate_base(out['api_base_url'])
    out['webgl_limit'] = max(1,min(4,out['webgl_limit']))
    out['gallery_limit'] = max(1,min(100,out['gallery_limit']))
    if out['blender_handoff'] not in ('ask','always','never'):
        out['blender_handoff'] = 'ask'
    return out


def _api_key():
    from agent.secret_scope import get_secret
    return get_secret(KEY_ENV)


def _client():
    return client_module.StudioTwinClient(_settings()['api_base_url'], _api_key())


def _call(tool, args=None):
    with _client() as client:
        return client.call(tool, args)


def _data_root():
    from hermes_constants import get_hermes_home
    base = get_hermes_home() / 'plugin-data'
    found = sorted(base.glob('agent-plugin-hermes-studiotwin-*')) if base.is_dir() else []
    return found[0] if found else base / 'agent-plugin-hermes-studiotwin'


def _allowed_roots():
    from hermes_constants import get_hermes_home
    return [_data_root(), get_hermes_home() / 'cache/generated', Path.home()]


def _id(value):
    if not isinstance(value,str) or not re.fullmatch(r'[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}',value):
        raise HTTPException(400, 'a UUID is required')
    return value


def _index():
    return store.AssetIndex(_data_root())


def _provenance():
    return ProvenanceStore(_data_root())


def _kind(path):
    ext = path.suffix.lower()
    if ext in AUDIO:
        return 'audio'
    if ext in ('.hdr','.exr','.png','.jpg','.jpeg','.webp'):
        return 'image'
    return {'.mp4':'video','.tar':'image_sequence','.json':'animation'}.get(ext,'3d_model')


def _local_rows():
    rows = _index().rows()
    known = {r['path'] for r in rows}
    cache = _data_root() / 'studio_cache'
    if cache.is_dir() and not cache.is_symlink():
        rows += [{'path':str(p)} for p in cache.iterdir() if str(p) not in known]
    result = []
    for row in rows:
        try:
            p = sandbox.readable(row['path'],_allowed_roots())
            st = p.stat()
        except (HTTPException,OSError):
            continue
        result.append({**row,'path':str(p),'local_path':str(p),'name':p.name,
                       'bytes':st.st_size,'mtime':int(st.st_mtime*1000),'type':row.get('type') or _kind(p)})
    return result


def _cached(asset):
    return next((r['path'] for r in _local_rows() if r.get('uuid') == asset), None)


@router.get('/status')
def status():
    settings, key = _settings(), _api_key()
    ffmpeg = bool(shutil.which('ffmpeg'))
    out = {'configured':bool(key),'key_env':KEY_ENV,'settings':settings,'balance':None,
           'host':{'ffmpeg':ffmpeg,'conversions':sorted(CONVERSIONS) if ffmpeg else []}}
    if key:
        try:
            with client_module.StudioTwinClient(settings['api_base_url'],key) as client:
                out['balance'] = client.call('studiotwin_get_credit_balance').get('balance')
        except HTTPException as exc:
            out['error'] = exc.detail
    return out


@router.get('/assets')
def assets(type: str = '', limit: int | None = Query(None,ge=1,le=100)):
    if type and type not in TYPES:
        raise HTTPException(400,'unsupported asset type')
    limit = limit or _settings()['gallery_limit']
    local = _local_rows()
    cloud = _call('studiotwin_list_my_assets',{'type':type} if type else {}).get('assets',[]) if _api_key() else []
    merged = {r['uuid']:dict(r) for r in cloud}
    for row in local:
        key = row.get('uuid') or row['path']
        merged[key] = {**merged.get(key,{}),**row}
    visible = []
    for row in merged.values():
        if type and (row.get('type') != type if type not in ('jpg','png') else not row.get('name','').lower().endswith('.'+type)):
            continue
        row['made_from'] = _provenance().details(row.get('uuid') or row.get('task') or '')['made_from']
        visible.append(row)
    return {'configured':bool(_api_key()),'assets':visible[:limit]}


@router.get('/assets/{uuid}')
def asset_detail(uuid: str):
    _id(uuid)
    row = _call('studiotwin_resolve_asset',{'assetId':uuid})
    return {**row,'local_path':_cached(uuid),'made_from':_provenance().details(uuid)['made_from']}


def _download_asset(aid):
    _id(aid)
    with store.STATE_LOCK:
        if cached := _cached(aid):
            return cached
        folder = sandbox.local_folder(_data_root(),'studio_cache')
        with _client() as client:
            row = client.call('studiotwin_resolve_asset',{'assetId':aid})
            ext = Path(row.get('name','')).suffix.lower()
            if ext not in sandbox.MIME:
                raise HTTPException(415,'unsupported asset extension')
            _, data = client.request('GET',row.get('downloadUrl',''),storage=True,cap=sandbox.MAX_BYTES)
        dest = folder / f'{aid}-{uuid.uuid4().hex}{ext}'
        with dest.open('xb') as out:
            out.write(data)
        _index().record(dest,asset=aid,kind=row.get('type'))
        return str(dest)


def _convert(data, fmt):
    ffmpeg = shutil.which('ffmpeg')
    if not ffmpeg:
        raise HTTPException(409,'ffmpeg is not installed on this host')
    folder = sandbox.local_folder(_data_root(),'conversions')
    fd, name = tempfile.mkstemp(suffix='.'+fmt,dir=folder)
    os.close(fd)
    try:
        result = subprocess.run([ffmpeg,'-nostdin','-hide_banner','-loglevel','error','-y',
            '-protocol_whitelist','pipe','-i','pipe:0','-vn',*CONVERSIONS[fmt],
            '-fs',str(sandbox.MAX_BYTES+1),name], input=data,capture_output=True,timeout=45,check=False)
        if result.returncode:
            raise HTTPException(502,'ffmpeg could not convert the audio')
        if Path(name).stat().st_size > sandbox.MAX_BYTES:
            raise HTTPException(413,'converted audio exceeds the media limit')
        return Path(name).read_bytes()
    except subprocess.TimeoutExpired:
        raise HTTPException(504,'audio conversion exceeded 45 seconds') from None
    except OSError:
        raise HTTPException(502,'audio conversion could not run') from None
    finally:
        Path(name).unlink(missing_ok=True)


@router.get('/file')
def file(request: Request, path: str = '', asset: str = '', task: str = '', format: str = 'original', raw: bool = False):
    if format not in ('original',*CONVERSIONS):
        raise HTTPException(400,'format must be original, mp3, wav, ogg or flac')
    if path:
        sandbox.readable(path,_allowed_roots())  # preflight BEFORE an asset lookup
    if asset:
        _id(asset)
    if task:
        _id(task)
    if bool(path) == bool(asset):
        raise HTTPException(400,'provide exactly one of path or asset')
    path = path or _download_asset(asset)
    with sandbox.open_media(path,_allowed_roots()) as (target,source,st):
        mime = sandbox.MIME[target.suffix.lower()]
        name = target.name
        size = st.st_size
        if format != 'original' and '.'+format != target.suffix.lower():
            if target.suffix.lower() not in AUDIO:
                raise HTTPException(415,'only audio can be converted')
            data = _convert(source.read(),format)
            source = io.BytesIO(data)
            name, size, mime = target.stem+'.'+format,len(data),sandbox.MIME['.'+format]
        _index().record(target,asset=asset or None,task=task or None)
        if raw or request.headers.get('range') is not None:
            return proxy.binary_response(source,size,mime,request.headers.get('range'))
        data = source.read()
        return {'name':name,'bytes':len(data),'mtime':int(st.st_mtime*1000),'mime':mime,
                'dataUrl':f'data:{mime};base64,'+base64.b64encode(data).decode('ascii')}


@router.get('/jobs')
def jobs(limit: int = Query(24,ge=1,le=100),offset: int = Query(0,ge=0)):
    return {'jobs':_call('studiotwin_list_my_jobs',{'limit':limit,'offset':offset})}


def _job(jid):
    _id(jid)
    row = _call('studiotwin_get_job_status',{'jobId':jid})
    state = str(row.get('status','')).lower()
    # No invented intermediate percentage: None explicitly means not reported.
    progress = row.get('progress',100 if state in ('done','complete','completed','succeeded') else None)
    return {**row,'id':jid,'progress':progress}


@router.get('/jobs/{job_id}')
def job(job_id: str):
    return _job(job_id)


@router.get('/task')
def task(id: str):
    return _job(id)


@router.get('/active')
def active(tasks: str = ''):
    wanted = list(dict.fromkeys(filter(None,tasks.split(','))))
    if len(wanted)>16:
        raise HTTPException(400,'at most 16 tasks')
    for jid in wanted:
        _id(jid)
    running,done,missing,failed = [],[],[],[]
    for jid in wanted:
        try:
            row = _job(jid)
        except HTTPException as exc:
            (missing if exc.status_code == 404 else failed).append(jid)
            continue
        if str(row.get('status','')).lower() in ('submitted','queued','running','pending','in_progress'):
            running.append(row)
        else:
            done.append(jid)
    return {'configured':bool(_api_key()),'tasks':running,'done':done,'missing':missing,'failed':failed}


@router.post('/jobs/{job_id}/cancel')
def cancel_job(job_id: str):
    return _call('studiotwin_cancel_job',{'jobId':_id(job_id)})


@router.post('/cancel')
def cancel(body: dict):
    return cancel_job(body.get('id') or body.get('jobId') or '')


@router.get('/concepts')
def concepts(limit: int = Query(24,ge=1,le=100),offset: int = Query(0,ge=0)):
    return _call('studiotwin_conceptlab_list',{'limit':limit,'offset':offset})


@router.get('/concepts/{concept_id}')
def concept(concept_id: str):
    return _call('studiotwin_conceptlab_get',{'conceptId':_id(concept_id)})


@router.get('/concepts/{concept_id}/status')
def concept_status(concept_id: str):
    return _call('studiotwin_conceptlab_get_status',{'conceptId':_id(concept_id)})


def _upload(filename, data, cloud, entries=None):
    if not isinstance(filename,str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._ -]{0,119}',filename) or '..' in filename:
        raise HTTPException(400,'filename must be a plain file name')
    ext = Path(filename).suffix.lower()
    if ext not in sandbox.MIME:
        raise HTTPException(415,'unsupported media extension')
    if not data or len(data)>sandbox.MAX_BYTES:
        raise HTTPException(413,'empty or oversized upload')
    if ext == '.tar' and cloud:
        import tarfile
        from pathlib import PurePosixPath
        try:
            with tarfile.open(fileobj=io.BytesIO(data), mode='r:') as archive:
                derived = []
                for member in archive:
                    name = PurePosixPath(member.name)
                    if (name.is_absolute() or '..' in name.parts or '\\' in member.name
                            or member.issym() or member.islnk() or member.size > sandbox.MAX_BYTES):
                        raise ValueError
                    if member.isfile():
                        derived.append({'name':member.name,'offset':member.offset,'size':member.size})
                    if len(derived)>10000:
                        raise ValueError
                if not derived or (entries is not None and entries != derived):
                    raise ValueError
                entries = derived
        except (tarfile.TarError,ValueError):
            raise HTTPException(400,'invalid or unsafe image-sequence archive') from None
    folder = sandbox.local_folder(_data_root(),'uploads')
    dest = folder / f'{uuid.uuid4().hex}-{filename}'
    with dest.open('xb') as out:
        out.write(data)
    _index().record(dest)
    result = {'path':str(dest),'name':filename,'bytes':len(data)}
    if not cloud:
        return result
    with _client() as client:
        upload = client.call('studiotwin_upload_asset')
        post = upload.get('preSignedPost',{})
        fields = post.get('fields',{})
        if not isinstance(fields,dict) or not all(isinstance(v,str) for v in fields.values()):
            raise HTTPException(502,'invalid StudioTwin upload session')
        fields = {k:v.replace('${filename}',filename) for k,v in fields.items()}
        client.request('POST',post.get('url',''),storage=True,data=fields,files={'file':(filename,data,sandbox.MIME[ext])})
        args = {'uploadSessionId':upload['uuid']}
        if entries is not None:
            args['entries'] = entries
        completed = client.call('studiotwin_complete_asset_upload',args)
    # Do not project the upload session: only final asset metadata is public.
    assets = completed.get('assets',[])
    if assets:
        _index().record(dest,asset=assets[0].get('uuid'),kind=assets[0].get('type'))
    return {**result,'uuid':completed.get('uuid'),'assetIds':completed.get('assetIds',[]),'assets':assets}


@router.post('/upload')
@router.post('/uploads')
async def upload(request: Request, cloud: bool = False):
    cap = sandbox.MAX_BYTES * 4 // 3 + 65536
    data = bytearray()
    async for chunk in request.stream():
        if len(data)+len(chunk)>cap:
            raise HTTPException(413,'upload body exceeds the media limit')
        data.extend(chunk)
    entries = None
    try:
        content_type = request.headers.get('content-type','')
        if content_type.startswith('multipart/form-data'):
            message = BytesParser(policy=email_policy).parsebytes(('Content-Type: '+content_type+'\r\nMIME-Version: 1.0\r\n\r\n').encode()+data)
            parts = [p for p in message.iter_parts() if p.get_filename() is not None]
            if len(parts)!=1:
                raise ValueError
            filename, payload = parts[0].get_filename(), parts[0].get_payload(decode=True)
        else:
            body = json.loads(data)
            filename,payload = body['filename'],base64.b64decode(body['data'],validate=True)
            cloud = cloud or body.get('cloud') is True
            entries = body.get('entries')
    except (ValueError,KeyError,TypeError):
        raise HTTPException(400,'no file in the request (or invalid file encoding)') from None
    return await run_in_threadpool(_upload,filename,payload,cloud or request.url.path.endswith('/uploads'),entries)


@router.post('/provenance')
def provenance(body: dict):
    identifier = _id(body.get('id') or body.get('jobId') or body.get('task_id') or '')
    record = {}
    for key in ('sourceAssetIds','outputAssetIds'):
        if key in body:
            if not isinstance(body[key],list) or len(body[key])>100:
                raise HTTPException(400,'asset ids must be a list of up to 100 UUIDs')
            record[key] = list(dict.fromkeys(_id(a) for a in body[key]))
    for key in ('conceptId','jobId'):
        if key in body:
            record[key] = _id(body[key])
    for key in ('prompt','tool','session_id'):
        if key in body:
            if not isinstance(body[key],str) or len(body[key])>8000:
                raise HTTPException(400,'invalid provenance text')
            record[key] = body[key]
    _provenance().record(identifier,record)
    return {'ok':True,'id':identifier}


@router.get('/provenance')
@router.get('/details')
def details(id: str):
    return _provenance().details(_id(id))


# Follow-up buttons only compose visible messages; this route never submits a job.
# Prices are fixed values from the captured definitions. Input-dependent tools
# require a fresh estimate in the composed instruction, not a fabricated quote.
ACTION_TABLE = {
    'image':[('mesh','Create 3D mesh','image-to-3d-mesh',25)],
    '3d_model':[('retopo','Retopologize','tripo-retopology',None),('rig','Auto-rig','blender-auto-rig',15)],
    'animation':[('motion','Generate motion','text-to-motion',None)],
    'environment':[('world','Build world','environment-map-to-world',80),('upscale','Upscale','environment-map-upscale-cpu',None)],
    'texture':[('material','Create PBR material','texture-to-material',20)],
    'audio':[], 'video':[], 'image_sequence':[]}


@router.get('/actions')
def actions(id: str, type: str = ''):
    _id(id)
    if not type or type == 'job':
        row = None
        if not type:
            try:
                row = _call('studiotwin_resolve_asset',{'assetId':id})
            except HTTPException as exc:
                if exc.status_code != 404:
                    raise
        if row is not None:
            type = 'environment' if Path(row.get('name','')).suffix.lower() in ('.hdr','.exr') else row.get('type','unknown')
        else:
            row = _job(id)
            if str(row.get('status','')).lower() not in ('done','complete','completed','succeeded'):
                return {'id':id,'type':'job','actions':[]}
            outputs = row.get('outputs') or {}
            type = next((kind for keys,kind in [
                (('environmentHDR','panoramaHDR'),'environment'), (('mesh','worldMesh'),'3d_model'),
                (('imageUrl',),'image'), (('audioClip',),'audio')]
                if any(key in outputs for key in keys)), 'unknown')
    if type not in ACTION_TABLE:
        return {'id':id,'type':type,'actions':[]}
    out = []
    for aid,label,tool,cost in ACTION_TABLE[type]:
        price = f'{cost} credits' if cost is not None else 'input-dependent credits; estimate first'
        out.append({'id':aid,'label':label,'tool':tool,'cost':cost,'cost_label':price,
            'message':f'StudioTwin asset {id}: {label} using {tool} ({price}). '
                       'Read the live tool schema, check compatibility, estimate the exact inputs with '
                       'studiotwin_estimate_cost, and ask me to approve the cost before submitting.'})
    return {'id':id,'type':type,'actions':out}
