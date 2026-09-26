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


def test_site_helpers_find_the_host_layer_outside_the_repository(tmp_path):
    """The site folder is a copy (for example /var/lib/heimdall-nexus/site): the
    helpers must find the code through HEIMDALL_ROOT or the default install path."""
    import os
    import shutil
    import subprocess
    site = tmp_path / 'site'
    shutil.copytree(ROOT / 'site/web', site, ignore=shutil.ignore_patterns('__pycache__'))
    probe = 'import sistema, sys; print(sistema.hostos.__file__)'
    env = {k: v for k, v in os.environ.items() if k != 'HEIMDALL_ROOT'}
    found = subprocess.run([sys.executable, '-c', probe], cwd=site, capture_output=True, text=True,
                           env={**env, 'HEIMDALL_ROOT': str(ROOT)})
    assert found.returncode == 0, found.stderr
    assert Path(found.stdout.strip()).is_relative_to(ROOT)
    source = (ROOT / 'site/web/sistema.py').read_text(encoding='utf-8')
    assert "'/opt/heimdall-nexus'" in source and "'HeimdallNexus' / 'app'" in source


def test_every_site_publication_passes_heimdall_root():
    for script in ('deploy/update.sh', 'deploy/install-web.sh'):
        text = (ROOT / script).read_text(encoding='utf-8')
        for line in [l for l in text.splitlines() if 'publicar.py"' in l and 'python3' in l]:
            assert 'HEIMDALL_ROOT=' in line, (script, line)


def test_site_helpers_skip_a_folder_they_cannot_read(tmp_path):
    import os
    import shutil
    import subprocess
    if os.geteuid() == 0 if hasattr(os, 'geteuid') else True:
        pytest.skip('needs a non-root POSIX account')
    site = tmp_path / 'site'
    site.mkdir()
    shutil.copy(ROOT / 'site/web/sistema.py', site / 'sistema.py')
    locked = tmp_path / 'locked'
    (locked / 'servicos/painel').mkdir(parents=True)
    locked.chmod(0)
    try:
        found = subprocess.run([sys.executable, '-c', 'import sistema'], cwd=site, capture_output=True, text=True,
                               env={**os.environ, 'HEIMDALL_ROOT': str(locked)})
    finally:
        locked.chmod(0o755)
    assert 'PermissionError' not in found.stderr
