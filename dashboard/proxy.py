"""S11 local, bounded streaming proxy. No URL resolver or network client.

Gateway-owned downloads must be materialized in S07 MediaCache first. Refusing
URL targets here is intentional: Desktop never opens a second hosted channel.
The caller supplies authenticated scope and session identity, never query IDs.
"""
from __future__ import annotations

import os
from pathlib import Path
import re
from threading import RLock
import time
from .ipc_client import redaction
from .sandbox import media_cache

CHUNK = 65536
# Only passive binary formats; JSON manifests/glTF require a mediated processor.
MIMES = frozenset(m for ext,values in media_cache._FORMATS.items() for m in values
                  if ext not in ('.json','.gltf'))


class ProxyRefused(ValueError):
    def __init__(self, status=404, *, size=None):
        super().__init__('Media unavailable.')
        self.status = status
        self.headers = {'Accept-Ranges':'bytes','X-Content-Type-Options':'nosniff'}
        if status == 416 and type(size) is int:
            self.headers['Content-Range'] = f'bytes */{size}'
        if status == 429:
            self.headers['Retry-After'] = '1'


class SessionLimits:
    """Bounded token buckets and active slots keyed by trusted session/binding."""
    def __init__(self, *, clock=time.monotonic, rate=20, burst=40, capacity=128):
        self.clock, self.rate, self.burst, self.capacity = clock,rate,burst,capacity
        self.rows = {}
        self.lock = RLock()

    def _row(self, key):
        now = self.clock()
        if key not in self.rows:
            # Do not evict a busy/burst-exhausted row to reset its budget.
            for k,(tokens,stamp,active) in list(self.rows.items()):
                if not any(active.values()) and now-stamp >= 60:
                    del self.rows[k]
            if len(self.rows)>=self.capacity: raise ProxyRefused(429)
            self.rows[key] = [float(self.burst),now,{}]
        row = self.rows[key]
        row[0] = min(self.burst,row[0]+max(0,now-row[1])*self.rate)
        row[1] = now
        return row

    def request(self, key):
        with self.lock:
            row = self._row(key)
            if row[0]<1: raise ProxyRefused(429)
            row[0] -= 1

    def acquire(self, key, kind='stream', maximum=2):
        with self.lock:
            row = self._row(key)
            if row[2].get(kind,0)>=maximum: raise ProxyRefused(429)
            row[2][kind] = row[2].get(kind,0)+1

    def release(self, key, kind='stream'):
        with self.lock:
            row = self.rows.get(key)
            if row: row[2][kind] = max(0,row[2].get(kind,0)-1)


def byte_range(header, size):
    if header is None: return 0,size-1,200
    if type(header) is not str or len(header)>96:
        raise ProxyRefused(416,size=size)
    match = re.fullmatch(r'bytes=([0-9]*)-([0-9]*)',header)
    if match is None or not any(match.groups()): raise ProxyRefused(416,size=size)
    first,last = match.groups()
    if not first:
        suffix = int(last)
        if suffix<=0: raise ProxyRefused(416,size=size)
        start,end = max(0,size-suffix),size-1
    else:
        start,end = int(first),int(last) if last else size-1
    if start>=size or end<start or size<=0: raise ProxyRefused(416,size=size)
    return start,min(end,size-1),206


class _AdmittedHandles:
    """S11 adapter for S07's consume-on-admission API, shared per store.

    Exhausted rows can disappear on resolve/expire/mint without revoking an
    admitted read. Observe explicit invalidations separately, even after that
    removal. Only active leases are retained; no token tombstones accumulate.
    All hooks, admission and lease checks serialize on the existing store lock.
    """
    def __init__(self, handles):
        self.handles, self.active = handles, set()
        revoke, invalidate, purge = handles.revoke, handles.invalidate_target, handles.purge_scope

        def revoke_active(token):
            with handles._lock:
                revoke(token)
                for lease in self.active:
                    if lease.handle == token: lease.revoked = True

        def invalidate_active(scope_id, path):
            with handles._lock:
                invalidate(scope_id, path)
                for lease in self.active:
                    if lease.row.scope_id == scope_id and lease.row.target.get('localPath') == path:
                        lease.revoked = True

        def purge_active(scope_id):
            with handles._lock:
                purge(scope_id)
                for lease in self.active:
                    if lease.row.scope_id == scope_id: lease.revoked = True

        handles.revoke = revoke_active
        handles.invalidate_target = invalidate_active
        # S07 rotate invokes this hook under the same reentrant lock.
        handles.purge_scope = purge_active

    def check(self, lease):
        with self.handles._lock:
            self.handles.bind(*lease.binding)
            if lease.revoked or lease.row.expires_at <= self.handles._clock():
                raise ProxyRefused()


class StreamLease:
    def __init__(self, proxy, stream, key, binding, handle, start, end, status, mime, size, row=None):
        self.proxy, self.stream, self.key, self.binding, self.handle = proxy,stream,key,binding,handle
        self.start,self.end,self.status,self.closed = start,end,status,False
        self.row, self.revoked = row, False
        self.headers = {'Content-Type':mime,'Content-Length':str(end-start+1),
            'Accept-Ranges':'bytes','X-Content-Type-Options':'nosniff',
            'Cache-Control':'no-store','Content-Disposition':'inline'}
        if status==206: self.headers['Content-Range'] = f'bytes {start}-{end}/{size}'

    def close(self):
        if not self.closed:
            self.closed = True
            try: self.stream.close()
            finally:
                with self.proxy.handles._lock:
                    self.proxy._admitted.active.discard(self)
                self.proxy.limits.release(self.key)

    def check(self):
        self.proxy.check(*self.binding)
        if self.handle: self.proxy._admitted.check(self)

    def chunks(self):
        try:
            self.stream.seek(self.start)
            remaining = self.end-self.start+1
            while remaining and not self.closed:
                self.check()
                data = self.stream.read(min(CHUNK,remaining))
                if not data: break
                self.check()
                remaining -= len(data)
                yield data
        except Exception:
            # A midstream failure terminates; never append diagnostics to bytes.
            pass
        finally:
            self.close()


class MediaProxy:
    def __init__(self, handles, cache, sandbox, *, current_binding, sensitive_values, limits=None):
        self.handles,self.cache,self.sandbox = handles,cache,sandbox
        self._current,self._sensitive = current_binding,sensitive_values
        self.limits = limits or SessionLimits()
        with handles._lock:
            if not hasattr(handles, '_s11_admitted'):
                handles._s11_admitted = _AdmittedHandles(handles)
            self._admitted = handles._s11_admitted

    @property
    def active_streams(self):
        with self.limits.lock:
            return sum(r[2].get('stream',0) for r in self.limits.rows.values())

    def check(self, scope_id, generation):
        redaction._binding(scope_id,generation)
        if self._current() != (scope_id,generation): raise ProxyRefused()

    def prepare(self, *, scope_id, generation, session, path=None, handle=None, range_header=None):
        failed,stream,acquired,status,size,row = False,None,False,404,None,None
        key = (scope_id,generation,session)
        try:
            self.check(scope_id,generation)
            redaction.validate_mediated_v1('dashboard#/components/schemas/LocalIdV1',session,
                scope_id=scope_id,generation=generation,sensitive_values=tuple(self._sensitive()))
            self.limits.request(key)
            self.limits.acquire(key); acquired = True
            if (path is None)==(handle is None): raise ProxyRefused(400)
            if handle is not None:
                row = self.handles.resolve(handle,scope_id=scope_id,generation=generation,purpose='resource',operation='read',consume=False)
                descriptor = dict(handle=handle,mime=row.mime,bytes=row.size,assetId=None)
                redaction.validate_mediated_v1('host_gateway#/$defs/IpcStreamDescriptorV1',descriptor,
                    scope_id=scope_id,generation=generation,sensitive_values=tuple(self._sensitive()))
                if set(row.target) != {'localPath'}: raise ProxyRefused()
                path,mime,kind = row.target['localPath'],row.mime,row.kind
            else:
                extension = Path(path).suffix.lower()
                values = media_cache._FORMATS.get(extension,())
                if not values: raise ProxyRefused(415)
                mime = sorted(values)[0]
                kind = {'model':'model','audio':'audio','video':'video','image':'image'}.get(mime.split('/')[0],'other')
            if mime not in MIMES: raise ProxyRefused(415)
            if Path(path).is_relative_to(self.cache.root):
                stream = self.cache.open(path,scope_id=scope_id,generation=generation,mime=mime,kind=kind)
            elif handle is None:
                stream = self.sandbox.open(path,mime=mime,kind=kind)
            else:
                raise ProxyRefused()
            size = os.fstat(stream.fileno()).st_size
            if handle is not None and row.size is not None and row.size != size: raise ProxyRefused()
            start,end,status = byte_range(range_header,size)
            self.check(scope_id,generation)
            with self.handles._lock:
                if handle is not None:
                    # Re-resolve after opening and Range validation. Revocation or
                    # another admission while opening must still fail closed.
                    admitted = self.handles.resolve(handle,scope_id=scope_id,generation=generation,purpose='resource',operation='read')
                    if admitted is not row: raise ProxyRefused()
                lease = StreamLease(self,stream,key,(scope_id,generation),handle,start,end,status,mime,size,
                                    row if handle is not None else None)
                if handle is not None: self._admitted.active.add(lease)
                return lease
        except ProxyRefused as e:
            failed,status = True,e.status
        except Exception:
            failed = True
        finally:
            if failed:
                if stream is not None: stream.close()
                if acquired: self.limits.release(key)
        raise ProxyRefused(status,size=size)
