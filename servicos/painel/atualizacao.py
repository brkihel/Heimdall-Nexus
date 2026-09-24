"""Self-update from the official repository, driven by the privileged executor.

Security model:
- The executor keeps its own root-owned clone; the panel user cannot write it.
- Only the configured HTTPS repository is fetched; other Git transports are
  refused, and credentials are never prompted for.
- The admin approves an exact commit. The update runs that commit, not
  whatever the branch points to a moment later.
- update.sh restarts the executor and the panel, so it runs in a separate
  transient systemd unit and writes its progress to a log file.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from pathlib import Path

import codigos

STATE = Path(os.environ.get('HEIMDALL_STATE_DIR', '/var/lib/heimdall-nexus'))
RUNTIME = Path(os.environ.get('HEIMDALL_ROOT', '/opt/heimdall-nexus'))
REPOSITORY = os.environ.get('HEIMDALL_UPDATE_REPO', 'https://github.com/brkihel/Heimdall-Nexus.git')
UNIT = 'heimdall-self-update'
CHANNEL = re.compile(r'^(main|dev/[a-z0-9._-]{1,40})$')
COMMIT = re.compile(r'^[0-9a-f]{40}$')
REPO_URL = re.compile(r'^https://[A-Za-z0-9.-]+/[A-Za-z0-9._/-]+\.git$')
MAX_COMMITS = 50


class UpdateError(ValueError):
    """Carries a catalog code (codigos.py); str() is 'HN-UPD-NNN: message'."""

    def __init__(self, code: str, message: str):
        self.code = code
        super().__init__(codigos.com_codigo(code, message))


def _paths(state: Path) -> dict:
    return {'source': state / 'source', 'channel': state / 'update-channel',
            'check': state / 'update-check.json', 'log': state / 'update.log'}


def _git(source: Path, *args: str, timeout: int = 30, allow_file: bool = False) -> str:
    protocols = ['-c', 'protocol.allow=never', '-c', 'protocol.https.allow=always']
    if allow_file:  # tests only
        protocols += ['-c', 'protocol.file.allow=always']
    env = {'PATH': '/usr/bin:/bin', 'GIT_TERMINAL_PROMPT': '0', 'HOME': str(source.parent),
           'GIT_CONFIG_NOSYSTEM': '1', 'LC_ALL': 'C'}
    try:
        done = subprocess.run(['git', *protocols, '-c', f'safe.directory={source}', *args],
                              cwd=source if source.is_dir() else source.parent,
                              env=env, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as error:
        raise UpdateError('HN-UPD-001', 'o Git não está instalado; rode: sudo apt install git') from error
    except subprocess.TimeoutExpired as error:
        raise UpdateError('HN-UPD-002', 'o repositório demorou demais para responder') from error
    if done.returncode != 0:
        detail = (done.stderr or done.stdout).strip().splitlines()[-1:] or ['']
        raise UpdateError('HN-UPD-003', 'falha no Git: ' + detail[0][:200])
    return done.stdout


def installed(runtime: Path = RUNTIME) -> dict:
    try:
        data = json.loads((runtime / '.heimdall-version.json').read_text(encoding='utf-8'))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def channel(state: Path = STATE, runtime: Path = RUNTIME) -> str:
    """The saved channel; before any choice, the branch the install came from."""
    try:
        value = _paths(state)['channel'].read_text(encoding='ascii').strip()
    except (OSError, UnicodeError):
        value = str(installed(runtime).get('branch') or '')
    return value if CHANNEL.fullmatch(value) else 'main'


def set_channel(value: object, state: Path = STATE) -> str:
    if not isinstance(value, str) or not CHANNEL.fullmatch(value):
        raise UpdateError('HN-UPD-007', 'canal inválido')
    path = _paths(state)['channel']
    temporary = path.with_suffix('.tmp')
    temporary.write_text(value + '\n', encoding='ascii')
    os.replace(temporary, path)
    _paths(state)['check'].unlink(missing_ok=True)
    return value


def running() -> bool:
    try:
        state = subprocess.run(['systemctl', 'is-active', UNIT + '.service'],
                               capture_output=True, text=True, timeout=5).stdout.strip()
        return state in ('active', 'activating', 'reloading')
    except (OSError, subprocess.TimeoutExpired):
        return False


def _log_tail(path: Path, lines: int = 80) -> list[str]:
    try:
        text = path.read_bytes()[-24000:].decode('utf-8', 'replace')
    except OSError:
        return []
    clean = ''.join(c for c in text if c in '\n\t' or ord(c) >= 32)
    return clean.splitlines()[-lines:]


# deploy/update.sh prints '::heimdall step N/T CODE' before each step,
# '::heimdall fail CODE' on error and '::heimdall done' at the end.
STEPS = {
    'HN-UPD-100': 'Conferindo a instalação',
    'HN-UPD-101': 'Copiando o código novo',
    'HN-UPD-102': 'Atualizando as bibliotecas do painel',
    'HN-UPD-103': 'Atualizando os serviços das Sagas',
    'HN-UPD-104': 'Atualizando os ajudantes do site',
    'HN-UPD-105': 'Publicando o site',
    'HN-UPD-106': 'Conferindo a ponte Sagas e registrando a versão',
    'HN-UPD-108': 'Reiniciando o painel',
}
MARKER = re.compile(r'^::heimdall (step (\d+)/(\d+) (HN-UPD-\d{3})|fail (HN-UPD-\d{3})|done)\b')


def progress(lines: list[str], active: bool) -> dict:
    """Summarize the update log for the progress bar."""
    result = {'state': 'idle', 'step': 0, 'total': 0, 'code': '', 'label': ''}
    started, started_at, markers = False, 0.0, False
    for line in lines:
        match = MARKER.match(line)
        if not match:
            if ' Updating to ' in line:
                started = True
                try:
                    started_at = time.mktime(time.strptime(line[:19], '%Y-%m-%d %H:%M:%S'))
                except ValueError:
                    started_at = 0.0
            continue
        started = markers = True
        if match.group(2):
            code = match.group(4)
            result.update(state='running', step=int(match.group(2)), total=int(match.group(3)),
                          code=code, label=STEPS.get(code, ''))
        elif match.group(5):
            code = match.group(5)
            result.update(state='failed', code=code, label=codigos.CATALOGO[code]['titulo'])
        else:
            result.update(state='done', step=result['total'] or result['step'], code='',
                          label='Atualização concluída')
    if not started:
        return result
    # systemd may not report the unit as active in the first instant.
    if not markers and not active and time.time() - started_at < 20:
        active = True
    if result['state'] in ('idle', 'running') and not active:
        # The unit ended without printing done or fail: interrupted.
        result.update(state='failed', code='HN-UPD-121',
                      label=codigos.CATALOGO['HN-UPD-121']['titulo'])
    elif result['state'] == 'idle':
        result.update(state='running', label='Preparando')
    return result


def status(state: Path = STATE, runtime: Path = RUNTIME) -> dict:
    paths = _paths(state)
    try:
        check = json.loads(paths['check'].read_text(encoding='utf-8'))
    except (OSError, ValueError):
        check = None
    active = running()
    log = _log_tail(paths['log'], 400)
    return {'installed': installed(runtime), 'channel': channel(state, runtime),
            'repository': REPOSITORY, 'running': active, 'check': check,
            'log': log[-80:], 'progress': progress(log, active), 'git': _has_git()}


def _has_git() -> bool:
    return any(Path(folder, 'git').is_file() for folder in ('/usr/bin', '/bin'))


def _ensure_clone(state: Path, repository: str, allow_file: bool) -> Path:
    if not allow_file and not REPO_URL.fullmatch(repository):
        raise UpdateError('HN-UPD-004', 'endereço do repositório de atualização inválido')
    source = _paths(state)['source']
    if not (source / '.git').is_dir():
        if source.exists():
            raise UpdateError('HN-UPD-005', f'{source} existe mas não é um repositório Git')
        state.mkdir(parents=True, exist_ok=True)
        _git(state, 'clone', '--quiet', '--no-checkout', repository, str(source),
             timeout=180, allow_file=allow_file)
        os.chmod(source, 0o750)
    # Re-pin the origin every time, in case the clone was tampered with.
    _git(source, 'remote', 'set-url', 'origin', repository, allow_file=allow_file)
    return source


def check(state: Path = STATE, runtime: Path = RUNTIME, repository: str = REPOSITORY,
          allow_file: bool = False) -> dict:
    try:
        return _check(state, runtime, repository, allow_file)
    except UpdateError as error:
        _save_check(state, {'checked_at': int(time.time()), 'channel': channel(state, runtime),
                            'error': str(error), 'code': error.code})
        raise


def _save_check(state: Path, result: dict) -> None:
    temporary = _paths(state)['check'].with_suffix('.tmp')
    temporary.write_text(json.dumps(result, ensure_ascii=False), encoding='utf-8')
    os.replace(temporary, _paths(state)['check'])


def _check(state: Path, runtime: Path, repository: str, allow_file: bool) -> dict:
    source = _ensure_clone(state, repository, allow_file)
    _git(source, 'fetch', '--quiet', '--prune', 'origin',
         '+refs/heads/*:refs/remotes/origin/*', timeout=120, allow_file=allow_file)
    branches = sorted(name.removeprefix('origin/') for name in
                      _git(source, 'for-each-ref', '--format=%(refname:short)',
                           'refs/remotes/origin').split()
                      if CHANNEL.fullmatch(name.removeprefix('origin/')))
    wanted = channel(state, runtime)
    if wanted not in branches:
        raise UpdateError('HN-UPD-006', f'o canal {wanted} não existe no repositório')
    target = _git(source, 'rev-parse', f'origin/{wanted}^{{commit}}').strip()
    current = installed(runtime).get('commit', '')
    linear = False
    if COMMIT.fullmatch(current):
        try:
            _git(source, 'merge-base', '--is-ancestor', current, target)
            linear = True
        except UpdateError:
            linear = False
    span = f'{current}..{target}' if linear else target
    commits = []
    for line in _git(source, 'log', f'--max-count={MAX_COMMITS}',
                     '--format=%H%x09%ct%x09%s', span).splitlines():
        sha, when, subject = (line.split('\t', 2) + ['', ''])[:3]
        commits.append({'commit': sha, 'short': sha[:7], 'date': int(when or 0),
                        'subject': subject[:200]})
    result = {'checked_at': int(time.time()), 'channel': wanted, 'branches': branches,
              'target': target, 'target_short': target[:7],
              'up_to_date': current == target, 'linear': linear, 'commits': commits}
    _save_check(state, result)
    return result


def start(commit: object, state: Path = STATE, runner=subprocess.run,
          runtime: Path = RUNTIME) -> dict:
    paths = _paths(state)
    if not isinstance(commit, str) or not COMMIT.fullmatch(commit):
        raise UpdateError('HN-UPD-008', 'versão inválida')
    if running():
        raise UpdateError('HN-UPD-009', 'uma atualização já está em andamento')
    try:
        last = json.loads(paths['check'].read_text(encoding='utf-8'))
    except (OSError, ValueError) as error:
        raise UpdateError('HN-UPD-012', 'procure atualizações antes de atualizar') from error
    source = paths['source']
    remote = _git(source, 'rev-parse', f'origin/{last["channel"]}^{{commit}}').strip()
    if last.get('error') or last.get('target') != commit or remote != commit or last['channel'] != channel(state, runtime):
        raise UpdateError('HN-UPD-010', 'a lista de mudanças ficou desatualizada; procure de novo')
    _git(source, 'checkout', '--quiet', '--force', '--detach', commit)
    _git(source, 'clean', '--quiet', '-fdx')
    paths['log'].write_text(time.strftime('%Y-%m-%d %H:%M:%S') +
                            f' Updating to {commit[:7]} ({last["channel"]})\n', encoding='utf-8')
    # --no-block: update.sh restarts this executor; do not wait inside it.
    command = ['systemd-run', f'--unit={UNIT}', '--collect', '--quiet', '--no-block',
               f'--property=StandardOutput=append:{paths["log"]}',
               f'--property=StandardError=append:{paths["log"]}',
               f'--setenv=HEIMDALL_UPDATE_BRANCH={last["channel"]}',
               '/bin/bash', str(source / 'deploy/update.sh')]
    done = runner(command, capture_output=True, text=True, timeout=30)
    if done.returncode != 0:
        raise UpdateError('HN-UPD-011', 'não foi possível iniciar a atualização: ' +
                          (done.stderr or '').strip()[:200])
    return {'started': True, 'commit': commit}
