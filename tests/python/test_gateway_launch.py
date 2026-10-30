"""S05 real pre-router stdio launch and authenticated dispatch boundary."""
import importlib.util
import json
import os
from pathlib import Path
import select
import subprocess
import sys
import types

import pytest

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
pkg = types.ModuleType('s05_launch')
pkg.__path__ = [str(ROOT / 'gateway')]
sys.modules[pkg.__name__] = pkg
spec = importlib.util.spec_from_file_location('s05_launch.startup', ROOT / 'gateway/startup.py')
startup = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = startup
spec.loader.exec_module(startup)


def signed(gate, tool='studiotwin_setup_status', nonce=0, session='session-a'):
    from s05_launch.host_context import META_KEY
    import hashlib
    import hmac
    value = dict(hostInstanceNonce='H' * 43, profileId='profile-a', connectionId='local',
                 sessionId=session, runKind='interactive', cronRunId=None,
                 toolName=tool, turnId='turn-a', toolCallId=f'call-{nonce}', callNonce=nonce)
    value['mac'] = hmac.new(b'k' * 32, b'trusted-tool-context-v1\0' +
        json.dumps(value, sort_keys=True, separators=(',', ':')).encode(), hashlib.sha256).hexdigest()
    return {META_KEY: value}


def managed(**kw):
    return startup.ManagedHostGate(key=b'k' * 32, host_instance_nonce='H' * 43,
        profile_id='profile-a', connection_id='local', **kw)


def test_dispatch_binds_actual_name_and_releases_context():
    gate = managed()
    app = startup.Gateway(gate=gate)
    result = app.call('studiotwin_setup_status', {}, signed(gate, tool='text-to-material'))
    assert result == {'ok': False, 'code': 'CONTEXT_MISMATCH'}
    assert not gate._contexts and not gate._operations
    assert app.call('text-to-material', {}, signed(gate, tool='text-to-material', nonce=1)) == {
        'ok': False, 'code': 'SETUP_ONLY'}
    assert not gate._contexts


def test_setup_only_even_with_forged_handshake_or_principal():
    app = startup.Gateway()
    assert app.tools() == ['studiotwin_setup_status']
    assert app.call('text-to-material', {'principalIdentity': 'proven'}, {})['ok'] is False
    assert app.call('studiotwin_setup_status', {'key': 'x', 'hostCapabilities': {}}, {}) == {
        'ok': False, 'code': 'INVALID_ARGUMENTS'}
    result = app.call('studiotwin_setup_status', {}, {})
    assert result['principalIdentity'] == 'unproven'
    assert result['publishedTiers'] == ['setup']


def test_lifecycle_expiry_and_release_keep_replay_highwater():
    now = [0.0]
    gate = managed(clock=lambda: now[0], ttl=2, max_contexts=1, max_sessions=2)
    ctx = gate.receive(arguments={}, metadata=signed(gate))
    op = gate.new_operation(ctx)
    now[0] = 3
    gate.expire()
    assert not gate.consume_operation(op, ctx)
    assert not gate._contexts and not gate._operations
    assert gate.receive(arguments={}, metadata=signed(gate))['trusted'] is False
    ctx = gate.receive(arguments={}, metadata=signed(gate, nonce=1))
    gate.release(ctx)
    assert gate.receive(arguments={}, metadata=signed(gate, nonce=1))['trusted'] is False
    assert len(gate._nonces) == 1


def test_context_and_session_limits_fail_closed_without_eviction():
    gate = managed(max_contexts=1, max_sessions=1)
    ctx = gate.receive(arguments={}, metadata=signed(gate))
    assert gate.receive(arguments={}, metadata=signed(gate, nonce=1))['trusted'] is False
    gate.release(ctx)
    assert gate.receive(arguments={}, metadata=signed(gate, session='other'))['trusted'] is False
    assert gate.receive(arguments={}, metadata=signed(gate))['trusted'] is False
    assert gate.receive(arguments={}, metadata=signed(gate, nonce=1))['trusted'] is True


def test_bootstrap_only_inherited_private_pipe():
    read, write = os.pipe()
    payload = dict(key='6b' * 32, hostInstanceNonce='H' * 43, profileId='profile-a', connectionId='local')
    os.write(write, json.dumps(payload).encode())
    os.close(write)
    gate = startup.gate_from_fd(read)
    assert gate.receive(arguments={}, metadata=signed(gate))['trusted'] is True
    with pytest.raises(OSError):
        os.fstat(read)
    with pytest.raises(ValueError, match='bootstrap'):
        startup.gate_from_fd(1)


@pytest.mark.parametrize('authenticated', [False, True])
def test_launch_translated_manifest_real_stdio(tmp_path, authenticated):
    from hermes_cli.agent_plugins import load_agent_plugin
    from tools.mcp_tool_config import _build_safe_env
    package = load_agent_plugin(ROOT, tmp_path / 'data')
    server = package.mcp_servers['studiotwin']
    env = _build_safe_env(server['env'])
    env['PATH'] = str(Path(sys.executable).parent) + os.pathsep + os.environ['PATH']
    env['PYTHONDONTWRITEBYTECODE'] = '1'
    # A different core gateway package is on PYTHONPATH; the entry point must not import it.
    spawn = {}
    if authenticated:
        read, write = os.pipe()
        os.write(write, json.dumps(dict(key='6b' * 32, hostInstanceNonce='H' * 43,
            profileId='profile-a', connectionId='local')).encode())
        os.close(write)
        env['STUDIOTWIN_HOST_BOOTSTRAP_FD'] = str(read)
        spawn['pass_fds'] = (read,)
    process = subprocess.Popen([server['command'], *server['args']], cwd=server['cwd'],
        env=env, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, **spawn)
    if authenticated:
        os.close(read)
    def send(message):
        process.stdin.write(json.dumps(message) + '\n')
        process.stdin.flush()
    def receive():
        ready, _, _ = select.select([process.stdout], [], [], 15)
        assert ready, 'stdio response timed out'
        line = process.stdout.readline()
        assert line, 'gateway exited before responding'
        return json.loads(line)
    try:
        send({'jsonrpc': '2.0', 'id': 1, 'method': 'initialize', 'params': {
            'protocolVersion': '2025-03-26', 'capabilities': {},
            'clientInfo': {'name': 's05-real-wire', 'version': '1'}}})
        assert receive()['result']['serverInfo']['name'] == 'hermes-studiotwin'
        send({'jsonrpc': '2.0', 'method': 'notifications/initialized'})
        send({'jsonrpc': '2.0', 'id': 2, 'method': 'tools/list'})
        tools = receive()['result']['tools']
        assert [t['name'] for t in tools] == ['studiotwin_setup_status']
        send({'jsonrpc': '2.0', 'id': 3, 'method': 'tools/call', 'params': {
            'name': 'studiotwin_setup_status', 'arguments': {}}})
        result = receive()['result']
        assert not result.get('isError', False)
        assert json.loads(result['content'][0]['text'])['publishedTiers'] == ['setup']
        send({'jsonrpc': '2.0', 'id': 4, 'method': 'tools/call', 'params': {
            'name': 'text-to-material', 'arguments': {}}})
        assert receive()['result']['isError'] is True
        if authenticated:
            send({'jsonrpc': '2.0', 'id': 5, 'method': 'tools/call', 'params': {
                'name': 'studiotwin_setup_status', 'arguments': {}, '_meta': signed(None, tool='text-to-material')}})
            reply = receive()
            assert 'result' in reply, reply
            result = reply['result']
            assert result['isError'] is True
            assert json.loads(result['content'][0]['text'])['code'] == 'CONTEXT_MISMATCH'
            send({'jsonrpc': '2.0', 'id': 6, 'method': 'tools/call', 'params': {
                'name': 'studiotwin_setup_status', 'arguments': {}, '_meta': signed(None, nonce=1)}})
            result = receive()['result']
            assert not result['isError']
            assert json.loads(result['content'][0]['text'])['publishedTiers'] == ['setup']
        assert not (ROOT / 'gateway/router.py').exists()
        assert not (ROOT / 'gateway/leaves').exists()
    finally:
        process.stdin.close()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait()
        stderr = process.stderr.read()
        assert process.returncode == 0, stderr
        process.stdout.close()
        process.stderr.close()
    assert (tmp_path / 'data/studiotwin.sqlite3').exists()
