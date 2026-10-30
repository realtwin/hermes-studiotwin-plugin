"""The pinned StudioTwin staging tools/list capture and the fixture-only additions.

Nothing here talks to StudioTwin. The capture is a verbatim copy of
`studiotwin-staging-tools-2026-10-30.json` from the design handoff; its sha256 is pinned
below and asserted by `tests/fixtures/test_fixture_foundation.py`.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

FIXTURES_ROOT = Path(__file__).resolve().parent.parent
TOOLS_LIST_PATH = FIXTURES_ROOT / "tools-list-2026-10-30.json"
TOOLS_LIST_SHA256 = "39ffcc1ecb6b16392d3f9bf1af6960aa3acf7ad87588c9ba43835d29cad50c4b"
TOOLS_LIST_SOURCE = (
    "/home/deploy/work/realtwin/studiotwin-platform/handoffs/hermes-studiotwin-plugin/"
    "studiotwin-staging-tools-2026-10-30.json"
)
EXPECTED_TOOL_COUNT = 45

# Platform tools (S rows of DESIGN §3) whose live handlers are in the API's mcp.service.ts.
PLATFORM_TOOLS = (
    "studiotwin_get_job_status",
    "studiotwin_estimate_cost",
    "studiotwin_get_credit_balance",
    "studiotwin_list_my_jobs",
    "studiotwin_cancel_job",
    "studiotwin_list_my_assets",
    "studiotwin_upload_asset",
    "studiotwin_complete_asset_upload",
    "studiotwin_resolve_asset",
)
CONCEPT_PREFIX = "studiotwin_conceptlab_"
CONCEPT_PAID_TOOLS = (
    "studiotwin_conceptlab_create_and_generate",
    "studiotwin_conceptlab_generate",
    "studiotwin_conceptlab_edit",
)

# A tool that is NOT in the capture. It models a server function released after the
# 2026-10-30 capture (DESIGN §2.3, D21): discoverable, never classified, and billable if a
# gateway ever forwarded it. The name is deliberately fixture-flavoured.
UNCLASSIFIED_TOOL: dict[str, Any] = {
    "name": "fixture-unclassified-hologram-fn",
    "description": (
        "StudioTwin generation function fixture-unclassified-hologram-fn. Costs 7 credits. "
        "(S02 fixture: appears after the 2026-10-30 capture; not in any classification.)"
    ),
    "inputSchema": {
        "type": "object",
        "properties": {"prompt": {"type": "string"}, "seed": {"type": "number"}},
        "required": ["prompt"],
        "additionalProperties": True,
    },
    "outputSchema": {
        "type": "object",
        "properties": {"hologram": {"type": "string"}},
        "required": ["hologram"],
        "additionalProperties": True,
    },
}
UNCLASSIFIED_TOOL_COST = 7

# Tool whose schema the `schema_drift` scenario mutates (same name, different hash).
SCHEMA_DRIFT_TOOL = "text-to-environment-map"


@lru_cache(maxsize=1)
def _raw_bytes() -> bytes:
    return TOOLS_LIST_PATH.read_bytes()


def capture_sha256() -> str:
    return hashlib.sha256(_raw_bytes()).hexdigest()


@lru_cache(maxsize=1)
def _capture() -> dict[str, Any]:
    return json.loads(_raw_bytes())


def capture() -> dict[str, Any]:
    """A deep copy of the whole capture document (server, instructions, tools)."""
    return copy.deepcopy(_capture())


def tools() -> list[dict[str, Any]]:
    return copy.deepcopy(_capture()["tools"])


def tool_names() -> list[str]:
    return [t["name"] for t in _capture()["tools"]]


def tool(name: str) -> dict[str, Any]:
    for t in _capture()["tools"]:
        if t["name"] == name:
            return copy.deepcopy(t)
    if name == UNCLASSIFIED_TOOL["name"]:
        return copy.deepcopy(UNCLASSIFIED_TOOL)
    raise KeyError(name)


def generation_tools() -> list[str]:
    """The 24 VP generation functions (every non-platform, non-Concept tool)."""
    return [n for n in tool_names() if n not in PLATFORM_TOOLS and not n.startswith(CONCEPT_PREFIX)]


def concept_tools() -> list[str]:
    return [n for n in tool_names() if n.startswith(CONCEPT_PREFIX)]


_FIXED_COST = re.compile(r"Costs (\d+) credits")


def fixed_cost(name: str) -> int | None:
    """The fixed credit cost stated by the live description, or None when it says to estimate."""
    match = _FIXED_COST.search(tool(name)["description"])
    return int(match.group(1)) if match else None


def schema_hash(tool_def: dict[str, Any]) -> str:
    """Stable hash of a tool's name + input/output schema (fixture helper, not S08's policy)."""
    material = {
        "name": tool_def["name"],
        "inputSchema": tool_def.get("inputSchema"),
        "outputSchema": tool_def.get("outputSchema"),
    }
    return hashlib.sha256(json.dumps(material, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def drifted(tool_def: dict[str, Any]) -> dict[str, Any]:
    """A copy of `tool_def` with an extra required input: same name, different schema hash."""
    out = copy.deepcopy(tool_def)
    schema = out["inputSchema"]
    schema.setdefault("properties", {})["fixtureDriftMode"] = {
        "type": "string",
        "enum": ["a", "b"],
        "description": "S02 schema-drift fixture field.",
    }
    schema["required"] = sorted(set(schema.get("required", [])) | {"fixtureDriftMode"})
    return out
