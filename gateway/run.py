#!/usr/bin/env python
"""Portable mcp.json entry point; no imports from future routers or leaves."""
from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
import sys
import types

# Executing gateway/run.py sets sys.path[0] to gateway/, not package root.
# A pinned Hermes-core package ALSO has the name gateway. Resolve only this
# installed plugin's modules, without changing PYTHONPATH or importing that core.
if __package__ in (None, ''):
    package = types.ModuleType('_studiotwin_gateway')
    package.__path__ = [str(Path(__file__).resolve().parent)]
    sys.modules[package.__name__] = package
    __package__ = package.__name__

from .startup import Gateway, gate_from_fd, gate_from_file, open_database
from .ipc import LocalServer


async def main():
    from mcp.server.lowlevel import Server
    from mcp.server.stdio import stdio_server
    import mcp_types as mcp

    if sys.version_info < (3, 11):
        raise ValueError('Python 3.11 required')
    # Only a descriptor number or private bootstrap path is in the spawn
    # environment. Key/peer identity never comes from initialize or tool params.
    descriptor = os.environ.pop('STUDIOTWIN_HOST_BOOTSTRAP_FD', None)
    bootstrap_file = os.environ.pop('STUDIOTWIN_HOST_BOOTSTRAP_FILE', None)
    if descriptor is not None and bootstrap_file is not None:
        raise ValueError('ambiguous bootstrap source')
    gate = (gate_from_file(bootstrap_file) if bootstrap_file is not None else
            gate_from_fd(int(descriptor)) if descriptor is not None else None)
    gateway = Gateway(gate=gate)
    data = os.environ.get('PLUGIN_DATA')
    if not data:
        raise ValueError('private plugin data required')
    database = open_database(data)

    async def initialize_context(ctx, call_next):
        if ctx.method == 'initialize':
            params = ctx.params or {}
            metadata = params.get('_meta') or {}
            extension = metadata.get('hermes.hostCapabilities/v1') if isinstance(metadata, dict) else None
            if isinstance(extension, dict) and set(extension) == {'payload', 'mac'}:
                gateway.initialize_host(extension['payload'], extension['mac'])
        return await call_next(ctx)

    async def list_tools(ctx, params):
        return mcp.ListToolsResult(tools=[mcp.Tool(name=name,
            description='Local setup diagnostics. Hosted execution is disabled.',
            input_schema={'type': 'object', 'properties': {}, 'additionalProperties': False})
            for name in gateway.tools()])

    async def call_tool(ctx, params):
        metadata = dict(ctx.meta) if ctx.meta is not None else None
        result = gateway.call(params.name, params.arguments if params.arguments is not None else {}, metadata)
        return mcp.CallToolResult(content=[mcp.TextContent(type='text', text=json.dumps(result))],
                                  is_error=result.get('ok') is False)

    server = Server('hermes-studiotwin', version='0.1.0', on_list_tools=list_tools, on_call_tool=call_tool)
    server.middleware.append(initialize_context)
    try:
        async with LocalServer(data):
            async with stdio_server() as (read_stream, write_stream):
                await server.run(read_stream, write_stream, server.create_initialization_options())
    finally:
        database.close()


if __name__ == '__main__':
    # No raw exceptions or environment contents on stderr (they can contain
    # credentials). Fail closed with one static diagnostic and nonzero status.
    try:
        asyncio.run(main())
    except (Exception, KeyboardInterrupt):
        sys.stderr.write('StudioTwin gateway startup or transport unavailable.\n')
        sys.exit(1)
