"""Linux: systemd, journald, POSIX accounts and a unix socket for the executor."""
from __future__ import annotations

import fcntl
import grp
import os
import pwd
import re
import socket
import socketserver
import subprocess
from pathlib import Path

DEFAULTS = {
    'HEIMDALL_VALHEIM_DIR': '/srv/valheim',
    'HEIMDALL_STATE_DIR': '/var/lib/heimdall-nexus',
    'HEIMDALL_PANEL_STATE_DIR': '/var/lib/heimdall-panel',
    'HEIMDALL_SAGAS_DIR': '/var/lib/heimdall-nexus/sagas',
    'HEIMDALL_PANEL_SOCKET': '/run/heimdall-panel/executor.sock',
    'HEIMDALL_PANEL_AUDIT_FILE': '/var/log/heimdall-panel/auditoria.jsonl',
    'HEIMDALL_PANEL_BACKUP_DIR': '/var/backups/heimdall-panel',
    'HEIMDALL_MAINTENANCE_LOCK': '/run/lock/heimdall-maintenance.lock',
    'HEIMDALL_WEB_DIR': '/srv/heimdall-web',
    'HEIMDALL_WEB_BACKUP_DIR': '/var/backups/heimdall-web',
    'HEIMDALL_ROOT': '/opt/heimdall-nexus',
    'HEIMDALL_ENV_FILE': '/etc/heimdall-nexus/heimdall.env',
    'PAINEL_CONFIG': '/etc/heimdall-panel/config.json',
    'HEIMDALL_MODPACK_CACHE': '/var/cache/heimdall-modpack',
}

PYTHON = '/usr/bin/python3'
STEAMCMD = 'steamcmd.sh'
GAME_EXECUTABLE = 'valheim_server.x86_64'


# ---------------------------------------------------------------- services
def service_show(name: str, properties: list[str]) -> dict[str, str]:
    result = subprocess.run(['systemctl', 'show', name, '--no-page',
                             '--property=' + ','.join(properties)],
                            capture_output=True, text=True, timeout=15)
    return dict(line.split('=', 1) for line in result.stdout.strip().splitlines() if '=' in line)


def service_action(action: str, name: str, timeout: int = 240) -> subprocess.CompletedProcess:
    """start, stop, restart, enable or disable; the result keeps returncode and stderr."""
    return subprocess.run(['systemctl', action, name], capture_output=True, text=True,
                          timeout=timeout)


def service_is_active(name: str) -> bool:
    return subprocess.run(['systemctl', 'is-active', '--quiet', name]).returncode == 0


def service_active_seconds(name: str) -> float | None:
    """Seconds since the service became active, or None if it is not or unknown.

    The monotonic property avoids timezone mistakes in systemctl's formatted time.
    """
    import time
    value = service_show(name, ['ActiveEnterTimestampMonotonic']).get('ActiveEnterTimestampMonotonic', '')
    try:
        started = int(value)
    except ValueError:
        return None
    return max(0.0, time.monotonic() - started / 1e6) if started else None


def service_logs(name: str, lines: int, since: str | None = None) -> list[str]:
    command = ['journalctl', '-u', name, '--no-pager', '-n', str(lines), '-o', 'short-iso']
    if since:
        command += ['--since', since]
    return subprocess.run(command, capture_output=True, text=True, timeout=30).stdout.splitlines()


def service_logged_since_start(name: str, text: str, invocation: str | None = None) -> bool:
    """Whether the current run of the service logged `text`.

    Tied to the systemd invocation, so a previous run never counts.
    """
    invocation = invocation or service_show(name, ['InvocationID']).get('InvocationID', '')
    if not re.fullmatch(r'[0-9a-f]{32}', invocation or ''):
        return False
    result = subprocess.run(['journalctl', '_SYSTEMD_INVOCATION_ID=' + invocation,
                             '--grep=' + text, '-n', '1', '--no-pager', '-o', 'cat'],
                            capture_output=True, text=True, timeout=10)
    return result.returncode == 0 and text in result.stdout


def service_log_text(name: str, lines: int) -> str:
    """The last `lines` lines the service logged, across runs, oldest first."""
    return subprocess.run(['journalctl', '-u', name, '--no-pager', '-n', str(lines)],
                          capture_output=True, text=True, timeout=60).stdout


def service_launcher(name: str) -> Path | None:
    result = subprocess.run(['systemctl', 'show', name, '-p', 'ExecStart', '--value'],
                            capture_output=True, text=True, timeout=15)
    match = re.search(r'path=([^ ;}]+)', result.stdout)
    return Path(match.group(1)) if match else None



def service_file(name: str) -> Path:
    """Where the service is defined, for backups."""
    return Path(os.environ.get('HEIMDALL_GAME_SERVICE_FILE') or f'/etc/systemd/system/{name}.service')


def timer_is_active(name: str) -> bool:
    """Whether the periodic job `name` (a systemd timer here) is scheduled."""
    try:
        return subprocess.run(['systemctl', 'is-active', '--quiet', name + '.timer'],
                              timeout=3, check=False).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def detached_job_start(unit: str, argv: list[str], log: Path, env: dict[str, str],
                       runner=subprocess.run) -> subprocess.CompletedProcess:
    """Run argv outside this service, so it survives the service's restart."""
    command = ['systemd-run', f'--unit={unit}', '--collect', '--quiet', '--no-block',
               f'--property=StandardOutput=append:{log}',
               f'--property=StandardError=append:{log}',
               *[f'--setenv={key}={value}' for key, value in env.items()], *argv]
    return runner(command, capture_output=True, text=True, timeout=30)


def detached_job_running(unit: str) -> bool:
    try:
        state = subprocess.run(['systemctl', 'is-active', unit + '.service'],
                               capture_output=True, text=True, timeout=5).stdout.strip()
        return state in ('active', 'activating', 'reloading')
    except (OSError, subprocess.TimeoutExpired):
        return False


GIT_SEARCH_PATH = '/usr/bin:/bin'


def git_available() -> bool:
    return any(Path(folder, 'git').is_file() for folder in ('/usr/bin', '/bin'))


# ---------------------------------------------------------------- files and accounts
chown = os.chown
lchown = os.lchown
fchown = os.fchown


def account_ids(name: str) -> tuple[int, int]:
    account = pwd.getpwnam(name)
    return account.pw_uid, account.pw_gid


def group_id(name: str) -> int:
    return grp.getgrnam(name).gr_gid


def account_exists(name: str) -> bool:
    try:
        pwd.getpwnam(name)
    except KeyError:
        return False
    return True


def link_directory(link: Path, target: Path) -> None:
    link.symlink_to(target, target_is_directory=True)


def exclusive_lock(path, blocking: bool = False):
    """Open and lock `path`; keep the returned file open to hold the lock.

    Raises BlockingIOError when another process holds it and blocking is False.
    """
    stream = open(path, 'w')
    try:
        fcntl.flock(stream, fcntl.LOCK_EX | (0 if blocking else fcntl.LOCK_NB))
    except BaseException:
        stream.close()
        raise
    return stream


def open_untrusted(path) -> int:
    """Read-only descriptor that refuses symlinks (and never blocks on a FIFO)."""
    return os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)


def copy_access(source, target) -> None:
    """Nothing to do here: callers keep owner and mode with chown and chmod."""


def run_as_game(argv: list[str]) -> list[str]:
    return ['runuser', '-u', 'valheim', '--', *argv]


def is_privileged() -> bool:
    return os.geteuid() == 0


# ---------------------------------------------------------------- executor channel
class ExecutorServer(socketserver.ThreadingUnixStreamServer):
    """Unix socket that only the panel's group can open."""
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, address, handler, panel_group: str):
        path = Path(address)
        path.parent.mkdir(parents=True, exist_ok=True)
        if path.exists():
            path.unlink()
        super().__init__(str(path), handler)
        os.chown(path, 0, grp.getgrnam(panel_group).gr_gid)
        os.chmod(path, 0o660)


def executor_connect(address, timeout: float) -> socket.socket:
    connection = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    connection.settimeout(timeout)
    try:
        connection.connect(str(address))
    except BaseException:
        connection.close()
        raise
    return connection
