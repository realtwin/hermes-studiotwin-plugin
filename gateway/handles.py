"""S07 volatile capability table. Tokens contain 256 random bits, no identity.

Only trusted gateway code owns this table. Upstream targets remain in memory,
never SQLite/logs/repr. Restart intentionally expires all capabilities. Current
scope/generation must come from authenticated S04/S05 context, not tool JSON.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
import hashlib
import math
import re
import secrets
from threading import RLock
import time
from types import MappingProxyType

from .mediation_parse import BoundaryRefused, bounded_copy_v1
from .redaction import _binding


class HandleNotFound(ValueError):
    def __init__(self):
        super().__init__('Handle not found.')


def _freeze(value):
    if type(value) is dict:
        return MappingProxyType({k:_freeze(v) for k,v in value.items()})
    if type(value) is list:
        return tuple(_freeze(v) for v in value)
    return value


@dataclass(frozen=True, slots=True, repr=False)
class HandleRecord:
    scope_id: str
    generation: int
    purpose: str
    kind: str
    role: str
    mime: str
    size: int | None
    expires_at: float
    operations: frozenset[str]
    target: Mapping = field(repr=False)

    def __repr__(self):
        return '<HandleRecord>'


class HandleStore:
    """Bounded process-local store keyed by token digest, with atomic read budget."""
    def __init__(self, *, clock=time.time, capacity=4096):
        if type(capacity) is not int or not 1 <= capacity <= 100000:
            raise BoundaryRefused()
        self._clock = clock
        self._capacity = capacity
        self._rows = {}
        self._generations = {}
        self._lock = RLock()

    def __repr__(self):
        return '<HandleStore>'

    def bind(self, scope_id, generation):
        _binding(scope_id, generation)
        with self._lock:
            current = self._generations.setdefault(scope_id, generation)
            if current != generation:
                raise HandleNotFound()

    def mint(self, *, scope_id, generation, purpose, kind, role, mime, size,
             target, ttl=300, max_reads=64, operations=('read',), expires_at=None):
        self.bind(scope_id, generation)
        allowed = {'resource':{'read','process'}, 'transfer':{'read'}, 'upload':{'put','complete'}}
        if (purpose not in allowed or type(kind) is not str or
                kind not in {'image','audio','video','model','environment','motion','material','manifest','other'} or
                type(role) is not str or not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', role) or
                type(mime) is not str or not re.fullmatch(r'(image|audio|video|model|application|text)/[a-z0-9][a-z0-9.+-]{0,63}', mime) or
                (size is not None and (type(size) is not int or not 0 <= size <= 2147483648)) or
                type(ttl) not in (int,float) or not math.isfinite(ttl) or not 0 < ttl <= 2592000 or
                type(max_reads) is not int or not 1 <= max_reads <= 1000000 or
                type(operations) not in (tuple,list,frozenset) or not operations or
                any(type(op) is not str or op not in allowed[purpose] for op in operations)):
            raise BoundaryRefused()
        data = bounded_copy_v1(target)
        if type(data) is not dict:
            raise BoundaryRefused()
        with self._lock:
            now = self._clock()
            deadline = now + ttl
            if expires_at is not None:
                if type(expires_at) not in (int,float) or not math.isfinite(expires_at) or expires_at <= now:
                    raise BoundaryRefused()
                deadline = min(deadline, expires_at)
            self.expire()
            if len(self._rows) >= self._capacity:
                raise BoundaryRefused()
            self.bind(scope_id, generation)
            token = 'sth_' + secrets.token_urlsafe(32)
            digest = hashlib.sha256(token.encode('ascii')).digest()
            while digest in self._rows:
                token = 'sth_' + secrets.token_urlsafe(32)
                digest = hashlib.sha256(token.encode('ascii')).digest()
            row = HandleRecord(scope_id,generation,purpose,kind,role,mime,size,deadline,
                               frozenset(operations),_freeze(data))
            self._rows[digest] = [row,max_reads]
            return token

    def resolve(self, token, *, scope_id, generation, purpose, operation, consume=True):
        self.bind(scope_id, generation)
        if type(token) is not str or not re.fullmatch(r'sth_[A-Za-z0-9_-]{43}', token):
            raise HandleNotFound()
        with self._lock:
            self.bind(scope_id, generation)
            digest = hashlib.sha256(token.encode('ascii')).digest()
            entry = self._rows.get(digest)
            if entry is None:
                raise HandleNotFound()
            row, remaining = entry
            if row.expires_at <= self._clock() or remaining <= 0:
                del self._rows[digest]
                raise HandleNotFound()
            if (row.scope_id != scope_id or row.generation != generation or
                    row.purpose != purpose or operation not in row.operations):
                raise HandleNotFound()
            if consume:
                entry[1] -= 1
            return row

    def expire(self):
        with self._lock:
            now = self._clock()
            for key, (row, remaining) in list(self._rows.items()):
                if row.expires_at <= now or remaining <= 0:
                    del self._rows[key]

    def revoke(self, token):
        if type(token) is str:
            with self._lock:
                self._rows.pop(hashlib.sha256(token.encode()).digest(), None)

    def invalidate_target(self, scope_id, path):
        with self._lock:
            for key, (row, _) in list(self._rows.items()):
                if row.scope_id == scope_id and row.target.get('localPath') == path:
                    del self._rows[key]

    def purge_scope(self, scope_id):
        _binding(scope_id, 0)
        with self._lock:
            for key, (row, _) in list(self._rows.items()):
                if row.scope_id == scope_id:
                    del self._rows[key]

    def rotate(self, scope_id, generation):
        _binding(scope_id, generation)
        with self._lock:
            current = self._generations.get(scope_id, -1)
            if generation <= current:
                raise HandleNotFound()
            self.purge_scope(scope_id)
            self._generations[scope_id] = generation
