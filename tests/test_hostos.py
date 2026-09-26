"""The host layer: Linux keeps its behavior, and the Windows executor channel is sound."""
import json
import socket
import socketserver
import sys
import threading
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'servicos/painel'))
import hostos  # noqa: E402
from hostos import _channel  # noqa: E402


class Echo(socketserver.StreamRequestHandler):
    def handle(self):
        self.wfile.write(self.rfile.readline().upper())


@pytest.fixture
def channel(tmp_path):
    key = tmp_path / 'executor.key'
    key.write_text('a' * 64)
    server = _channel.LoopbackExecutorServer('127.0.0.1:0', Echo, key)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f'127.0.0.1:{server.server_address[1]}', key, tmp_path
    server.shutdown()
    server.server_close()


def test_channel_serves_a_client_that_knows_the_secret(channel):
    address, key, _ = channel
    with _channel.connect(address, 5, key) as connection:
        connection.sendall(b'ping\n')
        assert connection.makefile('rb').readline() == b'PING\n'


def test_channel_refuses_a_client_with_another_secret(channel):
    address, _, folder = channel
    wrong = folder / 'wrong.key'
    wrong.write_text('b' * 64)
    with pytest.raises((ConnectionError, OSError)):
        with _channel.connect(address, 5, wrong) as connection:
            connection.sendall(b'ping\n')
            if not connection.makefile('rb').readline():
                raise ConnectionError('closed')


def test_channel_never_sends_the_secret(channel):
    address, key, _ = channel
    host, port = address.split(':')
    with socket.create_connection((host, int(port)), timeout=5) as raw:
        greeting = _channel.readline(raw)
        assert greeting.startswith(_channel.GREETING)
        assert key.read_bytes().strip() not in greeting


def test_client_refuses_an_impostor_that_took_the_port(tmp_path):
    key = tmp_path / 'executor.key'
    key.write_text('a' * 64)
    impostor = socket.socket()
    impostor.bind(('127.0.0.1', 0))
    impostor.listen(1)
    port = impostor.getsockname()[1]
    seen = []

    def pretend():
        connection, _ = impostor.accept()
        with connection:
            connection.sendall(_channel.GREETING + b'0' * 32 + b'\n')
            seen.append(_channel.readline(connection))
            connection.sendall(b'f' * 64 + b'\n')

    thread = threading.Thread(target=pretend, daemon=True)
    thread.start()
    with pytest.raises(ConnectionError):
        _channel.connect(f'127.0.0.1:{port}', 5, key)
    thread.join(5)
    impostor.close()
    assert seen and b'a' * 64 not in seen[0]


def test_channel_only_listens_on_loopback(tmp_path):
    key = tmp_path / 'executor.key'
    key.write_text('a' * 64)
    with pytest.raises(ValueError):
        _channel.LoopbackExecutorServer('0.0.0.0:0', Echo, key)


def test_short_keys_are_refused(tmp_path):
    key = tmp_path / 'executor.key'
    key.write_text('short')
    with pytest.raises(OSError):
        _channel.read_key(key)


def test_environment_overrides_the_default_path(monkeypatch, tmp_path):
    monkeypatch.setenv('HEIMDALL_VALHEIM_DIR', str(tmp_path))
    assert hostos.env_path('HEIMDALL_VALHEIM_DIR') == tmp_path
    monkeypatch.delenv('HEIMDALL_VALHEIM_DIR')
    assert hostos.env_path('HEIMDALL_VALHEIM_DIR') == Path(hostos.DEFAULTS['HEIMDALL_VALHEIM_DIR'])


@pytest.mark.skipif(hostos.IS_WINDOWS, reason='Linux defaults')
def test_linux_defaults_are_unchanged():
    assert hostos.DEFAULTS['HEIMDALL_VALHEIM_DIR'] == '/srv/valheim'
    assert hostos.DEFAULTS['HEIMDALL_PANEL_SOCKET'] == '/run/heimdall-panel/executor.sock'
    assert hostos.PYTHON == '/usr/bin/python3'
    assert hostos.STEAMCMD == 'steamcmd.sh'


def test_exclusive_lock_is_exclusive(tmp_path):
    path = tmp_path / 'maintenance.lock'
    first = hostos.exclusive_lock(path)
    try:
        with pytest.raises(BlockingIOError):
            hostos.exclusive_lock(path)
    finally:
        first.close()
    hostos.exclusive_lock(path).close()


def test_windows_module_compiles_and_declares_the_same_api():
    source = (ROOT / 'servicos/painel/hostos/_windows.py').read_text(encoding='utf-8')
    compile(source, '_windows.py', 'exec')
    linux = (ROOT / 'servicos/painel/hostos/_linux.py').read_text(encoding='utf-8')
    public = {line.split('(')[0][4:] for line in linux.splitlines()
              if line.startswith('def ') and not line.startswith('def _')}
    public |= {'ExecutorServer', 'DEFAULTS', 'PYTHON', 'STEAMCMD', 'GAME_EXECUTABLE', 'GIT_SEARCH_PATH'}
    missing = {name for name in public
               if f'def {name}(' not in source and f'class {name}(' not in source
               and f'\n{name} = ' not in source}
    assert not missing
    assert json.loads(json.dumps(sorted(public)))
