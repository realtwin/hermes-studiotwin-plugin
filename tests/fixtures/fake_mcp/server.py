"""MCP binding for `FakeStudioTwin` (mcp==2.3.0 low-level `Server`).

Usage (in-process, no network):

    from tests.fixtures.fake_mcp import FakeStudioTwin, build_server, scenario
    from mcp.client import Client

    fake = FakeStudioTwin(scenario("normal"))
    async with Client(build_server(fake), mode="legacy") as client:
        ...

`mode="legacy"` runs the JSON-RPC stream loop with the initialize handshake (what pinned
Hermes core uses); `mode="auto"` exercises the 2026-07-28 direct path. Over HTTP use
`fake_mcp.http.serve(...)`.

Results are typed MCP models: the mcp==2.3.0 server runner re-validates every result in both
protocol eras, so a protocol-invalid content block cannot be emitted through it. Malformed
fixtures are therefore malformed *content* (HTML text, truncated JSON, schema-violating
structuredContent, empty content), not malformed protocol frames.
"""

from __future__ import annotations

import warnings
from typing import Any

import anyio
import mcp_types as types
from mcp.server.lowlevel import NotificationOptions, Server
from mcp.shared.exceptions import MCPDeprecationWarning, MCPError

from . import catalog
from .state import FakeStudioTwin, Hang, ProtocolFailure, ToolResponse

MAX_CREDITS_CAPABILITY = "studiotwin.paidSubmissionMaxCreditsV1"


class FakeStudioTwinServer(Server[Any]):
    """Low-level server whose capabilities reflect the fake's scenario."""

    def __init__(self, fake: FakeStudioTwin):
        capture = catalog.capture()["server"]
        super().__init__(
            capture["name"],
            version=capture["version"],
            title=capture.get("title"),
            instructions=fake.instructions(),
            on_list_tools=self._list_tools,
            on_call_tool=self._call_tool,
        )
        self.fake = fake

    def get_capabilities(self, notification_options=None, experimental_capabilities=None, extensions=None, *,
                         protocol_version=None):  # type: ignore[override]
        experimental = dict(experimental_capabilities or {})
        if self.fake.scenario.advertise_max_credits:
            experimental[MAX_CREDITS_CAPABILITY] = {"field": "maxCredits", "rejectCode": "PRICE_EXCEEDS_MAX"}
        notification_options = notification_options or NotificationOptions(
            tools_changed=self.fake.scenario.unclassified_tool_after_calls is not None)
        return super().get_capabilities(notification_options, experimental or None, extensions,
                                        protocol_version=protocol_version)

    async def _list_tools(self, ctx, params) -> types.ListToolsResult:
        return types.ListToolsResult.model_validate({"tools": self.fake.visible_tools()})

    async def _call_tool(self, ctx, params: types.CallToolRequestParams) -> types.CallToolResult:
        fake = self.fake
        if fake.scenario.call_delay_seconds:
            await anyio.sleep(fake.scenario.call_delay_seconds)
        was_visible = fake.unclassified_visible()
        try:
            outcome = fake.call(params.name, params.arguments)
        except ProtocolFailure as exc:
            raise MCPError(exc.code, exc.message, exc.data) from None
        if isinstance(outcome, Hang):
            await anyio.sleep(outcome.seconds)
            raise MCPError(-32603, "fake upstream hang elapsed")
        if not was_visible and fake.unclassified_visible():
            try:
                await ctx.session.send_tool_list_changed()
            except Exception:  # noqa: BLE001 - modern sessions deliver list changes via subscriptions
                pass
        await _emit_side_channels(ctx, outcome)
        return types.CallToolResult.model_validate(to_wire(outcome))


async def _emit_side_channels(ctx, outcome: ToolResponse) -> None:
    for i, message in enumerate(outcome.progress):
        await ctx.session.report_progress(float(i + 1), float(len(outcome.progress)), message)
    for data in outcome.logs:
        # notifications/message is deprecated in 2026-07-28 but still a real upstream channel
        # that mediation must cover, so the fake keeps emitting it.
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", MCPDeprecationWarning)
            await ctx.session.send_log_message("info", data, "studiotwin-fake", related_request_id=ctx.request_id)


def to_wire(resp: ToolResponse) -> dict[str, Any]:
    """The JSON-RPC `result` object for a tools/call."""
    if resp.content is not None:
        content = resp.content
    elif resp.text is not None:
        content = [{"type": "text", "text": resp.text}]
    else:
        content = []
    out: dict[str, Any] = {"content": content, "isError": bool(resp.is_error)}
    if resp.structured is not None:
        out["structuredContent"] = resp.structured
    if resp.meta:
        out["_meta"] = resp.meta
    return out


def build_server(fake: FakeStudioTwin | None = None) -> FakeStudioTwinServer:
    return FakeStudioTwinServer(fake or FakeStudioTwin())
