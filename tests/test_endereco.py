"""Changing the site and game addresses from Server Config."""
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'servicos/painel'))
import endereco  # noqa: E402
import hostos  # noqa: E402

VHOST = """server {
    listen 80;
    listen [::]:80;
    server_name 192.168.0.25;
    root /var/www/heimdall;
}
"""


@pytest.fixture
def install(tmp_path, monkeypatch):
    state, env, vhost = tmp_path / 'state', tmp_path / 'heimdall.env', tmp_path / 'heimdall-nexus'
    state.mkdir()
    (state / 'installed.json').write_text(json.dumps(
        {'domain': '192.168.0.25', 'server_address': '192.168.0.25', 'tls': False, 'world': 'Midgard'}))
    env.write_text('HEIMDALL_WORLD_NAME=Midgard\nHEIMDALL_SERVER_ADDRESS=192.168.0.25\nHEIMDALL_SERVER_PORT=2456\n')
    vhost.write_text(VHOST)
    monkeypatch.setenv('HEIMDALL_STATE_DIR', str(state))
    monkeypatch.setenv('HEIMDALL_ENV_FILE', str(env))
    monkeypatch.setattr(hostos, 'WEB_CONFIG', vhost)
    monkeypatch.setattr(hostos, 'IS_WINDOWS', False)
    monkeypatch.setattr(hostos, 'copy_access', lambda source, target: None)
    calls = []
    monkeypatch.setattr(hostos, 'web_config_replace', lambda path, text: (calls.append('check'), path.write_text(text)))
    monkeypatch.setattr(hostos, 'web_reload', lambda: calls.append('reload'))
    monkeypatch.setattr(hostos, 'desktop_links', lambda url: calls.append(url))
    return state, env, vhost, calls


def test_reads_what_the_installer_recorded(install):
    now = endereco.ler()
    assert now['site'] == '192.168.0.25' and now['jogo'] == '192.168.0.25'
    assert now['pode_mudar_site'] and not now['https']


def test_changes_the_site_everywhere_it_lives(install):
    state, env, vhost, calls = install
    done = endereco.gravar({'site': 'http://meuservidor.com.br/', 'jogo': 'meuservidor.duckdns.org'})
    assert done['mudou'] == {'site': True, 'jogo': True, 'https': False} and done['url'] == 'http://meuservidor.com.br'
    assert 'server_name meuservidor.com.br;' in vhost.read_text()
    assert 'listen [::]:80;' in vhost.read_text()                      # the rest untouched
    assert calls == ['check', 'reload', 'http://meuservidor.com.br']
    assert 'HEIMDALL_SERVER_ADDRESS=meuservidor.duckdns.org\n' in env.read_text()
    assert 'HEIMDALL_SERVER_PORT=2456' in env.read_text()
    record = json.loads((state / 'installed.json').read_text())
    assert record['domain'] == 'meuservidor.com.br' and record['world'] == 'Midgard'


def test_game_address_alone_leaves_the_web_server_alone(install):
    state, env, vhost, calls = install
    done = endereco.gravar({'site': '192.168.0.25', 'jogo': '203.0.113.7'})
    assert done['mudou'] == {'site': False, 'jogo': True, 'https': False}
    assert calls == [] and vhost.read_text() == VHOST
    # Blank game address: the same as the site's.
    assert endereco.gravar({'site': '192.168.0.25', 'jogo': ''})['jogo'] == '192.168.0.25'


@pytest.mark.parametrize('bad', ['', 'meu servidor', 'a..b', '-x.com', 'x.com:80', 'x.com;rm'])
def test_refuses_what_is_not_an_address(install, bad):
    with pytest.raises(endereco.Problema):
        endereco.gravar({'site': bad})


def test_linux_https_keeps_its_domain(install):
    state = install[0]
    (state / 'installed.json').write_text(json.dumps({'domain': 'velho.com.br', 'tls': True}))
    assert not endereco.ler()['pode_mudar_site']
    with pytest.raises(endereco.Problema):
        endereco.gravar({'site': 'novo.com.br'})
    # The game address still changes.
    assert endereco.gravar({'site': 'velho.com.br', 'jogo': 'jogo.velho.com.br'})['mudou']['jogo']


def test_a_hand_edited_vhost_is_left_alone(install):
    vhost = install[2]
    vhost.write_text(VHOST.replace('server_name 192.168.0.25;', 'server_name _;'))
    with pytest.raises(endereco.Problema):
        endereco.gravar({'site': 'novo.com.br'})
    assert 'server_name _;' in vhost.read_text()


@pytest.fixture
def windows(install, tmp_path, monkeypatch):
    state, env, vhost, calls = install
    caddy = tmp_path / 'Caddyfile'
    monkeypatch.setattr(hostos, 'IS_WINDOWS', True)
    monkeypatch.setattr(hostos, 'WEB_CONFIG', caddy)
    monkeypatch.setenv('HEIMDALL_WEB_DIR', r'C:\ProgramData\HeimdallNexus\web')
    caddy.write_text(endereco.caddyfile('192.168.0.25', False, ''))
    timers = []
    monkeypatch.setattr(endereco.threading, 'Timer', lambda delay, job: type('T', (), {'start': lambda self: timers.append(job)})())
    restarts = []
    monkeypatch.setattr(hostos, 'service_action', lambda action, name, timeout=0: restarts.append((action, name)))
    return state, env, caddy, calls, timers, restarts


def test_windows_turns_https_on_with_a_domain_and_an_email(windows):
    state, env, caddy, calls, timers, restarts = windows
    assert endereco.ler()['pode_mudar_https']
    with pytest.raises(endereco.Problema):                       # an IP cannot have a certificate
        endereco.gravar({'site': '192.168.0.25', 'https': True, 'email': 'eu@exemplo.com'})
    with pytest.raises(endereco.Problema):                       # the certificate needs an e-mail
        endereco.gravar({'site': 'meuservidor.com.br', 'https': True, 'email': ''})
    done = endereco.gravar({'site': 'meuservidor.com.br', 'https': True, 'email': 'eu@exemplo.com'})
    assert done['url'] == 'https://meuservidor.com.br' and done['mudou']['site']
    text = caddy.read_text()
    assert 'meuservidor.com.br {' in text and 'email eu@exemplo.com' in text and 'auto_https off' not in text
    assert 'reload' not in calls                                  # the ordered restart below does it
    assert 'HEIMDALL_PANEL_COOKIE_SECURE=true' in env.read_text()
    assert json.loads((state / 'installed.json').read_text())['tls'] is True
    timers[0]()
    assert restarts == [('stop', 'heimdall-web'), ('restart', 'heimdall-panel'), ('start', 'heimdall-web')]
    assert endereco.ler()['email'] == 'eu@exemplo.com'


def test_windows_without_https_answers_any_name(windows):
    state, env, caddy, calls, timers, restarts = windows
    done = endereco.gravar({'site': '192.168.0.40'})
    assert ':80 {' in caddy.read_text() and done['url'] == 'http://192.168.0.40'
    assert calls == ['http://192.168.0.40'] and not timers        # only the app's buttons change


def test_linux_https_stays_as_installed(install):
    assert not endereco.ler()['pode_mudar_https']
    with pytest.raises(endereco.Problema):
        endereco.gravar({'site': '192.168.0.25', 'https': True, 'email': 'eu@exemplo.com'})


def test_the_panel_offers_it():
    executor = (ROOT / 'servicos/painel/executor.py').read_text(encoding='utf-8')
    assert "'site.endereco.gravar': v_site_endereco_gravar" in executor
    assert "'site.endereco.gravar'" in (ROOT / 'servicos/painel/app.py').read_text(encoding='utf-8')
    page = (ROOT / 'servicos/painel/modelos/server-config.html').read_text(encoding='utf-8')
    assert 'id="cartao-endereco"' in page and "api('site.endereco.gravar'" in page
