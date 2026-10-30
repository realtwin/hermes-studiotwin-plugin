"""S11 typed offline metadata; no credential or authority persistence.

The caller supplies an authenticated live binding, not browser scope fields.
Tables have an S11 prefix to coexist with S09's money ledger. Purging this
cache never touches reservations, authorizations or settlement evidence.
"""
from __future__ import annotations

from contextlib import contextmanager
import importlib
import json
import math
import time

from .ipc_client import ipc, redaction
startup = importlib.import_module(ipc.__package__ + '.startup')
RETENTION = 30 * 86400
CONTRACT = 'studiotwin.dashboard.v1'
SCHEMAS = {'asset':'AssetV1', 'job':'JobV1', 'lineage':'LineageV1',
           'status':'StatusV1', 'capabilities':'CapabilitiesV1', 'pause':'ScopePauseV1',
           'provenance':'ProvenanceRecordRequestV1'}


class DashboardStore:
    def __init__(self, data, *, current_binding, sensitive_values, clock=time.time, windows=None):
        self._current, self._sensitive, self.clock = current_binding, sensitive_values, clock
        self.connection = startup.open_database(data, windows=windows)
        try:
            with self.connection:
                self.connection.execute('PRAGMA secure_delete=ON')
                self.connection.execute('CREATE TABLE IF NOT EXISTS s11_migrations(scope_id TEXT PRIMARY KEY, version INTEGER NOT NULL)')
                self.connection.execute('INSERT OR IGNORE INTO s11_migrations VALUES (?,1)', ('0'*64,))
                if self.connection.execute('SELECT version FROM s11_migrations').fetchall() != [(1,)]:
                    raise redaction.BoundaryRefused()
                self.connection.execute('CREATE TABLE IF NOT EXISTS s11_binding(scope_id TEXT PRIMARY KEY, generation INTEGER NOT NULL)')
                self.connection.execute('CREATE TABLE IF NOT EXISTS s11_epochs(scope_id TEXT PRIMARY KEY, generation INTEGER NOT NULL)')
                self.connection.execute('CREATE TABLE IF NOT EXISTS s11_metadata(scope_id TEXT, generation INTEGER, kind TEXT, id TEXT, value TEXT NOT NULL, seen REAL NOT NULL, PRIMARY KEY(scope_id,generation,kind,id))')
                self.connection.execute('CREATE TABLE IF NOT EXISTS s11_provenance(scope_id TEXT, generation INTEGER, parent TEXT, child TEXT, relation TEXT, parent_kind TEXT, child_kind TEXT, source TEXT, concept_id TEXT NOT NULL, seen REAL NOT NULL, PRIMARY KEY(scope_id,generation,parent,child,relation,source,concept_id))')
                self.connection.execute('CREATE INDEX IF NOT EXISTS s11_edges_parent ON s11_provenance(scope_id,generation,parent)')
                self.connection.execute('CREATE INDEX IF NOT EXISTS s11_edges_child ON s11_provenance(scope_id,generation,child)')
        except Exception:
            self.connection.close()
            raise redaction.BoundaryRefused() from None

    def __repr__(self):
        return '<DashboardStore>'

    def close(self):
        self.connection.close()

    def now(self):
        value = self.clock()
        if type(value) not in (int,float) or not math.isfinite(value) or value < 0:
            raise redaction.BoundaryRefused()
        return value

    def validate(self, schema, value, scope_id, generation):
        ref = ('gateway#/$defs/' if schema == 'ScopePauseV1' else 'dashboard#/components/schemas/') + schema
        return redaction.validate_mediated_v1(ref,value,scope_id=scope_id,
            generation=generation,sensitive_values=tuple(self._sensitive()))

    def require_current(self, scope_id, generation):
        redaction._binding(scope_id,generation)
        if self._current() != (scope_id,generation) or self.connection.execute(
                'SELECT scope_id,generation FROM s11_binding').fetchall() != [(scope_id,generation)]:
            raise redaction.BoundaryRefused()

    @contextmanager
    def transaction(self, scope_id, generation):
        failed = False
        try:
            self.connection.execute('BEGIN IMMEDIATE')
            self.require_current(scope_id,generation)
            yield
            self.require_current(scope_id,generation)
            self.connection.commit()
        except Exception:
            self.connection.rollback()
            failed = True
        if failed:
            raise redaction.BoundaryRefused()

    def activate(self, scope_id, generation):
        """Lifecycle hook only, after fresh backend identity/generation proof."""
        failed = False
        try:
            redaction._binding(scope_id,generation)
            with self.connection:
                self.connection.execute('BEGIN IMMEDIATE')
                if self._current() != (scope_id,generation):
                    raise redaction.BoundaryRefused()
                old = self.connection.execute('SELECT generation FROM s11_epochs WHERE scope_id=?',(scope_id,)).fetchone()
                active = self.connection.execute('SELECT scope_id,generation FROM s11_binding').fetchall()
                if old and (generation < old[0] or (generation == old[0] and active != [(scope_id,generation)])):
                    raise redaction.BoundaryRefused()
                self.connection.execute('INSERT OR REPLACE INTO s11_epochs VALUES (?,?)',(scope_id,generation))
                self.connection.execute('DELETE FROM s11_binding')
                self.connection.execute('INSERT INTO s11_binding VALUES (?,?)',(scope_id,generation))
                for table in ('s11_metadata','s11_provenance'):
                    self.connection.execute(f'DELETE FROM {table} WHERE seen<=?',(self.now()-RETENTION,))
        except Exception:
            failed = True
        if failed:
            raise redaction.BoundaryRefused()

    def _key(self, kind, identifier, scope_id, generation):
        if kind not in SCHEMAS:
            raise redaction.BoundaryRefused()
        self.validate('LocalIdV1',identifier,scope_id,generation)

    def _put_in_transaction(self, kind, identifier, value, scope_id, generation):
        """Private composition primitive; caller holds the checked transaction."""
        self._key(kind,identifier,scope_id,generation)
        safe = self.validate(SCHEMAS[kind],value,scope_id,generation)
        self.connection.execute('INSERT OR REPLACE INTO s11_metadata VALUES (?,?,?,?,?,?)',
            (scope_id,generation,kind,identifier,json.dumps(safe.to_json(),allow_nan=False),self.now()))
        return safe

    def put(self, kind, identifier, value, *, scope_id, generation):
        # Validate before even BEGIN: rejected candidates never reach a sink.
        self._key(kind,identifier,scope_id,generation)
        self.validate(SCHEMAS[kind],value,scope_id,generation)
        with self.transaction(scope_id,generation):
            return self._put_in_transaction(kind,identifier,value,scope_id,generation)

    def get(self, kind, identifier, *, scope_id, generation):
        self._key(kind,identifier,scope_id,generation)
        with self.transaction(scope_id,generation):
            row = self.connection.execute('SELECT value FROM s11_metadata WHERE scope_id=? AND generation=? AND kind=? AND id=? AND seen>?',
                (scope_id,generation,kind,identifier,self.now()-RETENTION)).fetchone()
            return None if row is None else self.validate(SCHEMAS[kind],ipc.decode(row[0].encode()),scope_id,generation)

    def pause(self, *, scope_id, generation):
        return self.get('pause','current',scope_id=scope_id,generation=generation)

    def _stats(self, scope_id, generation):
        return {key:self.connection.execute(f'SELECT COUNT(*) FROM {table} WHERE scope_id=? AND generation=? AND seen>?',
                (scope_id,generation,self.now()-RETENTION)).fetchone()[0]
                for key,table in (('metadata','s11_metadata'),('provenance','s11_provenance'))}

    def stats(self, *, scope_id, generation):
        with self.transaction(scope_id,generation):
            return self._stats(scope_id,generation)

    def purge(self, *, scope_id, generation):
        """User cache purge, not financial-history erasure; all scope generations."""
        with self.transaction(scope_id,generation):
            counts = self._stats(scope_id,generation)
            for table in ('s11_metadata','s11_provenance'):
                self.connection.execute(f'DELETE FROM {table} WHERE scope_id=?',(scope_id,))
            return counts
