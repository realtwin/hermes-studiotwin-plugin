"""Shared loaders and lints for the S03 frozen contracts.

Consumers (S04 onward) may import this module by file path; it depends only on the stdlib and
the pinned `jsonschema`/`referencing` test dependencies. It never imports gateway/, dashboard/ or
src/ code.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Iterator

sys.dont_write_bytecode = True

from jsonschema import Draft202012Validator  # noqa: E402
from referencing import Registry, Resource  # noqa: E402
from referencing.jsonschema import DRAFT202012  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS = ROOT / "contracts"
FIXTURES = ROOT / "tests" / "fixtures"

GATEWAY_PATH = CONTRACTS / "gateway-v1.schema.json"
HOST_GATEWAY_PATH = CONTRACTS / "host-gateway-v1.schema.json"
DASHBOARD_PATH = CONTRACTS / "dashboard-v1.openapi.json"
LEAF_EXPORTS_PATH = CONTRACTS / "leaf-exports.md"

GATEWAY_ID = "urn:hermes-studiotwin:contracts:gateway-v1"
HOST_GATEWAY_ID = "urn:hermes-studiotwin:contracts:host-gateway-v1"
DASHBOARD_ID = "urn:hermes-studiotwin:contracts:dashboard-v1"

GATEWAY_PROTOCOL = "studiotwin.gateway.v1"
HOST_GATEWAY_PROTOCOL = "studiotwin.host-gateway.v1"
DASHBOARD_CONTRACT = "studiotwin.dashboard.v1"
LEAF_CONTRACT = "studiotwin.leaf-exports.v1"


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def documents() -> dict[str, dict[str, Any]]:
    return {"gateway": load(GATEWAY_PATH), "host_gateway": load(HOST_GATEWAY_PATH), "dashboard": load(DASHBOARD_PATH)}


def registry(docs: dict[str, dict[str, Any]] | None = None) -> Registry:
    docs = docs or documents()
    pairs = [(GATEWAY_ID, docs["gateway"]), (HOST_GATEWAY_ID, docs["host_gateway"]),
             (DASHBOARD_ID, _openapi_as_schema(docs["dashboard"]))]
    return Registry().with_resources((uri, Resource.from_contents(doc, default_specification=DRAFT202012))
                                     for uri, doc in pairs)


def _openapi_as_schema(doc: dict[str, Any]) -> dict[str, Any]:
    """Expose the OpenAPI document's components so `urn:...dashboard-v1#/components/schemas/X`
    resolves. OpenAPI 3.1 schema objects are JSON Schema 2020-12."""
    return {"$schema": "https://json-schema.org/draft/2020-12/schema", "$id": DASHBOARD_ID,
            "components": doc.get("components", {})}


def validator(ref: str, docs: dict[str, dict[str, Any]] | None = None) -> Draft202012Validator:
    """Validator for a fragment, e.g. ``gateway#/$defs/AuthorizationV1``."""
    base, _, frag = ref.partition("#")
    uri = {"gateway": GATEWAY_ID, "host_gateway": HOST_GATEWAY_ID, "dashboard": DASHBOARD_ID}[base]
    return Draft202012Validator({"$ref": f"{uri}#{frag}"}, registry=registry(docs))


def errors(ref: str, instance: Any, docs: dict[str, dict[str, Any]] | None = None) -> list[str]:
    return [e.message for e in validator(ref, docs).iter_errors(instance)]


def is_valid(ref: str, instance: Any, docs: dict[str, dict[str, Any]] | None = None) -> bool:
    return validator(ref, docs).is_valid(instance)


def scoped_media_candidate(path: str, scope_id: str, docs=None) -> bool:
    """Conformance oracle only, NOT an open-file authorization or production sandbox."""
    return (is_valid("gateway#/$defs/ScopeIdV1", scope_id, docs)
            and is_valid("gateway#/$defs/ScopedMediaPathV1", path, docs)
            and path.count("/hermes-studiotwin/scopes/") == 1
            and f"/hermes-studiotwin/scopes/{scope_id}/media/" in path)


# --------------------------------------------------------------------------- schema walking

def walk(node: Any, path: str = "") -> Iterator[tuple[str, Any]]:
    """Yield (json-pointer-ish path, node) for every dict in a document."""
    if isinstance(node, dict):
        yield path, node
        for k, v in node.items():
            yield from walk(v, f"{path}/{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from walk(v, f"{path}/{i}")


def property_names(doc: Any) -> Iterator[tuple[str, str]]:
    """Every declared property name (schema `properties`, `required`, OpenAPI parameter names)."""
    for path, node in walk(doc):
        props = node.get("properties")
        if isinstance(props, dict) and ("type" in node or "required" in node or "additionalProperties" in node
                                         or "$ref" not in props):
            for name in props:
                yield f"{path}/properties", name
        if isinstance(node.get("required"), list) and all(isinstance(x, str) for x in node["required"]):
            for name in node["required"]:
                yield f"{path}/required", name
        if node.get("in") in ("query", "header", "path", "cookie") and isinstance(node.get("name"), str):
            yield f"{path}/parameter", node["name"]


def _types(node: dict[str, Any]) -> set[str]:
    t = node.get("type")
    return {t} if isinstance(t, str) else set(t) if isinstance(t, list) else set()


def string_schemas(doc: Any) -> Iterator[tuple[str, dict[str, Any]]]:
    """Every schema node that admits a JSON string."""
    for path, node in walk(doc):
        if "string" in _types(node) and "/examples" not in path and "/x-" not in path:
            yield path, node


# Field names that would carry a presigned URL, storage URI, credential or API key (D09/D20).
# Matched case-insensitively against each camelCase/snake_case word boundary-free name.
BANNED_NAME = re.compile(
    r"(url|uri|href|link|signature|signed|policy|credential|secret|password|passwd|api_?key|"
    r"access_?key|private_?key|signing_?key|mac_?key|boot_?cap|authorization|bearer|cookie|"
    r"presign|amz|session_?token|security_?token|bucket|storage)", re.IGNORECASE)
# The one token-named field: an opaque server quote handle (DESIGN §7.1), pattern-constrained.
NAME_ALLOWLIST = frozenset({"serverQuoteToken"})


def banned_property_names(doc: Any) -> list[tuple[str, str]]:
    out = []
    for where, name in property_names(doc):
        if name in NAME_ALLOWLIST:
            continue
        if BANNED_NAME.search(name) or re.search(r"token", name, re.IGNORECASE):
            out.append((where, name))
    return out
