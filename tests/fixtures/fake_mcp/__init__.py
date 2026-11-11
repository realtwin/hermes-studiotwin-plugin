"""Reusable fake StudioTwin MCP fixtures (S02). Test-only; never contacts StudioTwin.

    catalog        pinned 45-tool capture, unclassified + schema-drift helpers
    scenarios      Scenario knobs and the named MODES registry
    state          FakeStudioTwin: deterministic jobs/wallet/assets/uploads/Concepts
    server         build_server(fake) -> mcp low-level Server (in-process Client or stdio/HTTP)
    http           serve(fake) -> loopback Streamable HTTP + fake object store
    canaries       secret canary registry and leak scanner
    concept_inputs port of the API Concept effective-input transform
"""

from .catalog import EXPECTED_TOOL_COUNT, TOOLS_LIST_SHA256, UNCLASSIFIED_TOOL
from .scenarios import MODES, Mode, Scenario, mode, scenario
from .server import build_server, to_wire
from .state import FakeStudioTwin, Hang, ProtocolFailure, ToolResponse

__all__ = [
    "EXPECTED_TOOL_COUNT", "TOOLS_LIST_SHA256", "UNCLASSIFIED_TOOL", "MODES", "Mode", "Scenario", "mode",
    "scenario", "build_server", "to_wire", "FakeStudioTwin", "Hang", "ProtocolFailure", "ToolResponse",
]
