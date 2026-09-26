"""Installs the optional Heimdall Sagas bridge on Windows (like deploy/install-sagas-extension.sh).

In PowerShell as administrator, from your checkout, with Valheim stopped:

    & "$env:ProgramFiles\\HeimdallNexus\\venv\\Scripts\\python.exe" deploy\\windows\\install-sagas.py dist\\sagas\\HeimdallSagas.Bridge.dll

The bridge goes into the game's BepInEx plugins, server.env tells it where the
Sagas inbox and settings live, and the Sagas jobs (import, stories, map) are
enabled. The game account may write the inbox and read the settings, nothing
more of the Sagas folder: story API keys live there too.
"""
from __future__ import annotations

import ctypes
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GAME = 'NT SERVICE\\heimdall-valheim'


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit(__doc__)
    try:
        admin = bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        admin = False
    if not admin:
        raise SystemExit('Run PowerShell as administrator.')
    bridge = Path(sys.argv[1]).resolve()
    if bridge.name != 'HeimdallSagas.Bridge.dll' or bridge.read_bytes()[:2] != b'MZ':
        raise SystemExit('Expected a built HeimdallSagas.Bridge.dll.')
    base = Path(os.environ.get('HEIMDALL_BASE_DIR') or Path(os.environ['ProgramData']) / 'HeimdallNexus')
    sys.path.insert(0, str(HERE))
    import run
    env = run.load_env(base / 'etc' / 'heimdall.env')
    state = Path(env.get('HEIMDALL_STATE_DIR') or base / 'state')
    if not (state / 'installed.json').is_file():
        raise SystemExit('Install Heimdall Nexus first.')
    game = Path(env.get('HEIMDALL_VALHEIM_DIR') or base / 'valheim')
    plugins = game / 'current' / 'BepInEx' / 'plugins'
    if not (game / 'current' / 'BepInEx' / 'core' / 'BepInEx.dll').is_file():
        raise SystemExit('BepInEx must be installed on the game server first.')
    sagas = Path(env.get('HEIMDALL_SAGAS_DIR') or state / 'sagas')
    for folder in (sagas, sagas / 'inbox', sagas / 'rejected'):
        folder.mkdir(parents=True, exist_ok=True)
    settings = sagas / 'settings.json'
    if not settings.exists():
        settings.write_text(json.dumps({'version': 1, 'enabled': True, 'gear': True, 'events': True,
                                        'clock': True, 'kill_mode': 'all'}) + '\n', encoding='utf-8')
    # The bridge reads its settings; the executor keeps this grant when it rewrites them.
    subprocess.run(['icacls', str(settings), '/grant', f'{GAME}:(R)', '/Q'], check=True, capture_output=True)

    target = plugins / 'HeimdallSagas' / 'HeimdallSagas.Bridge.dll'
    for part in (plugins, target.parent):
        if part.is_symlink() or part.is_junction():
            raise SystemExit(f'Unsafe game plugin directory: {part}')
    target.parent.mkdir(parents=True, exist_ok=True)
    staged = target.with_suffix('.dll.new')
    shutil.copyfile(bridge, staged)
    try:
        os.replace(staged, target)
    except PermissionError:
        staged.unlink(missing_ok=True)
        raise SystemExit('Valheim is using the bridge: stop the server in Jarl > Console and run this again.')

    server_env = game / 'server.env'
    lines = [line for line in server_env.read_text(encoding='utf-8').splitlines()
             if not line.startswith(('HEIMDALL_SAGAS_INBOX=', 'HEIMDALL_SAGAS_SETTINGS='))]
    lines += [f'HEIMDALL_SAGAS_INBOX={json.dumps(str(sagas / "inbox"))}',
              f'HEIMDALL_SAGAS_SETTINGS={json.dumps(str(settings))}']
    temporary = server_env.with_name('.server.env.sagas')
    temporary.write_text('\n'.join(lines) + '\n', encoding='utf-8')
    sys.path.insert(0, str(Path(env.get('HEIMDALL_ROOT') or HERE.parents[1]) / 'servicos' / 'painel'))
    import hostos
    hostos.copy_access(server_env, temporary)  # stays read-only for the game
    os.replace(temporary, server_env)

    jobs_file = state / 'jobs.json'
    try:
        jobs = json.loads(jobs_file.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        jobs = {}
    jobs.update({'heimdall-sagas-ingest': True, 'heimdall-sagas-story': True, 'heimdall-sagas-atlas': True})
    jobs_file.write_text(json.dumps(jobs, indent=2) + '\n', encoding='utf-8')
    print('Heimdall Sagas bridge installed. Start Valheim in Jarl > Console to load it.')


if __name__ == '__main__':
    main()
