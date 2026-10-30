"""Private durable policy ledger (S09), never a browser approval API.

Each instance owns one S05 private SQLite connection, used on its creating
thread. Independent workers/processes open independent instances. All policy
writes use BEGIN IMMEDIATE; the final check/consume/reserve shares a transaction.
No keys, locations, raw inputs, principal identifiers or upstream bodies persist.
S10 owns dispatch/reconciliation and verified evidence issuance, not this store.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import hmac
import json
import re
import sqlite3

from .startup import open_database
from .mediation_parse import BoundaryRefused, bounded_copy_v1
from . import redaction as R

_PROTOCOL = 'studiotwin.gateway.v1'
_BINDING = frozenset(('scope_id','generation','session_id','turn_id','tool_call_id','tool',
                      'schema_hash','canonical_input_hash'))


def _json(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False)


def mediated(kind, value, scope, generation, sensitive_values=()):
    prefix = 'dashboard#/components/schemas/' if kind == 'QuotePreviewV1' else 'gateway#/$defs/'
    return R.validate_mediated_v1(prefix+kind, value, scope_id=scope, generation=generation,
                                   sensitive_values=sensitive_values)


def _checked_binding(binding, sensitive_values=()):
    failed = False
    result = None
    try:
        result = bounded_copy_v1(binding)
        if type(result) is not dict or set(result) != _BINDING:
            raise BoundaryRefused()
        R._binding(result['scope_id'],result['generation'])
        for field in ('session_id','turn_id','tool_call_id'):
            R._schema_validate('gateway#/$defs/TrustedIdV1',result[field])
        R._schema_validate('gateway#/$defs/ToolNameV1',result['tool'])
        for field in ('schema_hash','canonical_input_hash'):
            R._schema_validate('gateway#/$defs/Sha256HexV1',result[field])
        R._walk(result,R._Sensitive(sensitive_values),redact=False,scope_id=result['scope_id'])
    except (ValueError,TypeError,KeyError):
        failed = True
    if failed:
        raise BoundaryRefused()
    return result


def check_preview(preview, binding, now_ms, sensitive_values=()):
    binding = _checked_binding(binding,sensitive_values)
    p = mediated('QuotePreviewV1',preview,binding['scope_id'],binding['generation'],sensitive_values).to_json()
    observed, expires = p.get('observedAtMs'), p['previewExpiresAtMs']
    if (p['tool'] != binding['tool'] or p['authorizes'] is not False or not p['executable'] or
            p['disabledReason'] is not None or p['previewId'] is None or p['estimatedCredits'] is None or
            p['scopePaused'] or type(observed) is not int or type(expires) is not int or
            not observed <= now_ms < expires):
        raise BoundaryRefused()
    return p


def check_authorization(auth, preview, binding, now_ms, sensitive_values=()):
    a = mediated('AuthorizationV1',auth,binding['scope_id'],binding['generation'],sensitive_values).to_json()
    p = check_preview(preview,binding,now_ms,sensitive_values)
    for key, expected in dict(scopeId=binding['scope_id'],trustedSessionId=binding['session_id'],
                              runId=binding['session_id'],tool=binding['tool'],schemaHash=binding['schema_hash'],
                              canonicalInputHash=binding['canonical_input_hash'],enforcementMode=p['enforcementMode'],
                              previewId=p['previewId'],estimatedCredits=p['estimatedCredits'],
                              previewExpiresAtMs=p['previewExpiresAtMs']).items():
        if a[key] != expected:
            raise BoundaryRefused()
    if not p['observedAtMs'] <= a['createdAtMs'] <= now_ms < a['expiresAtMs'] <= p['previewExpiresAtMs']:
        raise BoundaryRefused()
    expected = p['estimatedCredits'] if p['enforcementMode']=='interim-local' else p['maxCredits']
    if a['maxCredits'] != expected:
        raise BoundaryRefused()
    return a


class PolicyStore:
    def __init__(self, data, *, windows=None, sensitive_values=()):
        self._db = open_database(data, windows=windows)
        self._sensitive = sensitive_values
        self._db.execute('PRAGMA busy_timeout=10000')
        self._db.execute('PRAGMA foreign_keys=ON')
        with self.transaction():
            # Scope comes first even in the one active-connection slot. Epoch is
            # global to this connection, so A->B->A never resurrects generation A.
            for statement in (
                'CREATE TABLE IF NOT EXISTS policy_active(scope_id TEXT PRIMARY KEY, slot INTEGER NOT NULL CHECK(slot=1), generation INTEGER NOT NULL, identity_hash TEXT NOT NULL)',
                'CREATE TABLE IF NOT EXISTS policy_assets(scope_id TEXT NOT NULL, generation INTEGER NOT NULL, asset_id TEXT NOT NULL, PRIMARY KEY(scope_id,generation,asset_id))',
                'CREATE TABLE IF NOT EXISTS policy_quotes(scope_id TEXT NOT NULL, generation INTEGER NOT NULL, preview_id TEXT NOT NULL, binding_json TEXT NOT NULL, preview_json TEXT NOT NULL, price_version TEXT, server_token TEXT, consumed_by TEXT, PRIMARY KEY(scope_id,generation,preview_id))',
                'CREATE TABLE IF NOT EXISTS policy_operations(scope_id TEXT NOT NULL, generation INTEGER NOT NULL, operation_id TEXT NOT NULL, session_id TEXT NOT NULL, binding_json TEXT NOT NULL, authorization_json TEXT NOT NULL, state TEXT NOT NULL, reserved_credits INTEGER NOT NULL, final_debit INTEGER, refund INTEGER, PRIMARY KEY(scope_id,operation_id))',
                'CREATE TABLE IF NOT EXISTS policy_guards(scope_id TEXT NOT NULL, session_id TEXT NOT NULL, limit_credits INTEGER NOT NULL, PRIMARY KEY(scope_id,session_id))',
                'CREATE TABLE IF NOT EXISTS policy_pauses(scope_id TEXT PRIMARY KEY, generation INTEGER NOT NULL, pause_json TEXT NOT NULL)',
            ):
                self._db.execute(statement)

    def __repr__(self):
        return '<PolicyStore>'

    def close(self):
        self._db.close()

    @contextmanager
    def transaction(self):
        self._db.execute('BEGIN IMMEDIATE')
        try:
            yield
            self._db.commit()
        except BaseException:
            self._db.rollback()
            raise

    def require_current(self, scope_id, generation):
        R._binding(scope_id,generation)
        row = self._db.execute('SELECT scope_id,generation FROM policy_active WHERE slot=1').fetchone()
        if row != (scope_id,generation):
            raise BoundaryRefused()

    def activate_scope(self, scope_tuple, *, scope_key, credential_epoch, handles=None):
        """Trusted backend storage hook, not proof of the supplied principal.
        D24 issuer must authenticate this tuple BEFORE calling; S09 authorization
        independently requires that issuer. The keyed scope salt is backend-owned
        and stable; credential_epoch is a keyed digest, never an API key. Raw
        account/org/profile/endpoint values are not written to SQLite.
        """
        failed = False
        material = None
        try:
            value = bounded_copy_v1(scope_tuple)
            R._schema_validate('gateway#/$defs/ScopeTupleV1',value)
            if type(scope_key) is not bytes or len(scope_key) < 32:
                raise BoundaryRefused()
            R._binding(credential_epoch,0)
            registry = R._Sensitive(self._sensitive)
            if any(registry.unsafe(v,secrets_only=True) for v in value.values()):
                raise BoundaryRefused()
            material = _json(value).encode()
        except (ValueError,TypeError,AttributeError):
            failed = True
        if failed:
            raise BoundaryRefused()
        scope = hmac.new(scope_key,b'studiotwin-scope-v1\0'+material,hashlib.sha256).hexdigest()
        identity = hmac.new(scope_key,b'studiotwin-generation-v1\0'+material+b'\0'+credential_epoch.encode(),hashlib.sha256).hexdigest()
        return scope,self.activate(scope,identity,handles=handles)

    def activate(self, scope_id, identity_hash, *, handles=None):
        """Backend rotation hook AFTER fresh identity proof. identity_hash must
        include the full D23 tuple and credential generation; never a raw key.
        This storage hook is not a principal issuer or hosted publication grant.
        Optional S07 store is invalidated synchronously; current generation is
        checked independently on every policy operation even after process death.
        """
        R._binding(scope_id,0)
        R._binding(identity_hash,0)
        with self.transaction():
            old = self._db.execute('SELECT scope_id,generation,identity_hash FROM policy_active WHERE slot=1').fetchone()
            if old and (old[0],old[2]) == (scope_id,identity_hash):
                return old[1]
            generation = old[1]+1 if old else 1
            if handles is not None:
                for scope in set([scope_id]+([old[0]] if old else [])):
                    handles.rotate(scope,generation)
            self._db.execute('DELETE FROM policy_quotes')
            # Old in-flight/unknown reservations remain held for reconciliation;
            # only unsent unconsumed approvals can be expired automatically.
            self._db.execute("UPDATE policy_operations SET state='EXPIRED' WHERE state='AUTHORIZED'")
            self._db.execute('DELETE FROM policy_active')
            self._db.execute('INSERT INTO policy_active VALUES (?,1,?,?)',(scope_id,generation,identity_hash))
            return generation

    def adopt_asset(self, scope_id, generation, asset_id):
        """Trusted backend inventory/adoption write, not model/browser consent.
        Retained old-generation ownership never becomes current by rotating back.
        """
        R._binding(scope_id,generation)
        R._schema_validate('gateway#/$defs/AssetIdV1',asset_id)
        with self.transaction():
            self._db.execute('INSERT OR IGNORE INTO policy_assets VALUES (?,?,?)',(scope_id,generation,asset_id))

    def owns_asset(self, scope_id, generation, asset_id):
        self.require_current(scope_id,generation)
        return self._db.execute('SELECT 1 FROM policy_assets WHERE scope_id=? AND generation=? AND asset_id=?',
                                 (scope_id,generation,asset_id)).fetchone() is not None

    def guard_key(self, scope_id, generation, session_id):
        self.require_current(scope_id,generation)
        return mediated('SpendGuardKeyV1',dict(scopeId=scope_id,trustedSessionId=session_id),
                        scope_id,generation,self._sensitive)

    def guard_limit(self, scope_id, session_id):
        row=self._db.execute('SELECT limit_credits FROM policy_guards WHERE scope_id=? AND session_id=?',
                             (scope_id,session_id)).fetchone()
        return row[0] if row else 200

    def set_guard_limit(self, scope_id, session_id, credits, *, explicit_user_setting=False):
        """Backend user-settings seam only. Automatic defaults can lower to <=200;
        increases beyond 200 require an explicit user-owned settings change.
        """
        R._binding(scope_id,0)
        mediated('SpendGuardKeyV1',dict(scopeId=scope_id,trustedSessionId=session_id),scope_id,0,self._sensitive)
        R._schema_validate('gateway#/$defs/CreditsV1',credits)
        with self.transaction():
            if credits > min(200,self.guard_limit(scope_id,session_id)) and explicit_user_setting is not True:
                raise BoundaryRefused()
            self._db.execute('INSERT OR REPLACE INTO policy_guards VALUES (?,?,?)',(scope_id,session_id,credits))

    def guard_used(self, scope_id, session_id):
        # Each operation contributes exactly once: held reservation OR verified
        # settled debit minus verified refund. Old generations are NOT spendable.
        row=self._db.execute("""SELECT COALESCE(SUM(CASE
            WHEN state IN ('RELEASED','EXPIRED','AUTHORIZED') THEN 0
            WHEN state IN ('SETTLED','SETTLED_OVERRUN','REFUNDED_VERIFIED') AND final_debit IS NOT NULL
                THEN MAX(0,final_debit-COALESCE(refund,0))
            ELSE reserved_credits END),0) FROM policy_operations WHERE scope_id=? AND session_id=?""",
            (scope_id,session_id)).fetchone()
        return row[0]

    def save_quote(self, preview, binding, *, price_version, server_token, clock_ms):
        """Backend clock callable is evaluated only after acquiring the write lock."""
        b=_checked_binding(binding,self._sensitive)
        # Schema/metadata validation is safe before locking; expiry is not.
        p=mediated('QuotePreviewV1',preview,b['scope_id'],b['generation'],self._sensitive).to_json()
        self.guard_key(b['scope_id'],b['generation'],b['session_id'])
        failed = False
        try:
            if price_version is not None:
                R._schema_validate('gateway#/$defs/TrustedIdV1',price_version)
                R._walk(price_version,R._Sensitive(self._sensitive),redact=False)
            if p['enforcementMode']=='server-max-credits':
                if type(server_token) is not str or not re.fullmatch(r'sqt_[A-Za-z0-9_-]{43}',server_token):
                    raise BoundaryRefused()
                R._walk(server_token,R._Sensitive(self._sensitive),redact=False)
            elif server_token is not None:
                raise BoundaryRefused()
        except (ValueError,TypeError):
            failed = True
        if failed:
            raise BoundaryRefused()
        # Validate price/token through the complete authorization schema at the
        # approval boundary; no server mode may be enabled from these labels.
        try:
            with self.transaction():
                p=check_preview(p,b,clock_ms(),self._sensitive)
                self.require_current(b['scope_id'],b['generation'])
                self._db.execute('INSERT INTO policy_quotes VALUES (?,?,?,?,?,?,?,NULL)',
                    (b['scope_id'],b['generation'],p['previewId'],_json(b),_json(p),price_version,server_token))
        except sqlite3.IntegrityError:
            raise BoundaryRefused() from None
        return p['previewId']

    def load_quote(self, preview_id, binding, *, now_ms):
        self.require_current(binding['scope_id'],binding['generation'])
        row=self._db.execute('SELECT binding_json,preview_json,price_version,server_token,consumed_by FROM policy_quotes WHERE scope_id=? AND generation=? AND preview_id=?',
            (binding['scope_id'],binding['generation'],preview_id)).fetchone()
        if row is None or json.loads(row[0]) != binding or row[4] is not None:
            raise BoundaryRefused()
        p=check_preview(json.loads(row[1]),binding,now_ms,self._sensitive)
        return p,row[2],row[3]

    def reserve(self, authorization, binding, *, clock_ms):
        """Internal S09 call after exact host consent; NOT a public approval API.
        Returns only a NEW reservation; duplicate/foreign use refuses and S10 can
        read existing state without ever treating it as permission to dispatch.
        clock_ms is a trusted backend callable, never a sampled pre-lock time.
        """
        with self.transaction():
            # BEGIN IMMEDIATE may wait behind another writer past either expiry.
            # Use one fresh post-lock sample for both preview and authorization.
            now_ms=clock_ms()
            self.require_current(binding['scope_id'],binding['generation'])
            p,price,token=self.load_quote(authorization['previewId'],binding,now_ms=now_ms)
            a=check_authorization(authorization,p,binding,now_ms,self._sensitive)
            if a['previewPriceVersion']!=price or a.get('serverQuoteToken')!=token:
                raise BoundaryRefused()
            if self._db.execute('SELECT 1 FROM policy_operations WHERE scope_id=? AND operation_id=?',
                                 (binding['scope_id'],a['operationId'])).fetchone():
                raise BoundaryRefused()
            pause=self.pause(binding['scope_id'],binding['generation'])
            if pause is not None and pause.value['acknowledgedAtMs'] is None:
                raise BoundaryRefused()
            self.guard_key(binding['scope_id'],binding['generation'],binding['session_id'])
            if self.guard_used(binding['scope_id'],binding['session_id'])+a['maxCredits'] > self.guard_limit(binding['scope_id'],binding['session_id']):
                raise BoundaryRefused()
            self._db.execute('INSERT INTO policy_operations VALUES (?,?,?,?,?,?,?,?,NULL,NULL)',
                (binding['scope_id'],binding['generation'],a['operationId'],binding['session_id'],
                 _json(binding),_json(a),'RESERVED_UNSENT',a['maxCredits']))
            self._db.execute('UPDATE policy_quotes SET consumed_by=? WHERE scope_id=? AND generation=? AND preview_id=?',
                (a['operationId'],binding['scope_id'],binding['generation'],a['previewId']))
        return mediated('AuthorizationV1',a,binding['scope_id'],binding['generation'],self._sensitive)

    def get_operation(self, operation_id, binding):
        self.require_current(binding['scope_id'],binding['generation'])
        row=self._db.execute('SELECT binding_json,state,reserved_credits,authorization_json FROM policy_operations WHERE scope_id=? AND generation=? AND operation_id=?',
            (binding['scope_id'],binding['generation'],operation_id)).fetchone()
        if row is None or json.loads(row[0]) != binding:
            raise BoundaryRefused()
        return dict(state=row[1],reservedCredits=row[2],authorization=json.loads(row[3]))

    def put_pause(self, pause, *, generation):
        """S10 backend seam, only after verified job-specific overrun evidence.
        This stores an already verified pause; it does not certify ledger evidence.
        """
        p=mediated('ScopePauseV1',pause,pause['scopeId'],generation,self._sensitive).to_json()
        if (p['actualCredits']<=p['estimatedCredits'] or
                (p['acknowledgedAtMs'] is not None and p['acknowledgedAtMs']<p['createdAtMs'])):
            raise BoundaryRefused()
        with self.transaction():
            self.require_current(p['scopeId'],generation)
            self._db.execute('INSERT OR REPLACE INTO policy_pauses VALUES (?,?,?)',(p['scopeId'],generation,_json(p)))

    def pause(self, scope_id, generation):
        self.require_current(scope_id,generation)
        row=self._db.execute('SELECT pause_json FROM policy_pauses WHERE scope_id=?',(scope_id,)).fetchone()
        return mediated('ScopePauseV1',json.loads(row[0]),scope_id,generation,self._sensitive) if row else None

    def operation_count(self):
        return self._db.execute('SELECT COUNT(*) FROM policy_operations').fetchone()[0]

    def quote_count(self):
        return self._db.execute('SELECT COUNT(*) FROM policy_quotes').fetchone()[0]
