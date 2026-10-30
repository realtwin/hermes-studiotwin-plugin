"""S03 frozen leaf exports (contracts/leaf-exports.md).

DESIGN §9 preamble and D25: gateway leaves expose `register_gateway(registry)`, backend leaves
expose `SERVICE_ID` and `router`, and Desktop leaves export `contribution`. A missing export, an
extra export or a wrong signature is refused. S28 alone owns the four integration files.
"""

from __future__ import annotations

import importlib.util
import json
import re
import sys
from pathlib import Path

import pytest

sys.dont_write_bytecode = True
_HERE = Path(__file__).resolve().parent
ROOT = _HERE.parents[1]


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


L = _load("st_leaf_check", _HERE / "leaf_check.py")
SCOPES_TOOL = _load("st_check_slice_scopes", ROOT / "tools" / "check-slice-scopes.py")
MD = ROOT / "contracts" / "leaf-exports.md"
INTEGRATION = ["gateway/router.py", "dashboard/router.py", "src/registry.ts", "src/plugin.tsx"]


@pytest.fixture(scope="module")
def spec():
    return L.load_spec(MD)


@pytest.fixture(scope="module")
def scopes():
    return json.loads((ROOT / "slice-scopes.json").read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------ the document

def test_spec_is_exact_match_v1(spec):
    assert spec["contract"] == "studiotwin.leaf-exports.v1"
    assert spec["compatibility"] == "exact-match" and spec["onMismatch"] == "refuse"
    assert set(spec["kinds"]) == {"gateway", "backend", "desktop"}


def test_three_export_signatures_appear_exactly(spec):
    k = spec["kinds"]
    assert k["gateway"]["exports"] == ["register_gateway"]
    assert k["gateway"]["path"] == "gateway/leaves/<name>.py"
    assert k["gateway"]["signatures"] == {"register_gateway": "def register_gateway(registry: GatewayRegistry) -> None"}
    assert k["backend"]["exports"] == ["SERVICE_ID", "router"]
    assert k["backend"]["path"] == "dashboard/services/<name>.py"
    assert k["backend"]["signatures"] == {"SERVICE_ID": 'SERVICE_ID: Final[str] = "<name>"',
                                          "router": "router: APIRouter = APIRouter()"}
    assert k["desktop"]["exports"] == ["contribution"]
    assert k["desktop"]["signatures"] == {"contribution": "export const contribution: PluginContribution"}
    text = MD.read_text(encoding="utf-8")
    for sig in ("register_gateway(registry)", "`SERVICE_ID`", "`router`", "`contribution`"):
        assert sig in text, sig


def test_integration_facts_cite_pinned_core_and_sdk(spec):
    text = MD.read_text(encoding="utf-8")
    for cite in ("hermes_cli/web_server_dashboard.py:1231-1237", "hermes_cli/plugin_host_child.py:318-322",
                 "src/sdk.d.ts:72-81", "/api/plugins/<name>"):
        assert cite in text, cite
    sdk = (ROOT / "src" / "sdk.d.ts").read_text(encoding="utf-8").splitlines()
    assert sdk[71].startswith("export interface PluginContribution") and sdk[80].strip() == "}"


def test_leaf_paths_match_slice_grants(spec, scopes):
    """Every listed leaf is writable by exactly its declared slice, and by no one else."""
    for path, owner in spec["leaves"].items():
        assert SCOPES_TOOL.writers(scopes, path) == [owner], path
        kind = "gateway" if path.startswith("gateway/leaves/") else "backend"
        pattern = spec["kinds"][kind]["path"].replace("<name>", "[a-z][a-z0-9_]*")
        assert re.fullmatch(pattern.replace(".", r"\."), path), path


def test_registry_and_handler_interface_are_frozen(spec):
    assert "gatewayRegistry" in spec
    registry = spec["gatewayRegistry"]
    assert registry == {
        "definitionOwner": "S08", "integrationOwner": "S28",
        "registration": "def add(self, name: str, handler: GatewayHandler) -> None",
        "handler": "async def handler(*, context: GatewayCallContext, inputs: ValidatedCandidateInputs) -> MediatedValue",
        "duplicates": "refuse", "unclassified": "refuse", "schemaDrift": "refuse",
        "resultContract": "studiotwin.gateway.v1#GatewayResultV1"}
    # An independent leaf author can implement the frozen callable without guessing arguments.
    import inspect
    async def handler(*, context: "GatewayCallContext", inputs: "ValidatedCandidateInputs") -> "MediatedValue":
        return await context.execute(inputs)
    sig = inspect.signature(handler)
    assert list(sig.parameters) == ["context", "inputs"]
    assert all(p.kind == inspect.Parameter.KEYWORD_ONLY for p in sig.parameters.values())
    assert inspect.iscoroutinefunction(handler)


# ----------------------------------------------------------------------- S28 ownership

def test_only_s28_owns_the_integration_files(spec, scopes):
    assert spec["integrationOwner"] == "S28"
    assert spec["integrationFiles"] == INTEGRATION
    for path in INTEGRATION:
        assert SCOPES_TOOL.writers(scopes, path) == ["S28"], path
    s28 = next(s for s in scopes["slices"] if s["id"] == "S28")
    assert set(INTEGRATION) <= set(s28["writable"])


def test_ownership_check_detects_a_second_writer(scopes):
    """The ownership assertion is live: a leaf slice granted dashboard/router.py is caught."""
    import copy
    bad = copy.deepcopy(scopes)
    next(s for s in bad["slices"] if s["id"] == "S14")["writable"].append("dashboard/router.py")
    assert SCOPES_TOOL.writers(bad, "dashboard/router.py") == ["S14", "S28"]


# ----------------------------------------------------------------------- gateway leaves

GOOD_GATEWAY = '''
from __future__ import annotations
__all__ = ["register_gateway"]

def _tool(args):
    return args

def register_gateway(registry: "GatewayRegistry") -> None:
    registry.add("studiotwin_get_job_status", _tool)
'''


def test_good_gateway_leaf_is_accepted(spec):
    L.check_gateway_leaf(GOOD_GATEWAY, spec)


@pytest.mark.parametrize("case,source", [
    ("missing export", GOOD_GATEWAY.replace('__all__ = ["register_gateway"]', "__all__ = []")),
    ("no __all__", GOOD_GATEWAY.replace('__all__ = ["register_gateway"]\n', "")),
    ("extra export", GOOD_GATEWAY.replace('["register_gateway"]', '["register_gateway", "router"]')),
    ("renamed", GOOD_GATEWAY.replace("def register_gateway", "def register")),
    ("two params", GOOD_GATEWAY.replace('(registry: "GatewayRegistry")', '(registry, scope)')),
    ("wrong param name", GOOD_GATEWAY.replace('(registry: "GatewayRegistry")', '(reg)')),
    ("default", GOOD_GATEWAY.replace('(registry: "GatewayRegistry")', '(registry=None)')),
    ("kwargs", GOOD_GATEWAY.replace('(registry: "GatewayRegistry")', '(registry, **kw)')),
    ("async", GOOD_GATEWAY.replace("def register_gateway", "async def register_gateway")),
    ("no return annotation", GOOD_GATEWAY.replace(" -> None:", ":")),
    ("not a function", GOOD_GATEWAY.replace("def register_gateway(registry: \"GatewayRegistry\") -> None:\n"
                                            "    registry.add(\"studiotwin_get_job_status\", _tool)\n",
                                            "register_gateway = _tool\n")),
])
def test_bad_gateway_leaf_is_refused(spec, case, source):
    with pytest.raises(L.LeafRefused):
        L.check_gateway_leaf(source, spec)


# ----------------------------------------------------------------------- backend leaves

GOOD_BACKEND = '''
from typing import Final
from fastapi import APIRouter

__all__ = ["SERVICE_ID", "router"]
SERVICE_ID: Final[str] = "jobs"
router = APIRouter(tags=["jobs"])

@router.get("/jobs")
def list_jobs():
    return {}
'''


def test_good_backend_leaf_is_accepted(spec):
    L.check_backend_leaf(GOOD_BACKEND, "jobs", spec)


@pytest.mark.parametrize("case,source,stem", [
    ("missing router", GOOD_BACKEND.replace('["SERVICE_ID", "router"]', '["SERVICE_ID"]'), "jobs"),
    ("missing service id", GOOD_BACKEND.replace('["SERVICE_ID", "router"]', '["router"]'), "jobs"),
    ("extra export", GOOD_BACKEND.replace('["SERVICE_ID", "router"]', '["SERVICE_ID", "router", "list_jobs"]'), "jobs"),
    ("register_gateway in backend", GOOD_BACKEND.replace('["SERVICE_ID", "router"]',
                                                          '["SERVICE_ID", "router", "register_gateway"]'), "jobs"),
    ("service id mismatch", GOOD_BACKEND, "uploads"),
    ("service id not literal", GOOD_BACKEND.replace('SERVICE_ID: Final[str] = "jobs"', 'SERVICE_ID = __name__'), "jobs"),
    ("router prefix", GOOD_BACKEND.replace('APIRouter(tags=["jobs"])',
                                           'APIRouter(prefix="/api/plugins/hermes-studiotwin")'), "jobs"),
    ("router not APIRouter", GOOD_BACKEND.replace('router = APIRouter(tags=["jobs"])', "router = object()"), "jobs"),
    ("router missing", GOOD_BACKEND.replace('router = APIRouter(tags=["jobs"])', "")
     .replace("@router.get(\"/jobs\")\n", ""), "jobs"),
])
def test_bad_backend_leaf_is_refused(spec, case, source, stem):
    with pytest.raises(L.LeafRefused):
        L.check_backend_leaf(source, stem, spec)


# ----------------------------------------------------------------------- Desktop leaves

GOOD_DESKTOP = '''import type { PluginContribution } from "../sdk"
// helper is module-private
const render = () => null

export const contribution: PluginContribution = {
  id: "studiotwin.jobs",
  area: "page",
  title: "Jobs",
  render,
}
'''


def test_good_desktop_leaf_is_accepted(spec):
    L.check_desktop_leaf(GOOD_DESKTOP, spec)


@pytest.mark.parametrize("case,source", [
    ("missing export", GOOD_DESKTOP.replace("export const contribution", "const contribution")),
    ("extra named export", GOOD_DESKTOP + "export const helper = 1\n"),
    ("default export", GOOD_DESKTOP + "export default contribution\n"),
    ("star re-export", GOOD_DESKTOP + 'export * from "./other"\n'),
    ("wrong name", GOOD_DESKTOP.replace("contribution: PluginContribution", "jobs: PluginContribution")),
    ("untyped", GOOD_DESKTOP.replace("contribution: PluginContribution =", "contribution =")),
    ("let not const", GOOD_DESKTOP.replace("export const contribution", "export let contribution")),
    ("function export", GOOD_DESKTOP.replace("export const contribution: PluginContribution = {",
                                             "export function contribution(): PluginContribution { return {")),
])
def test_bad_desktop_leaf_is_refused(spec, case, source):
    with pytest.raises(L.LeafRefused):
        L.check_desktop_leaf(source, spec)


def test_spec_change_is_refused_by_exact_match(spec):
    """A leaf built against a different export list is refused, not adapted."""
    import copy
    other = copy.deepcopy(spec)
    other["kinds"]["gateway"]["exports"] = ["register_gateway", "SERVICE_ID"]
    with pytest.raises(L.LeafRefused):
        L.check_gateway_leaf(GOOD_GATEWAY, other)
