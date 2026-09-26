"""Updates an installed Heimdall Nexus on Windows (the counterpart of deploy/update.sh).

From your checkout, in PowerShell as administrator:

    cd C:\\HeimdallNexus-src
    git pull --ff-only
    & "$env:ProgramFiles\\HeimdallNexus\\venv\\Scripts\\python.exe" deploy\\windows\\update.py

Jarl > Sobre e atualizações runs the same file as a one-off SYSTEM task. It
replaces the service code, refreshes the libraries and the site helpers,
republishes the site and restarts the panel. The game, its worlds, mods and
settings, and your site content are not touched. Valheim is not restarted.

Progress lines use the same markers as update.sh ('::heimdall step N/T CODE').
"""
from __future__ import annotations

import ctypes
import filecmp
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TOTAL_STEPS = 7
PYTHON_SERVICES = ('heimdall-panel', 'heimdall-sagas-jobs', 'heimdall-jobs', 'heimdall-executor')
PARTS = ('deploy', 'servicos/painel', 'ferramentas', 'site/web', 'dist')
SKIP = {'.git', '.venv', '__pycache__'}
step_code = 'HN-UPD-100'


def step(number: int, label: str, code: str) -> None:
    global step_code
    step_code = code
    print(f'::heimdall step {number}/{TOTAL_STEPS} {code} {label}', flush=True)


def fail(code: str, reason: str) -> None:
    print(f'::heimdall fail {code} {reason}', file=sys.stderr, flush=True)
    raise SystemExit(1)


def load_env(path: Path) -> dict[str, str]:
    sys.path.insert(0, str(ROOT / 'deploy' / 'windows'))
    import run
    return run.load_env(path)


def run(argv: list[str], timeout: int = 1800, **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(argv, capture_output=True, text=True, errors='replace', timeout=timeout, **kwargs)


def sc(action: str, name: str) -> None:
    run(['sc.exe', action, name], timeout=60)


def wait_state(name: str, wanted: str, seconds: int = 90) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if wanted in run(['sc.exe', 'query', name], timeout=30).stdout:
            return True
        time.sleep(1)
    return False


def mirror(source: Path, target: Path) -> None:
    """Like rsync --delete, without the folders that are never copied."""
    target.mkdir(parents=True, exist_ok=True)
    wanted = set()
    for item in source.iterdir():
        if item.name in SKIP or item.suffix == '.pyc' or '.bak' in item.name:
            continue
        wanted.add(item.name)
        destination = target / item.name
        if item.is_dir():
            mirror(item, destination)
        elif not destination.is_file() or not filecmp.cmp(item, destination, shallow=False):
            shutil.copy2(item, destination)
    for item in target.iterdir():
        if item.name not in wanted and item.name not in SKIP:
            shutil.rmtree(item) if item.is_dir() and not item.is_junction() else item.unlink()


def main() -> None:
    try:
        admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        admin = False
    if not admin:
        print('Run PowerShell as administrator.', file=sys.stderr)
        fail('HN-UPD-100', 'not-admin')
    base = Path(os.environ.get('HEIMDALL_BASE_DIR')
                or Path(os.environ.get('ProgramData', r'C:\ProgramData')) / 'HeimdallNexus')
    env = load_env(base / 'etc' / 'heimdall.env')
    runtime = Path(env.get('HEIMDALL_ROOT') or Path(os.environ['ProgramFiles']) / 'HeimdallNexus' / 'app')
    app_base = runtime.parent
    state = Path(env.get('HEIMDALL_STATE_DIR') or base / 'state')
    if not (state / 'installed.json').is_file() or not (runtime / '.heimdall-nexus-runtime').is_file():
        print('No finished Heimdall Nexus installation here. Use deploy\\windows\\install.ps1 instead.',
              file=sys.stderr)
        fail('HN-UPD-100', 'not-installed')
    if ROOT.resolve() == runtime.resolve():
        print(f'Run this from your Git checkout, not from {runtime}.', file=sys.stderr)
        fail('HN-UPD-100', 'runtime-dir')
    site = Path(env.get('HEIMDALL_SITE_DIR') or state / 'site')
    # The installer's private Git, for the version record below.
    os.environ['PATH'] = str(app_base / 'git' / 'cmd') + os.pathsep + os.environ.get('PATH', '')
    web = Path(env.get('HEIMDALL_WEB_DIR') or base / 'web')
    venv_python = app_base / 'venv' / 'Scripts' / 'python.exe'

    step(1, 'code', 'HN-UPD-101')
    print(f'Updating service code in {runtime}...', flush=True)
    for part in PARTS:
        if (ROOT / part).is_dir():
            mirror(ROOT / part, runtime / part)

    step(2, 'libraries', 'HN-UPD-102')
    print('Updating panel libraries (the Python services pause for it)...', flush=True)
    # Windows cannot replace a library a running service has loaded.
    for name in PYTHON_SERVICES:
        sc('stop', name)
    for name in PYTHON_SERVICES:
        wait_state(name, 'STOPPED')
    done = run([str(venv_python), '-m', 'pip', 'install', '--disable-pip-version-check', '--no-input', '--quiet',
                '-r', str(runtime / 'deploy' / 'requirements-panel.txt'),
                '-r', str(runtime / 'deploy' / 'windows' / 'requirements-windows.txt')])
    if done.returncode:
        print(done.stdout[-1500:], done.stderr[-1500:], sep='\n', file=sys.stderr)
        for name in reversed(PYTHON_SERVICES):
            sc('start', name)
        fail('HN-UPD-102', 'pip')

    step(3, 'sagas-services', 'HN-UPD-103')
    jobs_file = state / 'jobs.json'
    try:
        jobs = json.loads(jobs_file.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        jobs = {}
    if jobs.get('heimdall-sagas-ingest'):
        jobs.update({'heimdall-sagas-story': True, 'heimdall-sagas-atlas': True})
        jobs_file.write_text(json.dumps(jobs, indent=2) + '\n', encoding='utf-8')
    # Service definitions are read at each start: refresh them for the restart below.
    sys.path.insert(0, str(runtime / 'deploy' / 'windows'))
    import services
    folder = app_base / 'services'
    valheim = Path(env.get('HEIMDALL_VALHEIM_DIR') or base / 'valheim')
    for service in services.definitions(game_autostart='Automatic' in (folder / 'heimdall-valheim.xml').read_text(
            encoding='utf-8') if (folder / 'heimdall-valheim.xml').is_file() else False):
        target = folder / f'{service.name}.xml'
        if target.is_file():
            target.write_text(services.xml(service, python=venv_python, root=runtime,
                                           logs=Path(env.get('HEIMDALL_LOG_DIR') or base / 'logs'),
                                           valheim=valheim), encoding='utf-8')

    step(4, 'site-helpers', 'HN-UPD-104')
    print('Updating site helpers (your pages and identity stay as they are)...', flush=True)
    source = runtime / 'site' / 'web'
    for helper in ('publicar.py', 'values.py', 'sync_modpack.py', 'identidade.py', 'navegacao.py', 'sistema.py',
                   'cronicas.html'):
        shutil.copy2(source / helper, site / helper)
    assets = source / 'assets'
    for name in ('vivo.js', 'modpack.js', 'mod-placeholder.svg', 'navegacao.js', 'navegacao.css', 'sagas-resumo.js',
                 'sagas-resumo.css', 'sagas-halls.js', 'sagas-halls.css', 'historias-bg.webp',
                 'historias-layout.css', 'boss-fights.js', 'boss-fights.css'):
        (site / 'assets').mkdir(parents=True, exist_ok=True)
        shutil.copy2(assets / name, site / 'assets' / name)
    for art in [*assets.glob('armaria-*.webp')]:
        shutil.copy2(art, site / 'assets' / art.name)
    for folder_name in ('boss-fights', 'fontes'):
        if (assets / folder_name).is_dir():
            shutil.copytree(assets / folder_name, site / 'assets' / folder_name, dirs_exist_ok=True)
    for template in (source / 'modelos-pagina').glob('*.html'):
        destination = site / 'modelos-pagina' / template.name
        if not destination.exists():
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(template, destination)
    for keep, origin in (('marca/favicon.svg', source / 'marca' / 'favicon.svg'),
                         ('identidade.json', source / 'identidade.json')):
        if not (site / keep).exists():
            (site / keep).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(origin, site / keep)
    done = run([str(venv_python), '-X', 'utf8', str(source / 'migrar-paginas.py'), str(source), str(site)])
    if done.returncode:
        print(done.stderr[-800:], file=sys.stderr)
        fail('HN-UPD-104', 'pages')

    step(5, 'publish', 'HN-UPD-105')
    print('Publishing the site...', flush=True)
    environment = {**os.environ, **env, 'HEIMDALL_WEB_DIR': str(web), 'HEIMDALL_SITE_DIR': str(site),
                   'HEIMDALL_ROOT': str(runtime)}
    done = run([str(venv_python), '-X', 'utf8', str(site / 'publicar.py')], env=environment)
    if done.returncode:
        print(done.stderr[-800:], file=sys.stderr)
        fail('HN-UPD-105', 'publish')

    step(6, 'bridge-and-version', 'HN-UPD-106')
    bridge = valheim / 'current' / 'BepInEx' / 'plugins' / 'HeimdallSagas' / 'HeimdallSagas.Bridge.dll'
    new_bridge = ROOT / 'dist' / 'sagas' / 'HeimdallSagas.Bridge.dll'
    bridge_updated = False
    if bridge.is_file() and not bridge.is_symlink() and new_bridge.is_file() and \
            not filecmp.cmp(new_bridge, bridge, shallow=False):
        print('Updating the Heimdall Sagas bridge (restart Valheim to load it)...', flush=True)
        # The game locks its plugins while it runs: the new file takes over on its next start.
        staged = bridge.with_suffix('.dll.new')
        shutil.copy2(new_bridge, staged)
        try:
            os.replace(staged, bridge)
        except PermissionError:
            print('Valheim is running: the bridge is replaced when the Heimdall update runs again '
                  'with the server stopped.', flush=True)
            staged.unlink(missing_ok=True)
        else:
            bridge_updated = True

    def git(*args: str) -> str:
        try:
            return run(['git', '-c', f'safe.directory={ROOT}', '-C', str(ROOT), *args], timeout=15).stdout.strip()
        except OSError:
            return ''
    commit = git('rev-parse', 'HEAD')
    branch = os.environ.get('HEIMDALL_UPDATE_BRANCH') or git('rev-parse', '--abbrev-ref', 'HEAD')
    info = {'commit': commit, 'short': commit[:7], 'subject': git('log', '-1', '--format=%s')[:200],
            'date': int(git('log', '-1', '--format=%ct') or 0), 'branch': '' if branch == 'HEAD' else branch,
            'version': (runtime / 'deploy' / 'VERSION').read_text(encoding='ascii').strip(),
            'updated_at': int(time.time()), 'bridge_updated': bridge_updated,
            'from_panel': ROOT.resolve() == (state / 'source').resolve()}
    (runtime / '.heimdall-version.json').write_text(json.dumps(info, ensure_ascii=False) + '\n', encoding='utf-8')

    step(7, 'restart-panel', 'HN-UPD-108')
    print('Restarting the panel...', flush=True)
    for name in reversed(PYTHON_SERVICES):
        sc('start', name)
    if not all(wait_state(name, 'RUNNING') for name in ('heimdall-executor', 'heimdall-panel')):
        fail('HN-UPD-108', 'panel-not-running')
    print(f'Heimdall Nexus updated to {git("log", "-1", "--format=%h %s") or "this checkout"}.', flush=True)
    print('The Valheim server was not restarted.', flush=True)
    print('::heimdall done', flush=True)


if __name__ == '__main__':
    try:
        main()
    except SystemExit:
        raise
    except Exception as error:  # noqa: BLE001 - reported as the current step's failure
        print(f'{type(error).__name__}: {error}', file=sys.stderr, flush=True)
        fail(step_code, 'error')
