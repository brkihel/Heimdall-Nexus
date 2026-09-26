"""Heimdall's Windows services: definitions, registration and accounts.

Each service is a copy of WinSW (MIT, pinned by hash) next to its XML file in
BASE/services. Services that need no privilege run as their own virtual
account (NT SERVICE\\<name>), which has no password and no rights beyond the
folder permissions the installer grants.
"""
from __future__ import annotations

import hashlib
import shutil
import subprocess
import time
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

WINSW_URL = 'https://github.com/winsw/winsw/releases/download/v2.12.0/WinSW.NET4.exe'
WINSW_SHA256 = '923111c7142b3dc783a3c722b19b8a21bcb78222d7a136ac33f0ca8a29f4cb66'
SYSTEM = 'LocalSystem'


@dataclass(frozen=True)
class Service:
    name: str
    title: str
    description: str
    command: tuple[str, ...]          # arguments after `python -X utf8 run.py`
    account: str = 'virtual'          # 'virtual' (NT SERVICE\name) or SYSTEM
    depends: tuple[str, ...] = ()
    start: str = 'Automatic'          # Automatic or Manual
    stop_seconds: int = 30
    restart_on_failure: bool = True
    own_log: bool = False             # the program keeps its own log file
    env: dict = field(default_factory=dict)
    working_directory: str = ''       # relative to the app root


def definitions(game_autostart: bool = False) -> list[Service]:
    return [
        Service('heimdall-executor', 'Heimdall Nexus - executor',
                'The only privileged part of the Heimdall panel: a fixed list of actions.',
                ('servicos/painel/executor.py',), account=SYSTEM),
        Service('heimdall-panel', 'Heimdall Nexus - panel (Jarl)',
                'The Heimdall administration panel, on 127.0.0.1:8791.',
                ('-m', 'uvicorn', 'app:app', '--host', '127.0.0.1', '--port', '8791',
                 '--proxy-headers', '--forwarded-allow-ips=127.0.0.1'),
                depends=('heimdall-executor',), working_directory='servicos/painel'),
        Service('heimdall-valheim', 'Heimdall Nexus - Valheim server',
                'Valheim dedicated server (Heimdall Nexus).',
                ('deploy/windows/launcher-windows.py',),
                start='Automatic' if game_autostart else 'Manual', stop_seconds=150,
                own_log=True, env={'HEIMDALL_LOG_DIR': '{VALHEIM}\\logs', 'HEIMDALL_RUN_DIR': '{VALHEIM}\\run'}),
        Service('heimdall-jobs', 'Heimdall Nexus - periodic jobs',
                'Public status, saga feed and Jarl scheduled tasks.',
                ('deploy/windows/jobs.py', 'system'), account=SYSTEM),
        Service('heimdall-sagas-jobs', 'Heimdall Nexus - Sagas jobs',
                'Optional Heimdall Sagas import, stories and map.',
                ('deploy/windows/jobs.py', 'sagas')),
    ]


def account_of(service: Service) -> str:
    return SYSTEM if service.account == SYSTEM else f'NT SERVICE\\{service.name}'


def xml(service: Service, *, python: Path, root: Path, logs: Path, valheim: Path) -> str:
    arguments = ['-X', 'utf8', str(root / 'deploy' / 'windows' / 'run.py')]
    for part in service.command:
        arguments.append(str(root / part) if part.endswith('.py') else part)
    quoted = subprocess.list2cmdline(arguments)
    lines = ['<service>',
             f'  <id>{escape(service.name)}</id>',
             f'  <name>{escape(service.title)}</name>',
             f'  <description>{escape(service.description)}</description>',
             f'  <executable>{escape(str(python))}</executable>',
             f'  <arguments>{escape(quoted)}</arguments>',
             f'  <workingdirectory>{escape(str(root / service.working_directory))}</workingdirectory>',
             f'  <startmode>{service.start}</startmode>',
             f'  <stoptimeout>{service.stop_seconds} sec</stoptimeout>',
             '  <stopparentprocessfirst>true</stopparentprocessfirst>',
             f'  <logpath>{escape(str(logs / service.name))}</logpath>']
    if service.own_log:
        lines.append('  <log mode="none"/>')
    else:
        lines += ['  <log mode="roll-by-size">', '    <sizeThreshold>10240</sizeThreshold>',
                  '    <keepFiles>4</keepFiles>', '  </log>']
    for depend in service.depends:
        lines.append(f'  <depend>{escape(depend)}</depend>')
    if service.restart_on_failure:
        lines += ['  <onfailure action="restart" delay="10 sec"/>', '  <resetfailure>1 hour</resetfailure>']
    for key, value in service.env.items():
        lines.append(f'  <env name={quoteattr(key)} value={quoteattr(value.replace("{VALHEIM}", str(valheim)))}/>')
    lines.append('</service>')
    return '\n'.join(lines) + '\n'


def fetch_winsw(cache: Path) -> Path:
    """WinSW, downloaded once and checked against the pinned hash."""
    target = cache / 'WinSW.NET4.exe'
    if target.is_file() and hashlib.sha256(target.read_bytes()).hexdigest() == WINSW_SHA256:
        return target
    cache.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(WINSW_URL, timeout=60) as response:
        data = response.read(5_000_000)
    if hashlib.sha256(data).hexdigest() != WINSW_SHA256:
        raise RuntimeError('WinSW download does not match its pinned hash')
    target.write_bytes(data)
    return target


def _run(argv: list[str], timeout: int = 120) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout, errors='replace')


def install(service: Service, *, winsw: Path, folder: Path, python: Path, root: Path,
            logs: Path, valheim: Path) -> None:
    """Register (or re-register) one service and set its account."""
    folder.mkdir(parents=True, exist_ok=True)
    wrapper = folder / f'{service.name}.exe'
    definition = folder / f'{service.name}.xml'
    remove(service.name, wrapper, service.stop_seconds)
    shutil.copyfile(winsw, wrapper)
    definition.write_text(xml(service, python=python, root=root, logs=logs, valheim=valheim),
                          encoding='utf-8')
    done = _run([str(wrapper), 'install'])
    if done.returncode:
        raise RuntimeError(f'could not register {service.name}: {(done.stderr or done.stdout).strip()[-300:]}')
    if service.account != SYSTEM:
        done = _run(['sc.exe', 'config', service.name, 'obj=', account_of(service)])
        if done.returncode:
            raise RuntimeError(f'could not set the account of {service.name}: {done.stdout.strip()[-300:]}')


def remove(name: str, wrapper: Path, stop_seconds: int = 150) -> None:
    """Stop and unregister a service, even if its wrapper moved or is gone."""
    if _run(['sc.exe', 'query', name]).returncode != 0:
        return
    if wrapper.is_file():
        _run([str(wrapper), 'stop'], timeout=stop_seconds + 30)
        _run([str(wrapper), 'uninstall'])
    else:
        _run(['sc.exe', 'stop', name])
        deadline = time.monotonic() + stop_seconds
        while time.monotonic() < deadline and 'STOPPED' not in _run(['sc.exe', 'query', name]).stdout:
            time.sleep(1)
        _run(['sc.exe', 'delete', name])
    deadline = time.monotonic() + 30  # deletion completes once handles close
    while time.monotonic() < deadline and _run(['sc.exe', 'query', name]).returncode == 0:
        time.sleep(1)


def uninstall(name: str, folder: Path) -> None:
    remove(name, folder / f'{name}.exe')
