"""Exact-match checker for contracts/leaf-exports.md (studiotwin.leaf-exports.v1).

Stdlib only. It parses leaf source text and never imports or executes a leaf, so S28's
registration test can run it on untrusted leaf files before loading them.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path
from typing import Any

FENCE = re.compile(r"```json leaf-exports\n(.*?)\n```", re.DOTALL)
SERVICE_ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


class LeafRefused(ValueError):
    """The leaf does not match its frozen export kind exactly."""


def load_spec(md_path: Path) -> dict[str, Any]:
    blocks = FENCE.findall(md_path.read_text(encoding="utf-8"))
    if len(blocks) != 1:
        raise ValueError(f"expected exactly one leaf-exports block, found {len(blocks)}")
    return json.loads(blocks[0])


def _refuse(msg: str) -> None:
    raise LeafRefused(msg)


def _module_exports(tree: ast.Module) -> list[str]:
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            if isinstance(node.value, (ast.List, ast.Tuple)) and all(
                    isinstance(e, ast.Constant) and isinstance(e.value, str) for e in node.value.elts):
                return [e.value for e in node.value.elts]
            _refuse("__all__ must be a literal list of names")
    _refuse("missing __all__")
    return []


def _top_level(tree: ast.Module) -> dict[str, ast.AST]:
    out: dict[str, ast.AST] = {}
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            out[node.name] = node
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    out[t.id] = node
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            out[node.target.id] = node
    return out


def _check_exact_exports(kind: str, spec: dict[str, Any], exports: list[str]) -> None:
    want = spec["kinds"][kind]["exports"]
    if sorted(exports) != sorted(want) or len(set(exports)) != len(exports):
        missing = sorted(set(want) - set(exports))
        extra = sorted(set(exports) - set(want))
        _refuse(f"{kind} leaf exports {exports!r}; missing {missing}, extra {extra}")


def check_gateway_leaf(source: str, spec: dict[str, Any]) -> None:
    tree = ast.parse(source)
    _check_exact_exports("gateway", spec, _module_exports(tree))
    fn = _top_level(tree).get("register_gateway")
    if not isinstance(fn, ast.FunctionDef):
        _refuse("register_gateway must be a plain (sync) def")
    a = fn.args
    if (a.posonlyargs or a.vararg or a.kwonlyargs or a.kwarg or a.defaults or len(a.args) != 1
            or a.args[0].arg != "registry"):
        _refuse("register_gateway must take exactly one parameter named registry, no default")
    if not (isinstance(fn.returns, ast.Constant) and fn.returns.value is None):
        _refuse("register_gateway must be annotated -> None")


def check_backend_leaf(source: str, stem: str, spec: dict[str, Any]) -> None:
    tree = ast.parse(source)
    _check_exact_exports("backend", spec, _module_exports(tree))
    top = _top_level(tree)
    sid = top.get("SERVICE_ID")
    value = getattr(sid, "value", None)
    if not (isinstance(sid, (ast.Assign, ast.AnnAssign)) and isinstance(value, ast.Constant)
            and isinstance(value.value, str)):
        _refuse("SERVICE_ID must be a module-level string literal")
    if value.value != stem or not SERVICE_ID_RE.match(value.value):
        _refuse(f"SERVICE_ID {value.value!r} must equal the module stem {stem!r}")
    rt = top.get("router")
    call = getattr(rt, "value", None)
    if not (isinstance(rt, (ast.Assign, ast.AnnAssign)) and isinstance(call, ast.Call)
            and isinstance(call.func, ast.Name) and call.func.id == "APIRouter"):
        _refuse("router must be a module-level APIRouter(...) call")
    if any(k.arg == "prefix" for k in call.keywords):
        _refuse("router must not set prefix=; core mounts it under /api/plugins/<name>")


_TS_EXPORT = re.compile(r"^\s*export\b(.*)$", re.MULTILINE)
_TS_CONTRIBUTION = re.compile(r"^\s*const\s+contribution\s*:\s*PluginContribution\s*=")


def check_desktop_leaf(source: str, spec: dict[str, Any]) -> None:
    stripped = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    stripped = re.sub(r"(^|[^:])//[^\n]*", r"\1", stripped)
    exports = _TS_EXPORT.findall(stripped)
    if len(exports) != 1:
        _refuse(f"desktop leaf must have exactly one export statement, found {len(exports)}")
    if not _TS_CONTRIBUTION.match(exports[0]):
        _refuse("desktop leaf must export `const contribution: PluginContribution`")
    _check_exact_exports("desktop", spec, ["contribution"])
