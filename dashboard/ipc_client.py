"""Authenticated dashboard client for S05's literal-loopback TCP protocol.

The approved S05 API is Channel/read_descriptor (not LocalClient or
startup.read_ipc_descriptor). Reuse those actual MAC/nonce/schema primitives.
No SO_PEERCRED, named pipe, hosted connection, retry or consent is implied.
One retained client is owned by the backend per boot; reconnects retain its
Channel. Replaced descriptors fail closed and require lifecycle integration.
"""
from __future__ import annotations

import asyncio
import importlib
from pathlib import Path
import sys
import types

# Core also has a package named gateway. Load this package from its exact local
# root under a private name; never alter sys.path or import core's gateway.
_GATEWAY_NAME = '_hermes_studiotwin_gateway_v1'
_GATEWAY_ROOT = Path(__file__).resolve().parents[1] / 'gateway'
if _GATEWAY_NAME not in sys.modules:
    _package = types.ModuleType(_GATEWAY_NAME)
    _package.__path__ = [str(_GATEWAY_ROOT)]
    sys.modules[_GATEWAY_NAME] = _package
elif list(sys.modules[_GATEWAY_NAME].__path__) != [str(_GATEWAY_ROOT)]:
    raise ImportError('StudioTwin package identity mismatch.')
ipc = importlib.import_module(_GATEWAY_NAME + '.ipc')
redaction = importlib.import_module(_GATEWAY_NAME + '.redaction')
classification = importlib.import_module(_GATEWAY_NAME + '.classification')


class DashboardIpcClient:
    """Backend-owned scope binding/registry callbacks, never browser inputs.

    The existing S05 setup-only listener authenticates the zero scope using
    transport scope 'setup'. Other scopes use their exact digest/generation;
    they require a future authenticated scoped dispatcher (S28). No principal
    is issued here. Calls are serialized to preserve monotonic receive order.
    """
    def __init__(self, data, *, scope_id, generation, current_binding,
                 sensitive_values, catalog=None, windows_files=None, timeout=3):
        failed = False
        try:
            redaction._binding(scope_id,generation)
            if (not callable(current_binding) or not callable(sensitive_values) or
                    type(timeout) not in (int,float) or not 0 < timeout <= 30 or
                    (catalog is not None and type(catalog) is not classification.Classification)):
                raise ValueError
            self.scope_id, self.generation = scope_id, generation
            self._current, self._sensitive = current_binding, sensitive_values
            self._catalog = catalog
            self._path = Path(data) / 'gateway-ipc.json'
            self._windows = windows_files
            self._descriptor = ipc.read_descriptor(self._path, windows=windows_files)
            self._channel = ipc.Channel(bytes.fromhex(self._descriptor['key']),
                scope='setup' if (scope_id,generation)==('0'*64,0) else scope_id,
                generation=generation)
            self._lock, self._timeout = asyncio.Lock(), timeout
            self._check_current()
        except (ValueError,TypeError,OSError,KeyError):
            failed = True
        if failed:
            raise redaction.BoundaryRefused()

    def __repr__(self):
        return '<DashboardIpcClient>'

    def _check_current(self):
        if self._current() != (self.scope_id,self.generation):
            raise redaction.BoundaryRefused()

    def _secrets(self):
        # Never return/log this registry. Include the descriptor capability too.
        return tuple(self._sensitive()) + (self._descriptor['key'],)

    def _validate(self, ref, value):
        return redaction.validate_mediated_v1(ref,value,scope_id=self.scope_id,
            generation=self.generation,sensitive_values=self._secrets())

    def _form_binding(self, params, payload=None):
        tool, digest = params['tool'], params['schemaHash']
        row = classification.RELEASE['tools'].get(tool)
        if row is None or row['schemaHash'] != digest:
            raise redaction.BoundaryRefused()
        if self._catalog is not None:
            self._catalog.input_schema(tool,digest,scope_id=self.scope_id,
                generation=self.generation,sensitive_values=self._secrets())
        if payload is not None and (payload['tool'] != tool or payload['schemaHash'] != digest
                or payload['inputSchema'] != redaction._thaw(row['inputSchema'])):
            raise redaction.BoundaryRefused()

    async def request(self, method, params):
        """Return ONLY the validated COMPLETE immutable IpcResponseV1.

        Failures, cancellation and timeouts never replay. A late rotated-scope
        reply is quarantined, not cached or forwarded. No raw exception chains.
        """
        failed = False
        result = None
        try:
            async with self._lock:
                self._check_current()
                if ipc.read_descriptor(self._path,windows=self._windows) != self._descriptor:
                    raise redaction.BoundaryRefused()
                if method == 'capabilities.inputSchema':
                    self._form_binding(params)
                if method == 'operations.quote':
                    self._validate('dashboard#/components/schemas/QuoteRequestV1',params)
                    if self._catalog is None:
                        raise redaction.BoundaryRefused()
                    self._catalog.candidate_inputs(params['tool'],params['schemaHash'],params['inputs'],
                        scope_id=self.scope_id,generation=self.generation,sensitive_values=self._secrets())
                request = self._channel.request(method,params)
                try:
                    request = self._validate('host_gateway#/$defs/IpcRequestV1',request).to_json()
                    frame = await asyncio.wait_for(self._exchange(request),self._timeout)
                    self._check_current()
                    response = self._channel.accept_response(frame)
                    result = self._validate('host_gateway#/$defs/IpcResponseV1',response)
                    if response['ok'] and method == 'capabilities.inputSchema':
                        # CF8 is not satisfied by envelope JSON Schema alone.
                        classification.validate_input_schema_response_v1(response,wrapped=True,
                            scope_id=self.scope_id,generation=self.generation,sensitive_values=self._secrets())
                        self._form_binding(params,response['result']['payload'])
                    self._check_current()
                finally:
                    self._channel.pending.pop(request['requestId'],None)
        except (ValueError,TypeError,OSError,KeyError,asyncio.TimeoutError):
            failed = True
        if failed:
            raise redaction.BoundaryRefused()
        return result

    async def _exchange(self, request):
        # read_descriptor has already required a literal loopback address. Check
        # again immediately before connect: no hostname/DNS/redirect escape.
        host = ipc.local_address(self._descriptor['host'])
        reader, writer = await asyncio.open_connection(host,self._descriptor['port'],limit=ipc.MAX_BYTES+1)
        try:
            ipc.local_address(writer.get_extra_info('peername')[0])
            writer.write(ipc.encode(request)+b'\n')
            await writer.drain()
            line = await reader.readline()
            if not line.endswith(b'\n') or len(line)>ipc.MAX_BYTES:
                raise redaction.BoundaryRefused()
            return ipc.decode(line)
        finally:
            writer.close()
            await writer.wait_closed()
