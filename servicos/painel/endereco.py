"""The site's address and the game's connection address, changed from Server Config.

The installer asked for both once; they end up in several places, which this
module keeps in step:

- heimdall.env, HEIMDALL_SERVER_ADDRESS: what the site shows players (through
  the status feed, on its next run);
- the installation record (installed.json): domain, address and HTTPS;
- the web server: Nginx's server_name on Linux, the site line of the Caddyfile
  on Windows with HTTPS (without it Caddy answers any name); each is tested by
  the server itself before it replaces the running configuration;
- on Windows, the desktop app's Open the panel and Open the website buttons.

The site's own link (the identity's url) is republished by the executor.
HTTPS stays as it was installed. On Linux, a site with HTTPS keeps its domain:
the certificate belongs to that name, and a new one is requested by Certbot,
which is not done from here yet.
"""
from __future__ import annotations

import ipaddress
import json
import os
import re
import sys
from pathlib import Path

import codigos
import hostos

HOST = re.compile(r'^[a-z0-9.-]{1,253}$')


class Problema(Exception):
    """A refusal to show the person as it is."""


def _state_file() -> Path:
    return hostos.env_path('HEIMDALL_STATE_DIR') / 'installed.json'


def _env_file() -> Path:
    return hostos.env_path('HEIMDALL_ENV_FILE')


def _record() -> dict:
    try:
        return json.loads(_state_file().read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def _env_value(name: str) -> str:
    try:
        for line in _env_file().read_text(encoding='utf-8').splitlines():
            key, sep, value = line.partition('=')
            if sep and key.strip() == name:
                value = value.strip()
                return value[1:-1] if len(value) > 1 and value[0] == value[-1] and value[0] in '"\'' else value
    except OSError:
        pass
    return ''


def ler() -> dict:
    record = _record()
    tls = bool(record.get('tls'))
    windows = sys.platform == 'win32'
    domain = str(record.get('domain') or '')
    motivo = ''
    if not domain:
        motivo = 'Esta instalação não guardou o endereço do site; ele só muda reinstalando.'
    elif tls and not windows:
        motivo = ('O site usa HTTPS, e o certificado vale só para ' + domain +
                  '. Trocar o domínio com HTTPS no Linux ainda não é feito pelo painel.')
    return {'site': domain, 'jogo': _env_value('HEIMDALL_SERVER_ADDRESS') or str(record.get('server_address') or domain),
            'https': tls, 'windows': windows, 'pode_mudar_site': not motivo, 'motivo_site': motivo}


def _host(value, campo: str) -> str:
    host = str(value or '').strip().lower().rstrip('.')
    for prefix in ('http://', 'https://'):
        if host.startswith(prefix):
            host = host[len(prefix):]
    host = host.split('/', 1)[0]
    if not host or not HOST.fullmatch(host) or '..' in host or host.startswith(('-', '.')):
        raise Problema(codigos.com_codigo('HN-CFG-010', f'{campo}: use um domínio ou um IP, como meuservidor.com.br ou 192.168.0.25'))
    return host


def _is_ip(host: str) -> bool:
    try:
        ipaddress.ip_address(host)
        return True
    except ValueError:
        return False


def validar(dados: dict, atual: dict) -> tuple[str, str]:
    """(site, jogo) as they will be saved; raises Problema otherwise."""
    site = _host(dados.get('site', atual['site']), 'Endereço do site')
    jogo = _host(dados.get('jogo') or site, 'Endereço de conexão do jogo')
    if site != atual['site']:
        if not atual['pode_mudar_site']:
            raise Problema(codigos.com_codigo('HN-CFG-010', atual['motivo_site']))
        if atual['https'] and (_is_ip(site) or '.' not in site or site == 'localhost'):
            raise Problema(codigos.com_codigo(
                'HN-CFG-010', 'com HTTPS, o endereço do site precisa ser um domínio, como meuservidor.com.br'))
    return site, jogo


def nginx_server_name(text: str, old: str, new: str) -> str:
    """The vhost with its server_name changed; the rest untouched."""
    pattern = re.compile(r'^(\s*server_name\s+)' + re.escape(old) + r'(\s*;)', re.M)
    updated, count = pattern.subn(lambda m: m.group(1) + new + m.group(2), text)
    if not count:
        raise Problema(codigos.com_codigo('HN-CFG-010', f'a configuração do Nginx não tem server_name {old}; '
                                                        'ela foi mudada à mão e o painel não mexe nela'))
    return updated


def caddy_site(text: str, old: str, new: str) -> str:
    """The Caddyfile with its site block renamed (only with HTTPS; without it the site is :80)."""
    pattern = re.compile(r'^' + re.escape(old) + r'(\s*\{)', re.M)
    updated, count = pattern.subn(lambda m: new + m.group(1), text)
    if count != 1:
        raise Problema(codigos.com_codigo('HN-CFG-010', f'o Caddyfile não tem o site {old}; '
                                                        'ele foi mudado à mão e o painel não mexe nele'))
    return updated


def _apply_site(old: str, new: str, tls: bool) -> None:
    path = hostos.WEB_CONFIG
    try:
        text = path.read_text(encoding='utf-8')
        if hostos.IS_WINDOWS:
            updated = caddy_site(text, old, new) if tls else text
        else:
            updated = nginx_server_name(text, old, new)
        if updated != text:
            hostos.web_config_replace(path, updated)
            hostos.web_reload()
        hostos.desktop_links(('https://' if tls else 'http://') + new)
    except (OSError, ValueError) as error:
        raise Problema(codigos.com_codigo('HN-CFG-010', str(error))) from error


def _write_env(name: str, value: str) -> None:
    path = _env_file()
    lines = path.read_text(encoding='utf-8').splitlines(keepends=True)
    line = f'{name}={value}\n'
    for index, current in enumerate(lines):
        if current.partition('=')[0].strip() == name:
            lines[index] = line
            break
    else:
        if lines and not lines[-1].endswith('\n'):
            lines[-1] += '\n'
        lines.append(line)
    _replace(path, ''.join(lines))


def _replace(path: Path, text: str) -> None:
    """Same file, same permissions: written beside it and moved over it."""
    temporary = path.with_name(path.name + '.novo')
    temporary.write_text(text, encoding='utf-8')
    hostos.copy_access(path, temporary)
    os.replace(temporary, path)


def gravar(dados: dict) -> dict:
    """Applies the new addresses; returns what changed, for the executor's next steps."""
    atual = ler()
    site, jogo = validar(dados, atual)
    changed = {'site': site != atual['site'], 'jogo': jogo != atual['jogo']}
    if changed['site']:
        # The web server first: if it refuses the new name, nothing else changed.
        _apply_site(atual['site'], site, atual['https'])
    if changed['jogo']:
        _write_env('HEIMDALL_SERVER_ADDRESS', jogo)
    if any(changed.values()):
        record = _record()
        if record:
            record.update(domain=site, server_address=jogo)
            _replace(_state_file(), json.dumps(record, ensure_ascii=False, indent=2) + '\n')
    scheme = 'https://' if atual['https'] else 'http://'
    return {'site': site, 'jogo': jogo, 'mudou': changed, 'url': scheme + site}
