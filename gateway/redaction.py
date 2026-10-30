"""S06 value-aware, all-channel secret boundary.

Two distinct operations: redact_upstream_v1 produces a VOLATILE intermediate,
never a tool/dashboard/IPC envelope. validate_mediated_v1 refuses rather than
silently repairing an outbound value. S07 alone creates scoped handles/media;
S08/S09 supply reviewed input schema bindings, canonical effective transforms
and authorization. No function here performs transport, logging or persistence.

Sensitive registries and candidate_schema_v1 are backend-owned call context,
not tool arguments. Do not store, log or expose either to the browser/model.
"""
from __future__ import annotations

import base64
from collections.abc import Collection, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
import hashlib
import html
import json
import re
from types import MappingProxyType
from urllib.parse import quote, unquote

from .mediation_parse import (BoundaryRefused, Budget, bounded_copy_v1,
                                     embedded_json_v1, decode_json_escapes_v1)

_REDACTED = '[redacted]'
_BANNED_NAME = re.compile(
    r'(url|uri|href|link|signature|signed|policy|credential|secret|password|passwd|'
    r'api[-_]?key|access[-_]?key|private[-_]?key|signing[-_]?key|mac[-_]?key|boot[-_]?cap|'
    r'authorization|bearer|cookie|presign|amz|token|bucket|storage)', re.I)
_UNSAFE_TEXT = re.compile(
    r'(STCANARY_|s3\s*:|X-Amz-|AKIA[0-9A-Z]{16}|ASIA[0-9A-Z]{16}|'
    r'Bearer\s+\S+|(?:x[-_])?api[-_]?key\s*["\s]*[:=]|'
    r'(?:password|passwd|secret|signature|policy|credential|security[-_]?token)\s*["\s]*[:=]|'
    r'https?://[^\s"<>]*[?&]|data:[^\s,]*[;,]|-----BEGIN [A-Z ]*PRIVATE KEY-----|'
    r'\bsk-[A-Za-z0-9_-]{16,}|\beyJ[A-Za-z0-9_-]+\.eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+)', re.I)
_URL = re.compile(r'[A-Za-z][A-Za-z0-9+.-]*://[^\s"<>]+')
_PATH = re.compile(r'(?:^|\s)(?:/[A-Za-z0-9_. -]+/|[A-Za-z]:[/\\])')
_B64 = re.compile(r'(?<![A-Za-z0-9_+/-])[A-Za-z0-9_+/-]{16,}={0,2}(?![A-Za-z0-9_+/-])')
_NAME_EXCEPTIONS = frozenset({'serverQuoteToken'})
_FACTORY = object()


def _freeze(value):
    if type(value) is dict:
        return MappingProxyType({k:_freeze(v) for k,v in value.items()})
    if type(value) is list:
        return tuple(_freeze(v) for v in value)
    return value


def _thaw(value):
    if isinstance(value, Mapping):
        return {k:_thaw(v) for k,v in value.items()}
    if type(value) is tuple:
        return [_thaw(v) for v in value]
    return value


@dataclass(frozen=True, slots=True, init=False, repr=False)
class MediatedValue:
    contract_ref: str
    scope_id: str
    generation: int
    value: object = field(repr=False)

    def __init__(self, *, _factory=None, contract_ref=None, scope_id=None, generation=None, value=None):
        if _factory is not _FACTORY:
            raise BoundaryRefused()
        for name, val in (('contract_ref',contract_ref), ('scope_id',scope_id),
                          ('generation',generation), ('value',_freeze(value))):
            object.__setattr__(self, name, val)

    def to_json(self):
        """Detached mutable JSON for the next validated sink; never shared internals."""
        return _thaw(self.value)

    def __repr__(self):
        return '<MediatedValue>'


@dataclass(frozen=True, slots=True, init=False, repr=False)
class ValidatedCandidateInputs:
    """Safety + exact supplied schema binding; NOT consent/dispatch authority.

    S08 owns its public classification facade and must bind this validator to
    reviewed current schemas, not caller-supplied schemas. S09 must supply the
    effective resource transforms before canonical hashing and billing.
    """
    tool: str
    schema_hash: str
    canonical_input_hash: str
    scope_id: str
    generation: int
    values: object = field(repr=False)

    def __init__(self, *, _factory=None, **fields):
        if _factory is not _FACTORY:
            raise BoundaryRefused()
        for name, value in fields.items():
            object.__setattr__(self, name, _freeze(value))

    def to_json(self):
        return _thaw(self.values)

    def __repr__(self):
        return '<ValidatedCandidateInputs>'


class _Sensitive:
    """Ephemeral snapshot; deliberately non-dataclass and static repr."""
    __slots__ = ('needles',)

    def __init__(self, values):
        if not isinstance(values, Collection) or isinstance(values, (str, bytes, Mapping)):
            raise BoundaryRefused()
        needles = set()
        for secret in values:
            if type(secret) is not str or not secret or len(secret) > 1048576:
                raise BoundaryRefused()
            data = secret.encode('utf-8')
            needles.update((secret, quote(secret, safe=''), data.hex(),
                            base64.b64encode(data).decode(),
                            base64.urlsafe_b64encode(data).decode().rstrip('='),
                            json.dumps(secret, ensure_ascii=True)[1:-1]))
        self.needles = tuple(needles)

    def __repr__(self):
        return '<SensitiveRegistry>'

    def unsafe(self, text, *, secrets_only=False):
        def matches(value):
            return bool((not secrets_only and _UNSAFE_TEXT.search(value)) or
                        any(needle in value for needle in self.needles))
        # Exact registry membership is always checked independently of canaries.
        if matches(text):
            return True
        decoded = text
        for _ in range(3):
            next_value = decode_json_escapes_v1(html.unescape(unquote(decoded)))
            if next_value == decoded:
                break
            decoded = next_value
            if matches(decoded):
                return True
        for match in re.finditer(r'(?<![0-9a-fA-F])(?:[0-9a-fA-F]{2}){8,}(?![0-9a-fA-F])', decoded):
            blob = bytes.fromhex(match.group())
            if matches(blob.decode('utf-8', errors='replace')):
                return True
        for match in _B64.finditer(decoded):
            token = match.group()
            try:
                blob = base64.b64decode(token + '=' * (-len(token) % 4), altchars=b'-_', validate=True)
            except ValueError:
                continue
            if matches(blob.decode('utf-8', errors='replace')):
                return True
        return False


def _binding(scope_id, generation):
    if (type(scope_id) is not str or not re.fullmatch('[0-9a-f]{64}', scope_id)
            or type(generation) is not int or generation < 0 or generation > 9007199254740991):
        raise BoundaryRefused()


def _schema_validate(ref, value):
    # The pinned MCP dependency already bundles jsonschema/referencing. No test
    # helpers, dynamic install, remote refs or independent runtime dependency.
    from .ipc import validate, _DOCS
    match = re.fullmatch(r'(gateway|host_gateway|host-gateway|dashboard)#/(?:\$defs|components/schemas)/([A-Za-z][A-Za-z0-9]*V1)', ref)
    if match is None:
        raise BoundaryRefused()
    contract, definition = match.groups()
    expected = '/components/schemas/' if contract == 'dashboard' else '/$defs/'
    if ref != contract + '#' + expected + definition:
        raise BoundaryRefused()
    document = _DOCS[contract.replace('_','-')][1]
    definitions = document['components']['schemas'] if contract == 'dashboard' else document['$defs']
    if definition not in definitions:
        raise BoundaryRefused()
    validate(contract.replace('_','-'), definition, value)


def _walk(value, registry, *, redact, scope_id=None):
    """Traverse EVERY field/event, including unknown extensions, errors and metadata."""
    budget = Budget()
    def visit(item, depth=0, key=None):
        budget.visit(depth)
        if type(item) is dict:
            result = {}
            for name, child in item.items():
                budget.visit(depth + 1)
                # A presigned POST form is one credential-bearing unit. Its
                # object key/location is privileged too, not just Policy/Signature.
                if (name == 'fields' and type(child) is dict and
                        any(_BANNED_NAME.search(field_name) for field_name in child)):
                    if not redact:
                        raise BoundaryRefused()
                    continue
                if registry.unsafe(name) or (name not in _NAME_EXCEPTIONS and _BANNED_NAME.search(name)):
                    if not redact:
                        raise BoundaryRefused()
                    # Drop key too: it may itself contain credentials.
                    continue
                result[name] = visit(child, depth + 1, name)
            if 'schema' in item and 'required' in item and 'name' in item:
                if _BANNED_NAME.search(item['name']):
                    if not redact:
                        raise BoundaryRefused()
                    return {'redacted':True}
            return result
        if type(item) is list:
            return [visit(child, depth + 1) for child in item]
        if type(item) is str:
            # Check the WHOLE original value before parsing can split a secret
            # across JSON spans. Key/shape heuristics still run on parsed members
            # below, so harmless IDs adjacent to credential keys survive.
            if registry.unsafe(item, secrets_only=True):
                if not redact:
                    raise BoundaryRefused()
                return _REDACTED
            # Parse first so embedded secret-bearing keys with innocuous values
            # cannot be missed, and safe IDs inside JSON survive redaction.
            spans = list(embedded_json_v1(item))
            chunks = []
            last = 0
            for start, stop, parsed in spans:
                checked = bounded_copy_v1(parsed, budget=budget, depth=depth + 1)
                safe = visit(checked, depth + 1)
                chunks.extend((residual(item[last:start], key), json.dumps(safe, separators=(',',':'))))
                last = stop
            if spans:
                chunks.append(residual(item[last:], key))
                return ''.join(chunks) if redact else item
            return residual(item, key)
        return item

    def residual(text, key):
        unsafe = registry.unsafe(text)
        # Raw resources are never pass-through based on a type tag alone.
        if redact and _URL.search(text):
            unsafe = True
        if not redact and _PATH.search(text) and key not in ('localPath','sourcePath','outputDir','contentRoute'):
            unsafe = True
        if not redact and key == 'localPath' and (
                text.count('/hermes-studiotwin/scopes/') != 1 or
                '/hermes-studiotwin/scopes/'+scope_id+'/media/' not in text):
            unsafe = True
        if unsafe:
            if not redact:
                raise BoundaryRefused()
            return _REDACTED
        return text
    return visit(value)


def redact_upstream_v1(candidate: object, *, sensitive_values: Collection[str]):
    """Volatile sanitized JSON only; not a classified/validated return envelope.

    Covers content, embedded/fenced JSON, structuredContent, resources, _meta,
    errors, progress/diagnostics and extension fields by one recursive walk.
    Classified media extraction must happen in S07 before discarding locations.
    """
    failed = False
    result = None
    try:
        registry = _Sensitive(sensitive_values)
        result = _walk(bounded_copy_v1(candidate), registry, redact=True)
    except (ValueError, TypeError, UnicodeError, RecursionError, KeyError):
        failed = True
    if failed:
        raise BoundaryRefused()
    return result


def validate_mediated_v1(contract_ref: str, candidate: object, *,
                         scope_id: str, generation: int,
                         sensitive_values: Collection[str]) -> MediatedValue:
    failed = False
    result = None
    try:
        _binding(scope_id, generation)
        registry = _Sensitive(sensitive_values)
        result = bounded_copy_v1(candidate)
        _walk(result, registry, redact=False, scope_id=scope_id)
        _schema_validate(contract_ref, result)
    except (ValueError, TypeError, UnicodeError, RecursionError, KeyError):
        failed = True
    if failed:
        raise BoundaryRefused()
    return MediatedValue(_factory=_FACTORY, contract_ref=contract_ref, scope_id=scope_id,
                         generation=generation, value=result)


_CANDIDATE_SCHEMA = ContextVar('studiotwin_candidate_schema', default=None)


@contextmanager
def candidate_schema_v1(tool: str, schema_hash: str, input_schema: object):
    """Backend-only scoped binding for S08's reviewed classified input schema.

    No global tool catalog here. Absent binding fails closed. S08 must compare
    exact live/release hash before entering, and project safe resource refs.
    Never populate this context manager from model/browser schema data.
    """
    schema = bounded_copy_v1(input_schema)
    # No external/local references or executable extensions in this projection.
    def check(node):
        if type(node) is dict:
            if any(k in node for k in ('$ref', '$dynamicRef', '$id', 'pattern', 'format')):
                raise BoundaryRefused()
            for child in node.values():
                check(child)
        elif type(node) is list:
            for child in node:
                check(child)
    check(schema)
    token = _CANDIDATE_SCHEMA.set((tool, schema_hash, _freeze(schema)))
    try:
        yield
    finally:
        _CANDIDATE_SCHEMA.reset(token)


def validate_candidate_inputs_v1(tool: str, schema_hash: str, candidate: object, *,
                                  scope_id: str, generation: int,
                                  sensitive_values: Collection[str]) -> ValidatedCandidateInputs:
    failed = False
    result = None
    try:
        _binding(scope_id, generation)
        registry = _Sensitive(sensitive_values)
        result = bounded_copy_v1(candidate)
        _walk(result, registry, redact=False, scope_id=scope_id)
        _schema_validate('gateway#/$defs/ToolNameV1', tool)
        _schema_validate('gateway#/$defs/Sha256HexV1', schema_hash)
        _schema_validate('gateway#/$defs/CandidateInputsV1', result)
        policy = _CANDIDATE_SCHEMA.get()
        if policy is None or policy[:2] != (tool, schema_hash):
            raise BoundaryRefused()
        from jsonschema import Draft202012Validator
        if not Draft202012Validator(_thaw(policy[2])).is_valid(result):
            raise BoundaryRefused()
    except (ValueError, TypeError, UnicodeError, RecursionError, KeyError):
        failed = True
    if failed:
        raise BoundaryRefused()
    canonical = json.dumps(result, sort_keys=True, separators=(',',':'), ensure_ascii=True, allow_nan=False)
    return ValidatedCandidateInputs(_factory=_FACTORY, tool=tool, schema_hash=schema_hash,
                                    canonical_input_hash=hashlib.sha256(canonical.encode()).hexdigest(),
                                    scope_id=scope_id, generation=generation, values=result)


def safe_error_v1() -> MediatedValue:
    """Static fallback when validating/emitting/logging a failed upstream result.

    No exception argument by design. Caller must bind the returned safe JSON to
    its current authenticated scope before sending; this zero-scope wrapper is
    a template, never evidence of account/session authority.
    """
    return validate_mediated_v1('dashboard#/components/schemas/ErrorV1',
                              {'contract':'studiotwin.dashboard.v1', 'code':'UNAVAILABLE',
                               'message':'Unsafe upstream payload refused.'},
                              scope_id='0'*64, generation=0, sensitive_values=())
