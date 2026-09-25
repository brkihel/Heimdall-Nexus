"""Valheim settings, schedules and backups used by the privileged executor.

Only fixed operations are accepted here. No user supplied shell command runs.
"""
from __future__ import annotations

import datetime as dt
from contextlib import contextmanager
import fcntl
import json
import os
import pwd
import re
import shutil
import subprocess
import tarfile
import tempfile
import uuid

import codigos
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
# World modifiers offered by Valheim's own "host a server" screen. Values match
# the -modifier options; 'default' means the slider's middle (not passed).
MODIFIERS = {
    'combat': ('veryeasy', 'easy', 'default', 'hard', 'veryhard'),
    'deathpenalty': ('casual', 'veryeasy', 'easy', 'default', 'hard', 'hardcore'),
    'resources': ('muchless', 'less', 'default', 'more', 'muchmore', 'most'),
    'raids': ('none', 'muchless', 'less', 'default', 'more', 'muchmore'),
    'portals': ('casual', 'default', 'hard', 'veryhard'),
}
WORLD_KEYS = ('playerevents', 'fire', 'nomap', 'passivemobs', 'nobuildcost')
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
    modifiers = _modifiers(env)
    supports_modifiers = 'VH_MODIFIERS_MANAGED' in script
    if supports_modifiers and modifiers['gerenciar']:
        args.append('-resetmodifiers')
        for name, value in modifiers['valores'].items():
            if value != 'default':
                args += ['-modifier', name, value]
        for key in modifiers['chaves']:
            args += ['-setkey', key]
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
            'modificadores': modifiers, 'modificadores_suportados': supports_modifiers,
            'comando': [str(launcher or 'valheim-launch.sh'), '→', *args],
            'ativo': online()}


def _modifiers(env: dict) -> dict:
    values = {name: 'default' for name in MODIFIERS}
    for pair in env.get('VH_MODIFIERS', '').split(','):
        name, _, value = pair.partition('=')
        if name in MODIFIERS and value in MODIFIERS[name]:
            values[name] = value
    keys = [key for key in env.get('VH_SETKEYS', '').split(',') if key in WORLD_KEYS]
    return {'gerenciar': env.get('VH_MODIFIERS_MANAGED') == '1', 'valores': values, 'chaves': keys}


def _modifier_changes(data) -> dict:
    if not isinstance(data, dict) or set(data) != {'gerenciar', 'valores', 'chaves'} or \
            not isinstance(data['gerenciar'], bool) or not isinstance(data['valores'], dict) or \
            not isinstance(data['chaves'], list):
        raise Problem(codigos.com_codigo('HN-CFG-007', 'modificadores de mundo inválidos'))
    if set(data['valores']) != set(MODIFIERS) or any(
            data['valores'][name] not in options for name, options in MODIFIERS.items()):
        raise Problem(codigos.com_codigo('HN-CFG-007', 'valor de modificador inválido'))
    if any(key not in WORLD_KEYS for key in data['chaves']) or \
            len(set(data['chaves'])) != len(data['chaves']):
        raise Problem(codigos.com_codigo('HN-CFG-007', 'opção de mundo inválida'))
    return {'VH_MODIFIERS_MANAGED': '1' if data['gerenciar'] else '0',
            'VH_MODIFIERS': ','.join(f'{name}={value}' for name, value in data['valores'].items()
                                     if value != 'default'),
            'VH_SETKEYS': ','.join(key for key in WORLD_KEYS if key in data['chaves'])}


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
    if 'modificadores' in data:
        if not current['modificadores_suportados']:
            raise Problem(codigos.com_codigo('HN-CFG-008', 'o lançador atual não aceita modificadores'))
        changes.update(_modifier_changes(data['modificadores']))
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


def backup_create():
    with _maintenance():
        return _backup_create()


def _backup_create():
    BACKUPS.mkdir(parents=True, exist_ok=True)
    was_online = online()
    if was_online:
        _system('stop')
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
    safety = _backup_create()
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


# ---- Admins, whitelist and bans (Valheim's adminlist/permittedlist/bannedlist) ----
# Valheim reads one ID per line, skips lines starting with "//" and reloads
# the files about every 10 seconds, so no restart is needed. Names live in
# "// heimdall: ID Name" comment lines, which Valheim keeps when it rewrites a
# list itself (for example after an in-game ban). A disabled whitelist keeps
# its players as "// heimdall-off: ID Name" lines: Valheim ignores comments,
# so an empty list means everyone may join.
PLAYER_ID = re.compile(r'^(7656119\d{10}|[A-Za-z]{2,16}_[A-Za-z0-9-]{3,64})$')
PLAYER_NAME = re.compile(r'^[^\x00-\x1f/]{0,40}$')
LISTS = {'admins': ('adminlist.txt', 'List admin players ID  ONE per line'),
         'whitelist': ('permittedlist.txt', 'List permitted players ID ONE per line'),
         'banidos': ('bannedlist.txt', 'List banned players ID  ONE per line')}
MAX_LIST = 500


def _save_dir() -> Path:
    path = Path(_env().get('VH_SAVEDIR') or GAME / 'saves')
    if path.is_symlink() or not path.is_dir():
        raise Problem(codigos.com_codigo('HN-CFG-005', f'pasta de saves não encontrada: {path}'))
    return path


def _read_list(path: Path) -> dict:
    active, off, names, other = [], [], {}, []
    try:
        lines = path.read_text(encoding='utf-8', errors='replace').splitlines()
    except FileNotFoundError:
        lines = []
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        for prefix, target in (('// heimdall-off:', off), ('// heimdall:', None)):
            if line.startswith(prefix):
                player, _, name = line[len(prefix):].strip().partition(' ')
                if PLAYER_ID.fullmatch(player):
                    names[player] = name.strip()[:40]
                    if target is not None and player not in target:
                        target.append(player)
                break
        else:
            if line.startswith('//'):
                other.append(line)
            elif line not in active:
                active.append(line)
    return {'active': active, 'off': off, 'names': names, 'comments': other}


def access_read() -> dict:
    folder = _save_dir()
    lists = {key: _read_list(folder / name) for key, (name, _) in LISTS.items()}
    entry = lambda data, player: {'id': player, 'nome': data['names'].get(player, ''),
                                  'valida': bool(PLAYER_ID.fullmatch(player))}
    admins = [entry(lists['admins'], p) for p in lists['admins']['active']]
    admin_ids = {a['id'] for a in admins}
    white = lists['whitelist']
    enabled = bool(white['active'])
    players = [entry(white, p) for p in (white['active'] if enabled else white['off'])
               if p not in admin_ids]
    return {'pasta': str(folder), 'admins': admins,
            'whitelist': {'ativa': enabled, 'jogadores': players},
            'banidos': [entry(lists['banidos'], p) for p in lists['banidos']['active']]}


def _entries(value, label: str) -> list[tuple[str, str]]:
    if not isinstance(value, list) or len(value) > MAX_LIST:
        raise Problem(codigos.com_codigo('HN-CFG-009', f'lista de {label} inválida'))
    result, seen = [], set()
    for item in value:
        if not isinstance(item, dict) or set(item) - {'id', 'nome'}:
            raise Problem(codigos.com_codigo('HN-CFG-009', f'item inválido em {label}'))
        player = str(item.get('id', '')).strip()
        name = ' '.join(str(item.get('nome', '')).split())
        if not PLAYER_ID.fullmatch(player):
            raise Problem(codigos.com_codigo('HN-CFG-001', f'ID inválida em {label}: {player[:40] or "(vazia)"}'))
        if not PLAYER_NAME.fullmatch(name):
            raise Problem(codigos.com_codigo('HN-CFG-002', f'nome inválido em {label}'))
        if player not in seen:
            seen.add(player)
            result.append((player, name))
    return result


def _write_list(path: Path, header: str, comments: list[str], active, off=()) -> None:
    lines = [f'// {header}', '// Managed by Heimdall Nexus (Jarl > Server Config).']
    lines += [c for c in comments if c not in lines]
    for player, name in active:
        lines.append(f'// heimdall: {player} {name}'.rstrip())
    for player, name in off:
        lines.append(f'// heimdall-off: {player} {name}'.rstrip())
    lines += [player for player, _ in active]
    content = '\n'.join(lines) + '\n'
    game = pwd.getpwnam('valheim') if _user_exists('valheim') else None
    with tempfile.NamedTemporaryFile('w', encoding='utf-8', dir=path.parent,
                                     prefix='.heimdall-', delete=False) as stream:
        temp = Path(stream.name)
        stream.write(content)
    try:
        # The game must own its lists: in-game ban/permit commands rewrite them.
        if game:
            os.chown(temp, game.pw_uid, game.pw_gid)
        os.chmod(temp, 0o644)
        if path.is_symlink():
            raise Problem(codigos.com_codigo('HN-CFG-006', f'{path.name} é um link simbólico'))
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _user_exists(name: str) -> bool:
    try:
        pwd.getpwnam(name)
        return True
    except KeyError:
        return False


def access_save(data: dict) -> dict:
    if not isinstance(data, dict) or set(data) != {'admins', 'whitelist_ativa', 'whitelist', 'banidos'} \
            or not isinstance(data['whitelist_ativa'], bool):
        raise Problem(codigos.com_codigo('HN-CFG-009', 'dados de acesso inválidos'))
    admins = _entries(data['admins'], 'admins')
    players = _entries(data['whitelist'], 'whitelist')
    banned = _entries(data['banidos'], 'banidos')
    admin_ids = {player for player, _ in admins}
    clash = admin_ids & {player for player, _ in banned}
    if clash:
        raise Problem(codigos.com_codigo('HN-CFG-003', 'admin e banido ao mesmo tempo: ' + ', '.join(sorted(clash))))
    if data['whitelist_ativa'] and not admins and not players:
        raise Problem(codigos.com_codigo('HN-CFG-004', 'adicione pelo menos um jogador antes de ativar a whitelist'))
    folder = _save_dir()
    current = {key: _read_list(folder / name) for key, (name, _) in LISTS.items()}
    _write_list(folder / LISTS['admins'][0], LISTS['admins'][1], current['admins']['comments'], admins)
    # Admins are always allowed in: the whitelist includes them automatically.
    permitted = admins + [p for p in players if p[0] not in admin_ids]
    if data['whitelist_ativa']:
        _write_list(folder / LISTS['whitelist'][0], LISTS['whitelist'][1],
                    current['whitelist']['comments'], permitted)
    else:
        _write_list(folder / LISTS['whitelist'][0], LISTS['whitelist'][1],
                    current['whitelist']['comments'], [], players)
    _write_list(folder / LISTS['banidos'][0], LISTS['banidos'][1], current['banidos']['comments'], banned)
    return access_read()
