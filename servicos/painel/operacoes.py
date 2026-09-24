"""Valheim settings, schedules and backups used by the privileged executor.

Only fixed operations are accepted here. No user supplied shell command runs.
"""
from __future__ import annotations

import datetime as dt
from contextlib import contextmanager
import fcntl
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import uuid
from pathlib import Path


GAME = Path(os.environ.get('HEIMDALL_VALHEIM_DIR', '/srv/valheim'))
STATE = Path(os.environ.get('HEIMDALL_PANEL_STATE_DIR', '/var/lib/heimdall-panel'))
SERVICE = os.environ.get('HEIMDALL_GAME_SERVICE') or 'heimdall-valheim'
ENV = GAME / 'server.env'
PROFILE = GAME / 'server-profile.json'
SCHEDULES = STATE / 'schedules.json'
BACKUPS = GAME / 'backups'
MAINTENANCE_LOCK = Path(os.environ.get('HEIMDALL_MAINTENANCE_LOCK', '/run/lock/heimdall-maintenance.lock'))
NAME = re.compile(r'^[^\x00-\x1f]{1,80}$')
WORLD = re.compile(r'^[A-Za-z0-9_ -]{1,40}$')
ID = re.compile(r'^[0-9a-f]{32}$')
ARCHIVE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9_.-]{0,100}\.tar\.gz$')
WORLD_ARCHIVE = re.compile(r'^\d{8}T\d{6}(?:\d{6})?Z\.tar\.gz$')


class Problem(Exception):
    pass


def _json(path: Path, fallback):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return fallback


def _write(path: Path, content: str, mode=0o600):
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent,
                                     prefix='.heimdall-', delete=False) as stream:
        temp = Path(stream.name)
        stream.write(content)
    try:
        if path.exists():
            st = path.stat()
            os.chown(temp, st.st_uid, st.st_gid)
            mode = st.st_mode & 0o777
        os.chmod(temp, mode)
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _system(action: str):
    if action not in {'start', 'stop', 'restart'}:
        raise Problem('ação de serviço inválida')
    result = subprocess.run(['systemctl', action, SERVICE], capture_output=True,
                            text=True, timeout=300)
    if result.returncode:
        raise Problem(result.stderr.strip()[-300:] or 'systemd recusou a operação')


def online():
    return subprocess.run(['systemctl', 'is-active', '--quiet', SERVICE]).returncode == 0


def _env():
    values = {}
    try:
        for line in ENV.read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.lstrip().startswith('#'):
                key, value = line.split('=', 1)
                if re.fullmatch(r'[A-Z_]+', key.strip()):
                    values[key.strip()] = value.strip().strip('"').strip("'")
    except OSError:
        pass
    return values


def _launcher():
    result = subprocess.run(['systemctl', 'show', SERVICE, '-p', 'ExecStart', '--value'],
                            capture_output=True, text=True, timeout=15)
    match = re.search(r'path=([^ ;}]+)', result.stdout)
    return Path(match.group(1)) if match else None


# Mods that let players join a server with no password. Vanilla Valheim does
# not; without one of these, the panel never lets the password be removed.
BLANK_PASSWORD_MODS = {'serverblankpassword.dll': 'serverblankpassword'}


def blank_password_mod() -> str | None:
    plugins = GAME / 'current/BepInEx/plugins'
    try:
        if _env().get('VH_BEPINEX') == '0' or not plugins.is_dir():
            return None
    except OSError:
        return None
    try:
        for dll in plugins.rglob('*.dll'):
            name = BLANK_PASSWORD_MODS.get(dll.name.lower())
            if name:
                return name
    except OSError:
        pass
    return None


def server_read():
    env = _env()
    launcher = _launcher()
    script = launcher.read_text(encoding='utf-8', errors='replace') if launcher and launcher.is_file() else ''
    supports_password = 'VH_PASSWORD' in script
    args = ['valheim_server.x86_64', '-nographics', '-batchmode',
            '-name', env.get('VH_NAME', ''), '-world', env.get('VH_WORLD', ''),
            '-port', env.get('VH_PORT', '2456'), '-public', env.get('VH_PUBLIC', '0'),
            '-savedir', env.get('VH_SAVEDIR', str(GAME / 'saves'))]
    if env.get('VH_RESOURCES') and '-modifier resources' in script:
        args += ['-modifier', 'resources', env['VH_RESOURCES']]
    if env.get('VH_LOG') and '-logFile' in script:
        args += ['-logFile', env['VH_LOG']]
    if supports_password and env.get('VH_PASSWORD'):
        args += ['-password', '••••••']
    if env.get('VH_CROSSPLAY') == '1':
        args.append('-crossplay')
    return {'nome': env.get('VH_NAME', ''), 'mundo': env.get('VH_WORLD', ''),
            'porta': env.get('VH_PORT', '2456'), 'publico': env.get('VH_PUBLIC') == '1',
            'crossplay': env.get('VH_CROSSPLAY') == '1',
            'senha_definida': bool(env.get('VH_PASSWORD')),
            'senha_suportada': supports_password,
            'mod_sem_senha': blank_password_mod(),
            'descricao': _json(PROFILE, {}).get('description', ''),
            'comando': [str(launcher or 'valheim-launch.sh'), '→', *args],
            'ativo': online()}


def server_save(data: dict):
    current = server_read()
    changes = {}
    for key, env_key, valid in (
        ('nome', 'VH_NAME', lambda v: NAME.fullmatch(v)),
        ('mundo', 'VH_WORLD', lambda v: WORLD.fullmatch(v)),
        ('porta', 'VH_PORT', lambda v: v.isdigit() and 1024 <= int(v) <= 65534),
    ):
        if key in data:
            value = str(data[key]).strip()
            if not valid(value):
                raise Problem(f'{key} inválido')
            changes[env_key] = value
    for key, env_key in (('publico', 'VH_PUBLIC'), ('crossplay', 'VH_CROSSPLAY')):
        if key in data:
            if not isinstance(data[key], bool):
                raise Problem(f'{key} inválido')
            changes[env_key] = '1' if data[key] else '0'
    if data.get('remover_senha') is True:
        if not blank_password_mod():
            raise Problem('a senha só pode ser removida com um mod de servidor sem senha instalado, '
                          'como o serverblankpassword')
        if data.get('senha'):
            raise Problem('escolha entre trocar ou remover a senha')
        changes['VH_PASSWORD'] = ''
    if data.get('senha'):
        value = str(data['senha'])
        if not current['senha_suportada']:
            raise Problem('o lançador atual não aceita senha por VH_PASSWORD')
        if len(value) < 5 or len(value) > 100 or '\n' in value or '\r' in value:
            raise Problem('a senha do jogo precisa de 5 a 100 caracteres')
        changes['VH_PASSWORD'] = value
    env = _env()
    final_name = changes.get('VH_NAME', env.get('VH_NAME', ''))
    final_password = changes.get('VH_PASSWORD', env.get('VH_PASSWORD', ''))
    if final_password and final_password.casefold() in final_name.casefold():
        raise Problem('o Valheim não aceita a senha dentro do nome do servidor; mude um dos dois')
    description = str(data.get('descricao', current['descricao'])).strip()
    if len(description) > 500 or any(ord(c) < 32 and c not in '\n\t' for c in description):
        raise Problem('descrição inválida')
    old = ENV.read_text(encoding='utf-8')
    lines = old.splitlines(keepends=True)
    if lines and not lines[-1].endswith('\n'):
        lines[-1] += '\n'
    for key, value in changes.items():
        encoded = json.dumps(value, ensure_ascii=False)
        pattern = re.compile(r'^' + re.escape(key) + r'=')
        found = False
        for i, line in enumerate(lines):
            if pattern.match(line):
                lines[i] = f'{key}={encoded}\n'
                found = True
                break
        if not found:
            lines.append(f'{key}={encoded}\n')
    modified = ''.join(lines) != old
    if modified:
        _write(ENV, ''.join(lines), 0o640)
    if description != current['descricao']:
        _write(PROFILE, json.dumps({'description': description}, ensure_ascii=False) + '\n')
    return {'reinicio_necessario': modified and current['ativo'], 'configuracao': server_read()}


def _cron_part(expr: str, minimum: int, maximum: int):
    values = set()
    for part in expr.split(','):
        if '/' in part:
            base, step = part.split('/', 1)
            if not step.isdigit() or int(step) < 1:
                raise Problem('passo cron inválido')
            step = int(step)
        else:
            base, step = part, 1
        if base == '*':
            lo, hi = minimum, maximum
        elif '-' in base:
            a, b = base.split('-', 1)
            if not a.isdigit() or not b.isdigit():
                raise Problem('intervalo cron inválido')
            lo, hi = int(a), int(b)
        elif base.isdigit():
            lo = int(base)
            hi = maximum if '/' in part else lo
        else:
            raise Problem('campo cron inválido')
        if not minimum <= lo <= hi <= maximum:
            raise Problem('campo cron fora do intervalo')
        values.update(range(lo, hi + 1, step))
    return values


def cron_match(expression: str, moment: dt.datetime):
    parts = expression.split()
    if len(parts) != 5:
        raise Problem('use cinco campos cron: minuto hora dia mês semana')
    minute, hour, day, month, weekday = [
        _cron_part(part, lo, hi) for part, lo, hi in zip(
            parts, (0, 0, 1, 1, 0), (59, 23, 31, 12, 7))]
    week = (moment.weekday() + 1) % 7
    day_ok, week_ok = moment.day in day, week in weekday or week == 0 and 7 in weekday
    day_rule = day_ok and week_ok if parts[2] == '*' or parts[4] == '*' else day_ok or week_ok
    return moment.minute in minute and moment.hour in hour and moment.month in month and day_rule


def schedules_list():
    value = _json(SCHEDULES, [])
    return value if isinstance(value, list) else []


def schedules_save(data: dict):
    entries = schedules_list()
    item_id = str(data.get('id') or uuid.uuid4().hex)
    if not ID.fullmatch(item_id):
        raise Problem('rotina inválida')
    title = str(data.get('nome', '')).strip()
    expression = str(data.get('cron', '')).strip()
    if not NAME.fullmatch(title):
        raise Problem('nome da rotina inválido')
    cron_match(expression, dt.datetime.now())
    tasks = data.get('tarefas', [])
    if not isinstance(tasks, list) or not 1 <= len(tasks) <= 10:
        raise Problem('adicione de uma a dez tarefas')
    cleaned = []
    for task in tasks:
        if not isinstance(task, dict) or task.get('acao') not in {'restart', 'start', 'stop', 'backup'}:
            raise Problem('tarefa inválida')
        offset = task.get('atraso', 0)
        if not isinstance(offset, int) or not 0 <= offset <= 3600:
            raise Problem('atraso precisa estar entre 0 e 3600 segundos')
        cleaned.append({'acao': task['acao'], 'atraso': offset})
    item = {'id': item_id, 'nome': title, 'cron': expression,
            'ativo': data.get('ativo') is True,
            'apenas_online': data.get('apenas_online') is True,
            'tarefas': cleaned}
    for idx, old in enumerate(entries):
        if old['id'] == item_id:
            item['ultima_execucao'] = old.get('ultima_execucao')
            entries[idx] = item
            break
    else:
        entries.append(item)
    _write(SCHEDULES, json.dumps(entries, ensure_ascii=False, indent=2) + '\n')
    return item


def schedules_delete(item_id: str):
    if not ID.fullmatch(item_id):
        raise Problem('rotina inválida')
    entries = schedules_list()
    kept = [item for item in entries if item['id'] != item_id]
    if len(kept) == len(entries):
        raise Problem('rotina não encontrada')
    _write(SCHEDULES, json.dumps(kept, ensure_ascii=False, indent=2) + '\n')


def backup_list():
    BACKUPS.mkdir(parents=True, exist_ok=True)
    return [{'nome': p.name, 'tamanho': p.stat().st_size,
             'quando': dt.datetime.fromtimestamp(p.stat().st_mtime, dt.timezone.utc).isoformat(),
             'travado': p.with_name(p.name + '.lock').exists(),
             'restauravel': bool(WORLD_ARCHIVE.fullmatch(p.name))}
            for p in sorted(BACKUPS.glob('*.tar.gz'), reverse=True)
            if ARCHIVE.fullmatch(p.name) and p.is_file() and not p.is_symlink()]


def _archive(name: str):
    if not ARCHIVE.fullmatch(name):
        raise Problem('nome do backup inválido')
    path = BACKUPS / name
    if not path.is_file() or path.is_symlink():
        raise Problem('backup não encontrado')
    return path


def backup_lock(name: str, locked: bool):
    path = _archive(name)
    marker = path.with_name(path.name + '.lock')
    if locked:
        _write(marker, 'locked\n')
    else:
        marker.unlink(missing_ok=True)


def backup_delete(name: str):
    path = _archive(name)
    if path.with_name(path.name + '.lock').exists():
        raise Problem('destrave o backup antes de apagar')
    path.unlink()
    path.with_name(path.name + '.sha256').unlink(missing_ok=True)


@contextmanager
def _maintenance():
    MAINTENANCE_LOCK.parent.mkdir(parents=True, exist_ok=True)
    with MAINTENANCE_LOCK.open('a+') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def backup_create(*, resume=True):
    with _maintenance():
        return _backup_create(resume=resume)


def _backup_create(*, resume=True):
    BACKUPS.mkdir(parents=True, exist_ok=True)
    was_online = online()
    if was_online:
        _system('stop')
    try:
        stamp = dt.datetime.now(dt.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        final = BACKUPS / f'{stamp}.tar.gz'
        temp = BACKUPS / f'.{stamp}.partial'
        try:
            with tarfile.open(temp, 'w:gz', dereference=False) as archive:
                for name in ('saves', 'config', 'server.env', 'server-profile.json'):
                    path = GAME / name
                    if path.exists():
                        archive.add(path, arcname=name, recursive=True)
            os.chmod(temp, 0o600)
            os.replace(temp, final)
        finally:
            temp.unlink(missing_ok=True)
        return final.name
    finally:
        if was_online and resume:
            _system('start')


def backup_restore(name: str):
    with _maintenance():
        return _backup_restore(name)


def _backup_restore(name: str):
    if not WORLD_ARCHIVE.fullmatch(name):
        raise Problem('esse arquivo é um pacote de manutenção; restaure o mundo por um backup de mundo')
    path = _archive(name)
    was_online = online()
    if was_online:
        _system('stop')
    try:
        safety = _backup_create(resume=False)
        with tempfile.TemporaryDirectory(dir=GAME) as folder:
            stage = Path(folder)
            with tarfile.open(path, 'r:gz') as archive:
                members = archive.getmembers()
                if any(m.issym() or m.islnk() or m.isdev() or m.name.startswith('/') or
                       '..' in Path(m.name).parts or
                       m.name.split('/')[0] not in {'saves', 'config', 'server.env', 'server-profile.json',
                                                       'service', 'mods.lock.json', 'appmanifest_896660.acf',
                                                       'backup-metadata.json', 'release',
                                                       'antes-da-instalacao.log'}
                       for m in members):
                    raise Problem('backup contém caminhos inseguros')
                # Avoid extractall: Python 3.10 lacks extraction filters. Only
                # regular files and directories below four fixed roots are used.
                for member in members:
                    if member.name.split('/')[0] not in {'saves', 'config', 'server.env', 'server-profile.json'}:
                        continue
                    if not (member.isfile() or member.isdir()):
                        continue
                    dest = stage / member.name
                    if member.isdir():
                        dest.mkdir(parents=True, exist_ok=True)
                    else:
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        with archive.extractfile(member) as src, dest.open('wb') as out:
                            shutil.copyfileobj(src, out)
                        os.chmod(dest, member.mode & 0o777)
            for name in ('saves', 'config', 'server.env', 'server-profile.json'):
                source = stage / name
                if not source.exists():
                    continue
                target = GAME / name
                previous = GAME / ('.before-restore-' + uuid.uuid4().hex + '-' + name)
                if target.exists():
                    target.rename(previous)
                source.rename(target)
                if name in ('saves', 'config'):
                    import pwd
                    account = pwd.getpwnam('valheim')
                    for item in [target, *target.rglob('*')]:
                        if not item.is_symlink():
                            os.chown(item, account.pw_uid, account.pw_gid)
                elif name == 'server.env':
                    import grp
                    os.chown(target, 0, grp.getgrnam('valheim').gr_gid)
                    os.chmod(target, 0o640)
                if previous.exists():
                    if previous.is_dir():
                        shutil.rmtree(previous)
                    else:
                        previous.unlink()
        return safety
    finally:
        if was_online:
            _system('start')


def schedules_tick():
    """Called by a systemd timer, once per minute. Idempotent per local minute."""
    SCHEDULES.parent.mkdir(parents=True, exist_ok=True)
    with (SCHEDULES.parent / 'schedules.lock').open('a+') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        now = dt.datetime.now().replace(second=0, microsecond=0)
        marker = now.isoformat()
        entries = schedules_list()
        due = []
        for item in entries:
            if item.get('ativo') and item.get('ultima_execucao') != marker and cron_match(item['cron'], now):
                item['ultima_execucao'] = marker
                if not item.get('apenas_online') or online():
                    due.append(item)
        _write(SCHEDULES, json.dumps(entries, ensure_ascii=False, indent=2) + '\n')
    import time
    for item in due:
        for task in item['tarefas']:
            time.sleep(task.get('atraso', 0))
            if task['acao'] == 'backup':
                backup_create()
            else:
                _system(task['acao'])
