"""Pre-integration startup. No router, leaf, hosted transport or D24 issuer.

The spawn adapter is opt-in: only an inherited, private, owner-owned pipe may
supply D31 bootstrap material. Tool/initialize JSON cannot construct a gate.
The upstream sender does not yet exist; ordinary launches remain setup-only.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import select
import sqlite3
import stat
from threading import RLock
import time

from .capabilities import publication_decision, published_tools
from .host_context import HostContextGate, untrusted


class ManagedHostGate(HostContextGate):
    """Bounded S04 receiver lifecycle for one authenticated spawn generation.

    Expiry/release discards contexts AND their operations, never nonce high-water
    marks. Once the session ceiling is reached, new sessions fail closed until a
    NEW authenticated boot/key generation; no LRU eviction re-enables replays.
    """

    def __init__(self, *, clock=time.monotonic, ttl=60, max_contexts=128,
                 max_sessions=1024, **bootstrap):
        super().__init__(**bootstrap)
        if ttl <= 0 or max_contexts < 1 or max_sessions < 1:
            raise ValueError('invalid lifecycle bounds')
        self._clock, self._ttl = clock, ttl
        self._max_contexts, self._max_sessions = max_contexts, max_sessions
        self._deadlines = {}
        self._lifecycle = RLock()

    def release(self, context):
        with self._lifecycle, self._lock:
            if not self._owned(context):
                return
            self._contexts.pop(id(context), None)
            self._deadlines.pop(id(context), None)
            self._operations = {k: v for k, v in self._operations.items() if v is not context}

    def expire(self):
        with self._lifecycle:
            for identity, deadline in list(self._deadlines.items()):
                if deadline <= self._clock():
                    self.release(self._contexts.get(identity))

    def receive(self, *, arguments, metadata=None):
        with self._lifecycle:
            self.expire()
            # Check global session capacity before allocating in the S04 receiver.
            from .host_context import META_KEY
            value = metadata.get(META_KEY) if isinstance(metadata, dict) else None
            session = None
            if isinstance(value, dict):
                candidate = tuple(value.get(k) for k in ('sessionId', 'runKind', 'cronRunId'))
                if all(v is None or isinstance(v, str) for v in candidate):
                    session = candidate
            if (len(self._contexts) >= self._max_contexts or
                    (len(self._nonces) >= self._max_sessions and session not in self._nonces)):
                return untrusted('trusted-context-stale-nonce')
            result = super().receive(arguments=arguments, metadata=metadata)
            if result['trusted']:
                self._deadlines[id(result)] = self._clock() + self._ttl
            return result

    def new_operation(self, context):
        with self._lifecycle:
            self.expire()
            # Bound operations too, not merely contexts. S09 owns durable money.
            if len(self._operations) >= self._max_contexts:
                raise ValueError('operation capacity reached')
            return super().new_operation(context)

    def consume_operation(self, operation, context):
        with self._lifecycle:
            self.expire()
            return super().consume_operation(operation, context)


def gate_from_fd(fd):
    """Consume a POSIX inherited pipe, with a deadline and size ceiling.

    The parent creating/inheriting the descriptor is the local trust root, not an
    MCP field or a file named by tool data. It must be the actual trusted host
    spawn adapter when D31 is shipped. This function does not invent that sender.
    """
    if type(fd) is not int or fd < 3 or os.name != 'posix':
        raise ValueError('invalid bootstrap descriptor')
    try:
        info = os.fstat(fd)
        if (not stat.S_ISFIFO(info.st_mode) or info.st_uid != os.getuid()
                or info.st_mode & 0o077):
            raise ValueError('invalid bootstrap descriptor')
        wire = bytearray()
        deadline = time.monotonic() + 2
        while True:
            ready, _, _ = select.select([fd], [], [], max(0, deadline - time.monotonic()))
            if not ready:
                raise ValueError('bootstrap timeout')
            chunk = os.read(fd, 16385 - len(wire))
            if not chunk:
                break
            wire.extend(chunk)
            if len(wire) > 16384:
                raise ValueError('bootstrap too large')
        from .ipc import decode
        payload = decode(bytes(wire))
        if set(payload) != {'key', 'hostInstanceNonce', 'profileId', 'connectionId'}:
            raise ValueError('invalid bootstrap fields')
        key = bytes.fromhex(payload['key'])
        if len(key) != 32:
            raise ValueError('invalid bootstrap key')
        return ManagedHostGate(key=key, host_instance_nonce=payload['hostInstanceNonce'],
            profile_id=payload['profileId'], connection_id=payload['connectionId'])
    except (OSError, TypeError, KeyError, ValueError):
        raise ValueError('invalid bootstrap') from None
    finally:
        os.close(fd)


class Gateway:
    """One actual tools/call boundary; no callable hosted registry before S28."""

    def __init__(self, *, gate=None):
        self.gate = gate if gate is not None else ManagedHostGate()
        self.capabilities = None

    def initialize_host(self, payload, mac):
        # Caller is the MCP initialize middleware, not a tools/call argument.
        self.capabilities = self.gate.verify_capabilities(payload, mac)

    def tools(self):
        return published_tools(publication_decision(self.capabilities))

    def call(self, name, arguments, metadata=None):
        context = self.gate.receive(arguments=arguments, metadata=metadata)
        try:
            if context['trusted'] and context['toolName'] != name:
                return {'ok': False, 'code': 'CONTEXT_MISMATCH'}
            # A supplied invalid signature/context must not be treated as absent.
            if metadata and not context['trusted']:
                return {'ok': False, 'code': 'UNTRUSTED_CONTEXT'}
            if name not in self.tools():
                return {'ok': False, 'code': 'SETUP_ONLY'}
            if arguments != {}:
                return {'ok': False, 'code': 'INVALID_ARGUMENTS'}
            return publication_decision(self.capabilities)
        finally:
            self.gate.release(context)


def open_database(data):
    """Open private startup storage; S09 owns policy tables and migrations.

    No policy-table substitute is created and no hosted execution is possible.
    Refuse existing symlinks/non-private files rather than following them.
    """
    data = Path(data).absolute()
    data.mkdir(mode=0o700, parents=True, exist_ok=True)
    if os.name != 'posix':
        raise ValueError('owner ACL adapter unavailable')
    directory_fd = os.open(data, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        info = os.fstat(directory_fd)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
            raise ValueError('private plugin data required')
        # The pinned translator creates PLUGIN_DATA with the host umask (775 on
        # this host). Tighten the owner-owned directory before any secret write.
        os.fchmod(directory_fd, 0o700)
    finally:
        os.close(directory_fd)
    path = data / 'studiotwin.sqlite3'
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise ValueError('private database required')
    finally:
        os.close(fd)
    connection = sqlite3.connect(path)
    connection.execute('PRAGMA journal_mode=WAL')
    return connection
