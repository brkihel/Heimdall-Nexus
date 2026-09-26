"""Starts the Valheim dedicated server on Windows (the counterpart of deploy/valheim-launch.sh).

The heimdall-valheim Windows service runs this file. It reads server.env
(written by the installer and by Jarl > Server Config), builds the same
arguments as the Linux launcher, and then:

- starts a fresh, timestamped log file on every start, keeping three older
  ones, so "the current run" is simply the current file;
- writes a run record (invocation id, start time, game process id) that the
  host layer reports in systemd's vocabulary;
- lets the game handle Ctrl+C: stopping the service sends it to the whole
  console, Valheim saves the world and exits, and this launcher waits for it.

Supported settings, like the Linux launcher: VH_MODIFIERS_MANAGED VH_PASSWORD.
"""
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

SERVICE = os.environ.get('HEIMDALL_GAME_SERVICE') or 'heimdall-valheim'
# The options Valheim's own "host a server" screen offers; nothing else passes.
MODIFIERS = {
    'combat': ('veryeasy', 'easy', 'hard', 'veryhard'),
    'deathpenalty': ('casual', 'veryeasy', 'easy', 'hard', 'hardcore'),
    'resources': ('muchless', 'less', 'more', 'muchmore', 'most'),
    'raids': ('none', 'muchless', 'less', 'more', 'muchmore'),
    'portals': ('casual', 'hard', 'veryhard'),
}
WORLD_KEYS = ('playerevents', 'fire', 'nomap', 'passivemobs', 'nobuildcost')
STOP_GRACE_SECONDS = 120
OLD_LOGS_KEPT = 3


class LaunchError(Exception):
    """A setting the game must not start with."""


def parse_env(text: str) -> dict[str, str]:
    """server.env as systemd's EnvironmentFile reads it.

    The installer writes "..." with backslash escapes and Jarl writes JSON
    strings; both are double-quoted, and single quotes and bare values work too.
    """
    values = {}
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#') or '=' not in stripped:
            continue
        key, raw = stripped.split('=', 1)
        key, raw = key.strip(), raw.strip()
        if raw.startswith('"') and raw.endswith('"') and len(raw) >= 2:
            try:
                value = json.loads(raw)
            except ValueError:
                value = raw[1:-1].replace('\\"', '"').replace('\\\\', '\\')
        elif raw.startswith("'") and raw.endswith("'") and len(raw) >= 2:
            value = raw[1:-1]
        else:
            value = raw
        values[key] = str(value)
    return values


def build_arguments(env: dict[str, str], report=print) -> list[str]:
    """The game's command line, checked the same way as the Linux launcher."""
    for required in ('VH_NAME', 'VH_PORT', 'VH_WORLD', 'VH_SAVEDIR'):
        if not env.get(required):
            raise LaunchError(f'{required} is missing from server.env')
    args = ['-name', env['VH_NAME'], '-port', env['VH_PORT'], '-world', env['VH_WORLD'],
            '-savedir', env['VH_SAVEDIR'], '-public', env.get('VH_PUBLIC') or '0',
            '-nographics', '-batchmode']
    if env.get('VH_PASSWORD'):
        args += ['-password', env['VH_PASSWORD']]
    if env.get('VH_CROSSPLAY') == '1':
        args.append('-crossplay')
    # World modifiers from Jarl > Server Config. Only when the admin opted in:
    # -resetmodifiers clears the world's current choices before applying these.
    if env.get('VH_MODIFIERS_MANAGED') == '1':
        args.append('-resetmodifiers')
        for pair in (env.get('VH_MODIFIERS') or '').split(','):
            if not pair:
                continue
            name, _, value = pair.partition('=')
            if value in MODIFIERS.get(name, ()):
                args += ['-modifier', name, value]
            else:
                report(f'Ignoring unknown world modifier: {pair}')
        for key in (env.get('VH_SETKEYS') or '').split(','):
            if not key:
                continue
            if key in WORLD_KEYS:
                args += ['-setkey', key]
            else:
                report(f'Ignoring unknown world key: {key}')
    return args


def bepinex_arguments(game: Path, enabled: bool) -> list[str]:
    """Doorstop (winhttp.dll) loads BepInEx; its switches follow VH_BEPINEX.

    Without BepInEx selected, a leftover winhttp.dll must not load mods.
    """
    if not (game / 'winhttp.dll').is_file():
        if enabled:
            raise LaunchError('BepInEx was selected but its loader (winhttp.dll) is missing.')
        return []
    if not enabled:
        return ['--doorstop-enabled', 'false']
    preloader = game / 'BepInEx' / 'core' / 'BepInEx.Preloader.dll'
    if not preloader.is_file():
        raise LaunchError('BepInEx was selected but its preloader is missing.')
    return ['--doorstop-enabled', 'true', '--doorstop-target-assembly', str(preloader)]


def _stamp() -> str:
    return datetime.now().astimezone().strftime('%Y-%m-%dT%H:%M:%S%z')


def _rotate(log: Path) -> None:
    for index in range(OLD_LOGS_KEPT, 0, -1):
        older = log.with_name(f'{log.stem}.{index}{log.suffix}')
        newer = log if index == 1 else log.with_name(f'{log.stem}.{index - 1}{log.suffix}')
        if newer.exists():
            os.replace(newer, older)


def main() -> int:
    base = Path(os.environ.get('HEIMDALL_BASE_DIR')
                or Path(os.environ.get('ProgramData', r'C:\ProgramData')) / 'HeimdallNexus')
    valheim = Path(os.environ.get('HEIMDALL_VALHEIM_DIR') or base / 'valheim')
    logs = Path(os.environ.get('HEIMDALL_LOG_DIR') or base / 'logs')
    runs = Path(os.environ.get('HEIMDALL_RUN_DIR') or base / 'run')
    env_file = Path(sys.argv[1]) if len(sys.argv) > 1 else valheim / 'server.env'
    logs.mkdir(parents=True, exist_ok=True)
    runs.mkdir(parents=True, exist_ok=True)
    log_path = logs / f'{SERVICE}.log'
    _rotate(log_path)
    log = open(log_path, 'a', encoding='utf-8', errors='replace', buffering=1)

    def write(line: str) -> None:
        log.write(f'{_stamp()} {SERVICE}: {line}\n')

    try:
        settings = parse_env(env_file.read_text(encoding='utf-8'))
        game = Path(settings.get('VH_GAMEDIR') or valheim / 'current')
        arguments = build_arguments(settings, write)
        arguments = bepinex_arguments(game, settings.get('VH_BEPINEX') == '1') + arguments
        executable = game / 'valheim_server.exe'
        if not executable.is_file():
            raise LaunchError(f'{executable} does not exist')
    except (OSError, LaunchError) as error:
        write(f'Refusing to start: {error}')
        log.close()
        return 78  # EX_CONFIG: the service manager should not loop on it

    environment = {**os.environ, 'SteamAppId': '892970'}
    # Ctrl+C from the service stop reaches every process on this console, the
    # game included; this launcher only waits for the game to finish saving.
    signal.signal(signal.SIGINT, lambda *_: None)
    signal.signal(signal.SIGBREAK, lambda *_: None)
    write('Starting ' + subprocess.list2cmdline([str(executable), *[
        '***' if index > 0 and arguments[index - 1] == '-password' else value
        for index, value in enumerate(arguments)]]))
    game_process = subprocess.Popen([str(executable), *arguments], cwd=game, env=environment,
                                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                    stderr=subprocess.STDOUT)
    record = {'invocation': uuid.uuid4().hex, 'started': time.time(), 'pid': game_process.pid,
              'launcher_pid': os.getpid(), 'restarts': 0}
    run_file = runs / f'{SERVICE}.run.json'
    run_file.write_text(json.dumps(record), encoding='utf-8')
    try:
        for raw in game_process.stdout:
            line = raw.decode('utf-8', 'replace').rstrip('\r\n')
            if line:
                write(line)
    finally:
        try:
            code = game_process.wait(timeout=STOP_GRACE_SECONDS)
        except subprocess.TimeoutExpired:
            write(f'The game did not exit {STOP_GRACE_SECONDS} s after the stop request; ending it.')
            game_process.kill()
            code = game_process.wait()
        write(f'Game exited with code {code}')
        log.close()
    return code


if __name__ == '__main__':
    sys.exit(main())
