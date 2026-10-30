"""S08 reviewed-release classification, form projection and leaf facade.

Discovery is not execution authority. Only exact live name/input/output hashes
can obtain a reviewed schema/policy or a handler. S04 remains the publication
source (currently setup-only); S09/S10 still own authenticated scope, asset
ownership/effective transforms, consent, ledger and dispatch. No network, signer,
policy updater, raw-schema form interpreter or public global registry exists.
"""
from __future__ import annotations

from collections.abc import Awaitable, Callable, Collection, Mapping
from dataclasses import dataclass
import hashlib
import inspect
import json
from pathlib import Path
import re
from threading import RLock
from types import MappingProxyType

from . import capabilities, redaction
from .host_context import HostContextGate
from .mediation import OutputPolicy, ResourceRule
from .mediation_parse import BoundaryRefused, bounded_copy_v1
from .redaction import MediatedValue, ValidatedCandidateInputs

_FORM_REF = 'dashboard#/components/schemas/ToolInputSchemaResponseV1'
_IPC_REF = 'host_gateway#/$defs/IpcResponseV1'
_SCHEMA_REF = 'gateway#/$defs/ToolInputSchemaV1'
_RESULT_REF = 'gateway#/$defs/GatewayResultV1'
_RELEASE_SHA256 = 'b1e96878fbb01b1f474cdf9f131be55d690b94155234b5b556c910b67f887b93'
_D22 = frozenset('studiotwin_conceptlab_'+s for s in ('create_and_generate','generate','edit'))
_FACTORY = object()


def _load_release():
    data = Path(__file__).with_name('tool_classification.v1.json').read_bytes()
    if hashlib.sha256(data).hexdigest() != _RELEASE_SHA256:
        raise BoundaryRefused()
    value = bounded_copy_v1(json.loads(data))
    if (value['contract'] != 'studiotwin.tool-classification.v1' or
            value['policy'] != 'reviewed-release-only' or len(value['tools']) != 45):
        raise BoundaryRefused()
    return redaction._freeze(value)


RELEASE = _load_release()


def schema_hash_v1(tool: object) -> str:
    """S02 canonical hash: only name, inputSchema and outputSchema, ASCII JSON."""
    failed = False
    result = None
    try:
        value = bounded_copy_v1(tool)
        if type(value) is not dict or not re.fullmatch('[a-z][a-z0-9_-]{0,63}', value['name']):
            raise BoundaryRefused()
        material = {key:value.get(key) for key in ('name','inputSchema','outputSchema')}
        result = hashlib.sha256(json.dumps(material, sort_keys=True, separators=(',',':'),
                                          ensure_ascii=True, allow_nan=False).encode()).hexdigest()
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        failed = True
    if failed:
        raise BoundaryRefused()
    return result


def _input_json_schema(node):
    """Compile ONLY the finite reviewed projection, never live arbitrary schema."""
    kind = node['kind']
    result = {'type':kind}
    for key in ('minimum','maximum','minLength','maxLength','minItems','maxItems'):
        if key in node:
            result[key] = node[key]
    if 'choices' in node:
        result['enum'] = node['choices']
    if kind == 'object':
        result.update(additionalProperties=False,
                      properties={f['name']:_input_json_schema(f['schema']) for f in node['fields']},
                      required=[f['name'] for f in node['fields'] if f['required']])
    elif kind == 'array':
        result['items'] = _input_json_schema(node['items'])
    return result


def _semantic_form(schema):
    """Whole form, including nested arrays/objects; run BEFORE schema recursion."""
    if len(json.dumps(schema, ensure_ascii=True, separators=(',',':'), allow_nan=False).encode()) > 65536:
        raise BoundaryRefused()
    count = 0
    def walk(node, depth=1):
        nonlocal count
        count += 1
        if depth > 8 or count > 256 or type(node) is not dict:
            raise BoundaryRefused()
        kind = node['kind']
        for low, high in (('minimum','maximum'),('minLength','maxLength'),('minItems','maxItems')):
            if low in node and high in node and node[low] > node[high]:
                raise BoundaryRefused()
        def valid(value):
            types = {'string':(str,), 'integer':(int,), 'number':(int,float),
                     'boolean':(bool,), 'null':(type(None),)}
            if kind not in types or type(value) not in types[kind]:
                return False
            from jsonschema import Draft202012Validator
            shape = {k:v for k,v in node.items() if k in
                     ('minimum','maximum','minLength','maxLength','minItems','maxItems')}
            shape['type'] = kind
            return Draft202012Validator(shape).is_valid(value)
        if 'choices' in node:
            choices = node['choices']
            if not choices or any(not valid(v) for v in choices):
                raise BoundaryRefused()
            encoded = [json.dumps(v,sort_keys=True,allow_nan=False) for v in choices]
            if len(set(encoded)) != len(encoded):
                raise BoundaryRefused()
        if 'defaultValue' in node:
            default = node['defaultValue']
            if not valid(default) or ('choices' in node and default not in node['choices']):
                raise BoundaryRefused()
        if kind == 'object':
            fields = node['fields']
            names = [f['name'] for f in fields]
            if len(set(names)) != len(names):
                raise BoundaryRefused()
            for field in fields:
                walk(field['schema'], depth+1)
        elif kind == 'array':
            walk(node['items'], depth+1)
    walk(schema)
    # Plain text only, including values hidden in choices/defaults and field names.
    def plain(value):
        if type(value) is str and re.search(r'[<>]|javascript\s*:|on\w+\s*=', value, re.I):
            raise BoundaryRefused()
        if type(value) is dict:
            for key, child in value.items():
                plain(key); plain(child)
        elif type(value) is list:
            for child in value: plain(child)
    plain(schema)


def validate_form_schema_v1(candidate: object, *, scope_id: str, generation: int,
                            sensitive_values: Collection[str]) -> MediatedValue:
    failed = False
    result = None
    try:
        schema = bounded_copy_v1(candidate)
        _semantic_form(schema)
        result = redaction.validate_mediated_v1(_SCHEMA_REF, schema, scope_id=scope_id,
                                                generation=generation, sensitive_values=sensitive_values)
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        failed = True
    if failed:
        raise BoundaryRefused()
    return result


def validate_input_schema_response_v1(candidate: object, *, wrapped: bool = False,
                                      scope_id: str, generation: int,
                                      sensitive_values: Collection[str]) -> MediatedValue:
    """S11 seam: complete-envelope S06 boundary PLUS CF8 semantic unwrapping.

    Receiver still must authenticate MAC/nonce/peer/requestId/method, compare the
    outstanding tool/hash, and bind current scope/generation BEFORE consuming.
    A shape-valid envelope cannot attest any of those facts on its own.
    """
    failed = False
    result = None
    try:
        value = bounded_copy_v1(candidate)
        payload = value
        if wrapped:
            if value['ok'] is not True or value['result']['method'] != 'capabilities.inputSchema':
                raise BoundaryRefused()
            payload = value['result']['payload']
        _semantic_form(payload['inputSchema'])
        result = redaction.validate_mediated_v1(_IPC_REF if wrapped else _FORM_REF, value,
                    scope_id=scope_id, generation=generation, sensitive_values=sensitive_values)
    except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
        failed = True
    if failed:
        raise BoundaryRefused()
    return result


class Classification:
    """Detached live snapshot over one immutable pinned release. Reconnect creates
    a new instance; it never changes RELEASE. No runtime manifest/path override.
    """
    __slots__ = ('_live', '_available')

    def __init__(self, live_tools, *, manifest=None):
        if manifest is not None:
            raise BoundaryRefused()
        failed = False
        try:
            tools = bounded_copy_v1(live_tools)
            if type(tools) is not list or len(tools) > 512:
                raise BoundaryRefused()
            live = {}
            available = set()
            for tool in tools:
                name = tool['name']
                if (type(name) is not str or not re.fullmatch('[a-z][a-z0-9_-]{0,63}',name)
                        or name in live):
                    raise BoundaryRefused()
                live[name] = (schema_hash_v1(tool), type(tool.get('inputSchema')) is dict and
                              ('outputSchema' not in tool or type(tool['outputSchema']) is dict))
                row = RELEASE['tools'].get(name)
                if row and live[name] == (row['schemaHash'],True):
                    try:
                        validate_form_schema_v1(redaction._thaw(row['inputSchema']),
                                                scope_id='0'*64,generation=0,sensitive_values=())
                        available.add(name)
                    except BoundaryRefused:
                        pass
            self._live = MappingProxyType(live)
            self._available = frozenset(available)
        except (ValueError, TypeError, KeyError, UnicodeError, RecursionError):
            failed = True
        if failed:
            raise BoundaryRefused()

    def update(self, *_args, **_kwargs):
        raise BoundaryRefused()

    sign = update
    reload = update

    def _reason(self, name):
        row = RELEASE['tools'].get(name)
        if row is None or name not in self._live:
            return 'unclassified'
        live_hash, present = self._live[name]
        if not present:
            return 'schema-unavailable'
        if live_hash != row['schemaHash']:
            return 'schema-changed'
        if name not in self._available:
            return 'schema-unavailable'
        if name in _D22:
            return 'concept-paid-d22'
        return None

    def is_classified(self, name):
        return self._reason(name) in (None,'concept-paid-d22')

    def _row(self, name, schema_hash=None, *, allow_disabled=False):
        reason = self._reason(name)
        if reason is not None and not (allow_disabled and reason == 'concept-paid-d22'):
            raise BoundaryRefused()
        row = RELEASE['tools'][name]
        if schema_hash is not None and schema_hash != row['schemaHash']:
            raise BoundaryRefused()
        return row

    def discover(self, *, publication=None, scope_id, generation, sensitive_values):
        # Never interpret caller tier/boolean JSON as principal or host proof.
        candidates = [name for name in self._live if self._reason(name) is None]
        callable_names = set(capabilities.published_tools(publication, candidates))
        rows = []
        tiers = {'setup'}
        for name,(live_hash,_) in self._live.items():
            reviewed = RELEASE['tools'].get(name)
            reason = self._reason(name)
            if reason is None and name not in callable_names:
                reason = 'principal-unproven'
            executable = reason is None
            if executable:
                tiers.add(reviewed['tier'])
            rows.append(dict(name=name,family=reviewed['family'] if reviewed else 'platform',
                             schemaHash=live_hash,fixedCost=reviewed['fixedCost'] if reviewed else None,
                             classification='classified' if reviewed else 'discovered_unclassified',
                             executable=executable,disabledReason=reason))
        value = dict(protocol='studiotwin.gateway.v1', publishedTiers=['setup',*sorted(tiers-{'setup'})],
                     agentCallable=['studiotwin_setup_status',*[r['name'] for r in rows if r['executable']]],tools=rows)
        return redaction.validate_mediated_v1('gateway#/$defs/CapabilityListV1',value,
                    scope_id=scope_id,generation=generation,sensitive_values=sensitive_values)

    def input_schema(self, tool, schema_hash, *, request_id=None, scope_id, generation, sensitive_values):
        row = self._row(tool,schema_hash,allow_disabled=True)
        value = dict(contract='studiotwin.dashboard.v1',tool=tool,schemaHash=row['schemaHash'],
                     classification='classified',inputSchema=redaction._thaw(row['inputSchema']))
        if request_id is not None:
            value = dict(protocol='studiotwin.host-gateway.v1',requestId=request_id,ok=True,
                         result=dict(method='capabilities.inputSchema',payload=value))
        return validate_input_schema_response_v1(value,wrapped=request_id is not None,
                    scope_id=scope_id,generation=generation,sensitive_values=sensitive_values)

    def candidate_inputs(self, tool, schema_hash, candidate, *, scope_id, generation, sensitive_values):
        row = self._row(tool,schema_hash)
        # Exact live AND release hash checked by _row before S06's context opens.
        schema = _input_json_schema(redaction._thaw(row['inputSchema']))
        with redaction.candidate_schema_v1(tool,schema_hash,schema):
            result = redaction.validate_candidate_inputs_v1(tool,schema_hash,candidate,
                        scope_id=scope_id,generation=generation,sensitive_values=sensitive_values)
        def check_path(value,path):
            if not path:
                if type(value) is not str or not re.fullmatch('[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}',value):
                    raise BoundaryRefused()
            elif path[0] == '*':
                for child in value: check_path(child,path[1:])
            elif path[0] in value:
                check_path(value[path[0]],path[1:])
        for reference in row['inputReferences']:
            check_path(result.values,reference['path'])
        return result

    def output_policy(self, tool):
        row = self._row(tool)
        policy = row['mediation']
        return OutputPolicy(tool=tool,schema_hash=row['schemaHash'],
                            job_path=tuple(policy['jobPath']) if policy['jobPath'] else None,
                            summary_path=tuple(policy['summaryPath']) if policy['summaryPath'] else None,
                            resources=tuple(ResourceRule(**redaction._thaw(r)) for r in policy['resources']))


@dataclass(frozen=True,slots=True,init=False,repr=False)
class GatewayCallContext:
    scope_id: str
    generation: int
    # S04 actually returns receiver-owned MappingProxyType, not a public class
    # literally named VerifiedHostContext. Never invent a second trust wrapper.
    trusted_context: Mapping
    execute: Callable[[ValidatedCandidateInputs], Awaitable[MediatedValue]]

    def __init__(self, *, _factory=None, **fields):
        if _factory is not _FACTORY:
            raise BoundaryRefused()
        for name,value in fields.items():
            object.__setattr__(self,name,value)

    def __repr__(self):
        return '<GatewayCallContext>'


GatewayHandler = Callable[..., Awaitable[MediatedValue]]


class GatewayRegistry:
    """Leaf registration, not consent. No shared router or global singleton.

    S28 supplies this instance. S09/S10 supplies the central execute callable,
    which is the ONLY dispatch seam. This layer checks its exact bound wrappers
    and output but cannot establish an absent ledger/ownership implementation.
    """
    def __init__(self, classification: Classification):
        if type(classification) is not Classification:
            raise BoundaryRefused()
        self._classification = classification
        self._handlers = {}
        self._contexts = {}
        self._lock = RLock()

    def add(self, name: str, handler: GatewayHandler) -> None:
        self._classification._row(name)
        failed = False
        try:
            if not inspect.iscoroutinefunction(handler):
                raise BoundaryRefused()
            signature = inspect.signature(handler)
            params = list(signature.parameters.values())
            if ([p.name for p in params] != ['context','inputs'] or
                    any(p.kind is not inspect.Parameter.KEYWORD_ONLY or p.default is not inspect.Parameter.empty for p in params)):
                raise BoundaryRefused()
            # Accept real identities or the exact canonical forward names; never
            # eval arbitrary annotation expressions supplied by a leaf.
            for actual,expected in ((params[0].annotation,GatewayCallContext),
                                    (params[1].annotation,ValidatedCandidateInputs),
                                    (signature.return_annotation,MediatedValue)):
                if actual is not expected and actual != expected.__name__:
                    raise BoundaryRefused()
        except (ValueError,TypeError):
            failed = True
        if failed:
            raise BoundaryRefused()
        with self._lock:
            if name in self._handlers:
                raise BoundaryRefused()
            self._handlers[name] = handler

    def context(self, name, *, scope_id, generation, gate, trusted_context, execute, sensitive_values):
        row = self._classification._row(name)
        redaction._binding(scope_id,generation)
        if (type(gate) is not HostContextGate or not gate._owned(trusted_context) or
                trusted_context['toolName'] != name or not inspect.iscoroutinefunction(execute)):
            raise BoundaryRefused()
        async def bound(inputs):
            if (type(inputs) is not ValidatedCandidateInputs or inputs.tool != name or
                    inputs.schema_hash != row['schemaHash'] or inputs.scope_id != scope_id or
                    inputs.generation != generation):
                raise BoundaryRefused()
            self._classification._row(name,inputs.schema_hash)
            # No raw/caller-constructed facade grants publication authority.
            if name not in capabilities.published_tools(None,[name]):
                raise BoundaryRefused()
            failed = False
            result = None
            try:
                result = await execute(inputs)
                if (type(result) is not MediatedValue or result.contract_ref != _RESULT_REF or
                        result.scope_id != scope_id or result.generation != generation or
                        result.value['tool'] != name):
                    raise BoundaryRefused()
                result = redaction.validate_mediated_v1(_RESULT_REF,result.to_json(),
                            scope_id=scope_id,generation=generation,sensitive_values=sensitive_values)
            except Exception:
                failed = True
            if failed:
                raise BoundaryRefused()
            return result
        context = GatewayCallContext(_factory=_FACTORY,scope_id=scope_id,generation=generation,
                                      trusted_context=trusted_context,execute=bound)
        with self._lock:
            if len(self._contexts) >= 1024:
                raise BoundaryRefused()
            self._contexts[id(context)] = (name,context)
        return context

    async def invoke(self, name, *, context: GatewayCallContext,
                     inputs: ValidatedCandidateInputs) -> MediatedValue:
        row = self._classification._row(name)
        with self._lock:
            owned = self._contexts.get(id(context))
            handler = self._handlers.get(name)
        if (owned is None or owned[0] != name or owned[1] is not context or handler is None or
                type(inputs) is not ValidatedCandidateInputs or inputs.tool != name or
                inputs.schema_hash != row['schemaHash'] or inputs.scope_id != context.scope_id or
                inputs.generation != context.generation or name not in capabilities.published_tools(None,[name])):
            raise BoundaryRefused()
        failed = False
        result = None
        try:
            result = await handler(context=context,inputs=inputs)
            if (type(result) is not MediatedValue or result.contract_ref != _RESULT_REF or
                    result.scope_id != context.scope_id or result.generation != context.generation or
                    result.value['tool'] != name):
                raise BoundaryRefused()
            result = redaction.validate_mediated_v1(_RESULT_REF,result.to_json(),
                        scope_id=context.scope_id,generation=context.generation,
                        sensitive_values=())  # bound execute already checked the current registry
        except Exception:
            failed = True
        if failed:
            raise BoundaryRefused()
        return result
