"""Reviewed effective inputs, not browser authority or an asset resolver.

The S08 projection deliberately replaces resource strings/file items with UUIDs.
We restore only reviewed vpc asset references, after backend ownership lookup.
No presigned locations, caller resolver, default injection or URL decoding.
EffectiveInputs is volatile and must never be sent to display/IPC/log sinks.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import json

from .classification import Classification, ValidatedCandidateInputs
from .mediation_parse import BoundaryRefused
from . import redaction as R

_FACTORY = object()


@dataclass(frozen=True, slots=True, init=False, repr=False)
class EffectiveInputs:
    tool: str
    schema_hash: str
    canonical_input_hash: str
    scope_id: str
    generation: int
    values: object = field(repr=False)
    candidate: ValidatedCandidateInputs = field(repr=False)

    def __init__(self, *, _factory=None, **fields):
        if _factory is not _FACTORY:
            raise BoundaryRefused()
        for name, value in fields.items():
            object.__setattr__(self, name, R._freeze(value))

    def to_json(self):
        return R._thaw(self.values)

    def __repr__(self):
        return '<EffectiveInputs>'


def canonicalize(inputs: ValidatedCandidateInputs, *, classification: Classification,
                 store, sensitive_values) -> EffectiveInputs:
    if type(inputs) is not ValidatedCandidateInputs or type(classification) is not Classification:
        raise BoundaryRefused()
    store.require_current(inputs.scope_id, inputs.generation)
    row = classification._row(inputs.tool, inputs.schema_hash)  # includes D22
    # Revalidate with current backend registry and exact reviewed release schema;
    # a wrapper from some other candidate_schema context is not authority.
    checked = classification.candidate_inputs(inputs.tool, inputs.schema_hash, inputs.to_json(),
        scope_id=inputs.scope_id, generation=inputs.generation, sensitive_values=sensitive_values)
    if checked.canonical_input_hash != inputs.canonical_input_hash:
        raise BoundaryRefused()
    values = checked.to_json()

    def transform(parent, path, reference):
        key = path[0]
        keys = list(range(len(parent))) if key == '*' else ([key] if key in parent else [])
        for item in keys:
            if len(path) > 1:
                transform(parent[item], path[1:], reference)
                continue
            asset_id = parent[item]
            if not store.owns_asset(inputs.scope_id, inputs.generation, asset_id):
                raise BoundaryRefused()
            # Platform asset IDs remain UUIDs. Generation functions accept the
            # reviewed VP vpc reference form, including file-item array entries.
            effective = 'vpc::assets/' + asset_id if row['family'] == 'generation' else asset_id
            target = reference.get('upstreamField', item)
            if target != item:
                if target in parent:
                    raise BoundaryRefused()
                del parent[item]
            parent[target] = effective

    for reference in row['inputReferences']:
        if reference['kind'] == 'uuid':
            continue  # S08 syntax-checked object/job/Concept ID, not an asset.
        if reference['kind'] != 'asset' or not reference['path']:
            raise BoundaryRefused()
        transform(values, reference['path'], reference)
    for restriction in row['inputRestrictions']:
        if restriction['policy'] == 'reviewed-field-alias':
            path = restriction['path']
            if len(path) != 1:
                raise BoundaryRefused()
            source, target = path[0], restriction['upstreamField']
            if source in values:
                if target in values:
                    raise BoundaryRefused()
                values[target] = values.pop(source)
    # Check again after resource lookups; activation races cannot produce a
    # current quote from old-generation data. S09 reserve checks again atomically.
    store.require_current(inputs.scope_id, inputs.generation)
    digest = hashlib.sha256(json.dumps(values, sort_keys=True, separators=(',', ':'),
                                       ensure_ascii=True, allow_nan=False).encode()).hexdigest()
    return EffectiveInputs(_factory=_FACTORY, tool=inputs.tool, schema_hash=inputs.schema_hash,
        canonical_input_hash=digest, scope_id=inputs.scope_id, generation=inputs.generation,
        values=values, candidate=checked)
