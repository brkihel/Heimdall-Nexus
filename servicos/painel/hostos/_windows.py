"""Windows: Windows services, log files, NTFS inheritance and an authenticated loopback channel.

Each Heimdall service is a Windows service (WinSW wraps the processes). The
game runs through launcher-windows.py, which starts a fresh log file and a run
record on every start, so "the current run" is simply the current file.

Ownership calls are no-ops: the installer gives each data folder inheritable
permissions, so every file created inside it gets the right access by itself.

The executor listens on 127.0.0.1 only. Both sides prove they know a secret
that only SYSTEM, administrators and the panel's service account can read, in
a challenge-response that never sends the secret, so a program that grabs the
port first learns nothing.
"""
from __future__ import annotations

import ctypes
import hashlib
import json
import msvcrt
import os
import re
import socket
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

from . import _channel

# Data lives in ProgramData; code in Program Files, where only administrators write.
BASE = Path(os.environ.get('HEIMDALL_BASE_DIR')
            or Path(os.environ.get('ProgramData', r'C:\ProgramData')) / 'HeimdallNexus')
APP_BASE = Path(os.environ.get('HEIMDALL_APP_BASE')
                or Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'HeimdallNexus')

DEFAULTS = {
    'HEIMDALL_VALHEIM_DIR': str(BASE / 'valheim'),
    'HEIMDALL_STATE_DIR': str(BASE / 'state'),
    'HEIMDALL_PANEL_STATE_DIR': str(BASE / 'panel'),
    'HEIMDALL_SAGAS_DIR': str(BASE / 'state' / 'sagas'),
    'HEIMDALL_PANEL_SOCKET': '127.0.0.1:8792',
    'HEIMDALL_EXECUTOR_KEY_FILE': str(BASE / 'etc' / 'executor.key'),
    'HEIMDALL_PANEL_AUDIT_FILE': str(BASE / 'logs' / 'auditoria.jsonl'),
    'HEIMDALL_PANEL_BACKUP_DIR': str(BASE / 'backups' / 'panel'),
    'HEIMDALL_MAINTENANCE_LOCK': str(BASE / 'run' / 'heimdall-maintenance.lock'),
    'HEIMDALL_WEB_DIR': str(BASE / 'web'),
    'HEIMDALL_WEB_BACKUP_DIR': str(BASE / 'backups' / 'web'),
    'HEIMDALL_ROOT': str(APP_BASE / 'app'),
    'HEIMDALL_ENV_FILE': str(BASE / 'etc' / 'heimdall.env'),
    'HEIMDALL_LOG_DIR': str(BASE / 'logs'),
    'HEIMDALL_RUN_DIR': str(BASE / 'run'),
    'PAINEL_CONFIG': str(BASE / 'etc' / 'panel.json'),
    'HEIMDALL_MODPACK_CACHE': str(BASE / 'cache' / 'modpack'),
}

PYTHON = sys.executable
STEAMCMD = 'steamcmd.exe'
GAME_EXECUTABLE = 'valheim_server.exe'

# Periodic jobs run inside two services instead of systemd timers (see
# deploy/windows/jobs.py): one as SYSTEM, one as the panel's account.
JOB_SERVICES = {
    'heimdall-status': 'heimdall-jobs', 'heimdall-saga': 'heimdall-jobs',
    'heimdall-schedule': 'heimdall-jobs',
    'heimdall-sagas-ingest': 'heimdall-sagas-jobs', 'heimdall-sagas-story': 'heimdall-sagas-jobs',
    'heimdall-sagas-atlas': 'heimdall-sagas-jobs',
}


def _setting(name: str) -> Path:
    return Path(os.environ.get(name) or DEFAULTS[name])


# ---------------------------------------------------------------- services
_STATES = {  # SERVICE_* state -> systemd ActiveState, SubState
    1: ('inactive', 'dead'), 2: ('activating', 'start'), 3: ('deactivating', 'stop'),
    4: ('active', 'running'), 5: ('activating', 'continue'), 6: ('deactivating', 'pause'),
    7: ('inactive', 'paused'),
}


def _scm():
    import win32service  # pywin32
    return win32service


def _query(name: str) -> tuple[int, int] | None:
    """(state, pid) of a service, or None if it does not exist."""
    ws = _scm()
    manager = ws.OpenSCManager(None, None, ws.SC_MANAGER_CONNECT)
    try:
        try:
            handle = ws.OpenService(manager, name, ws.SERVICE_QUERY_STATUS)
        except Exception:  # noqa: BLE001 - pywintypes.error: not installed
            return None
        try:
            status = ws.QueryServiceStatusEx(handle)
            return status['CurrentState'], status['ProcessId']
        finally:
            ws.CloseServiceHandle(handle)
    finally:
        ws.CloseServiceHandle(manager)


def _run_record(name: str) -> dict:
    """What launcher-windows.py wrote when this service last started."""
    try:
        return json.loads((_setting('HEIMDALL_RUN_DIR') / f'{name}.run.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return {}


def _process_tree(pid: int):
    import psutil
    try:
        root = psutil.Process(pid)
        return [root, *root.children(recursive=True)]
    except psutil.Error:
        return []


def service_show(name: str, properties: list[str]) -> dict[str, str]:
    found = _query(name)
    if found is None:
        values = {'ActiveState': 'inactive', 'SubState': 'dead', 'LoadState': 'not-found'}
        return {key: values.get(key, '') for key in properties}
    state, pid = found
    active, sub = _STATES.get(state, ('unknown', 'unknown'))
    values = {'ActiveState': active, 'SubState': sub, 'LoadState': 'loaded',
              'NRestarts': str(_run_record(name).get('restarts', 0))}
    tree = _process_tree(pid) if pid else []
    if tree:
        import psutil
        memory = 0
        for process in tree:
            try:
                memory += process.memory_info().rss
            except psutil.Error:
                pass
        values['MemoryCurrent'] = str(memory)
        started = tree[0].create_time()
        stamp = datetime.fromtimestamp(started).astimezone().strftime('%a %Y-%m-%d %H:%M:%S %z')
        values['ActiveEnterTimestamp'] = values['ExecMainStartTimestamp'] = stamp
        values['ActiveEnterTimestampMonotonic'] = str(int((time.monotonic() - (time.time() - started)) * 1e6))
        record = _run_record(name)
        values['InvocationID'] = record.get('invocation') or hashlib.md5(
            f'{name}:{pid}:{started}'.encode()).hexdigest()
    return {key: values.get(key, '') for key in properties}


def _wait_for(name: str, wanted: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        found = _query(name)
        if found and found[0] == wanted:
            return True
        time.sleep(0.5)
    return False


def service_action(action: str, name: str, timeout: int = 240) -> subprocess.CompletedProcess:
    """start, stop, restart, enable or disable, waiting like systemctl does."""
    ws = _scm()
    import win32serviceutil
    if _query(name) is None:
        return subprocess.CompletedProcess([action, name], 5, '', f'Unit {name} not found.')
    try:
        if action in ('stop', 'restart'):
            if _query(name)[0] != 1:
                win32serviceutil.StopService(name)
                if not _wait_for(name, 1, timeout):
                    return subprocess.CompletedProcess([action, name], 1, '', f'{name} did not stop in time.')
        if action in ('start', 'restart'):
            if _query(name)[0] != 4:
                win32serviceutil.StartService(name)
                if not _wait_for(name, 4, min(timeout, 120)):
                    return subprocess.CompletedProcess([action, name], 1, '', f'{name} did not start.')
        if action in ('enable', 'disable'):
            start = ws.SERVICE_AUTO_START if action == 'enable' else ws.SERVICE_DEMAND_START
            manager = ws.OpenSCManager(None, None, ws.SC_MANAGER_CONNECT)
            handle = ws.OpenService(manager, name, ws.SERVICE_CHANGE_CONFIG)
            try:
                ws.ChangeServiceConfig(handle, ws.SERVICE_NO_CHANGE, start, ws.SERVICE_NO_CHANGE,
                                       None, None, 0, None, None, None, None)
            finally:
                ws.CloseServiceHandle(handle)
                ws.CloseServiceHandle(manager)
    except Exception as error:  # noqa: BLE001 - pywintypes.error carries the reason
        return subprocess.CompletedProcess([action, name], 1, '', str(error)[:300])
    return subprocess.CompletedProcess([action, name], 0, '', '')


def service_is_active(name: str) -> bool:
    found = _query(name)
    return bool(found and found[0] == 4)


def service_active_seconds(name: str) -> float | None:
    found = _query(name)
    if not found or found[0] != 4 or not found[1]:
        return None
    tree = _process_tree(found[1])
    return max(0.0, time.time() - tree[0].create_time()) if tree else None


def _log_files(name: str) -> list[Path]:
    """The launcher's timestamped log, or WinSW's output and error logs."""
    logs = _setting('HEIMDALL_LOG_DIR')
    own = logs / f'{name}.log'
    if own.is_file():
        return [own]
    return [path for path in (logs / f'{name}.out.log', logs / f'{name}.err.log') if path.is_file()]


def _tail(path: Path, lines: int) -> list[str]:
    with open(path, 'rb') as stream:
        stream.seek(0, os.SEEK_END)
        size = stream.tell()
        stream.seek(max(0, size - max(65536, lines * 400)))
        data = stream.read()
    return data.decode('utf-8', 'replace').splitlines()[-lines:]


def service_logs(name: str, lines: int, since: str | None = None) -> list[str]:
    result: list[str] = []
    for path in _log_files(name):
        result += _tail(path, lines)
    if since:
        result = [line for line in result if line[:19] >= since.replace(' ', 'T')[:19]
                  or not re.match(r'\d{4}-\d\d-\d\dT', line)]
    return result[-lines:]


def service_logged_since_start(name: str, text: str, invocation: str | None = None) -> bool:
    """The launcher starts a new log file on every start: the file is the current run."""
    if not service_is_active(name):
        return False
    for path in _log_files(name):
        try:
            with open(path, 'r', encoding='utf-8', errors='replace') as stream:
                if any(text in line for line in stream):
                    return True
        except OSError:
            pass
    return False


def service_log_text(name: str, lines: int) -> str:
    logs = _setting('HEIMDALL_LOG_DIR')
    older = sorted(logs.glob(f'{name}.*.log'), key=lambda path: path.stat().st_mtime)
    text = []
    for path in [*older, *_log_files(name)]:
        try:
            text += _tail(path, lines)
        except OSError:
            pass
    return '\n'.join(text[-lines:])


def service_launcher(name: str) -> Path | None:
    root = Path(os.environ.get('HEIMDALL_ROOT') or DEFAULTS['HEIMDALL_ROOT'])
    launcher = root / 'deploy' / 'windows' / 'launcher-windows.py'
    return launcher if name and launcher.is_file() else None


def service_file(name: str) -> Path:
    """Where the service is defined (its WinSW file), for backups."""
    return Path(os.environ.get('HEIMDALL_GAME_SERVICE_FILE') or BASE / 'services' / f'{name}.xml')


def _enabled_jobs() -> set[str]:
    try:
        data = json.loads((_setting('HEIMDALL_STATE_DIR') / 'jobs.json').read_text(encoding='utf-8'))
        return {name for name, on in data.items() if on is True}
    except (OSError, ValueError, AttributeError):
        return set()


def timer_is_active(name: str) -> bool:
    """Whether the periodic job is enabled and its host service is running."""
    host = JOB_SERVICES.get(name)
    return bool(host) and name in _enabled_jobs() and service_is_active(host)


def _powershell(script: str, timeout: int = 30) -> subprocess.CompletedProcess:
    return subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', script],
                          capture_output=True, text=True, timeout=timeout)


def _ps_quote(value) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def detached_job_start(unit: str, argv: list[str], log: Path, env: dict[str, str],
                       runner=None) -> subprocess.CompletedProcess:  # noqa: ARG001
    """A one-off scheduled task as SYSTEM: it outlives the service that starts it."""
    script = Path(log).with_suffix('.cmd')
    lines = ['@echo off', 'chcp 65001 >nul']
    lines += [f'set "{key}={value}"' for key, value in env.items()]
    lines.append(subprocess.list2cmdline(argv) + f' >> "{log}" 2>&1')
    script.write_text('\r\n'.join(lines) + '\r\n', encoding='utf-8')
    return _powershell(
        f"$a = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument ('/d /c \"' + {_ps_quote(script)} + '\"'); "
        f"$p = New-ScheduledTaskPrincipal -UserId 'SYSTEM' -LogonType ServiceAccount -RunLevel Highest; "
        f"$s = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 2) -AllowStartIfOnBatteries; "
        f"Register-ScheduledTask -TaskName {_ps_quote(unit)} -Action $a -Principal $p -Settings $s -Force | Out-Null; "
        f"Start-ScheduledTask -TaskName {_ps_quote(unit)}", timeout=60)


def detached_job_running(unit: str) -> bool:
    try:
        return _powershell(f"(Get-ScheduledTask -TaskName {_ps_quote(unit)} -ErrorAction SilentlyContinue).State",
                           timeout=15).stdout.strip() == 'Running'
    except (OSError, subprocess.TimeoutExpired):
        return False


GIT_SEARCH_PATH = os.environ.get('PATH', '')


def git_available() -> bool:
    import shutil
    return shutil.which('git') is not None


# ---------------------------------------------------------------- files and accounts
def chown(path, uid, gid, *, follow_symlinks=True):  # noqa: ARG001 - NTFS inheritance
    return None


def lchown(path, uid, gid):  # noqa: ARG001
    return None


def fchown(fd, uid, gid):  # noqa: ARG001
    return None


def account_ids(name: str) -> tuple[int, int]:  # noqa: ARG001
    return -1, -1


def group_id(name: str) -> int:  # noqa: ARG001
    return -1


def account_exists(name: str) -> bool:  # noqa: ARG001
    """POSIX accounts do not exist here; callers skip their chown work."""
    return False


def link_directory(link: Path, target: Path) -> None:
    """A junction: unlike a symlink, it needs no special privilege."""
    import _winapi
    _winapi.CreateJunction(str(target), str(link))


class _Locked:
    """Open file holding a byte-range lock on its first byte until closed."""

    def __init__(self, fd: int):
        self._fd = fd
        self.closed = False

    def close(self):
        if not self.closed:
            try:
                os.lseek(self._fd, 0, os.SEEK_SET)
                msvcrt.locking(self._fd, msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
            os.close(self._fd)
            self.closed = True

    def fileno(self):
        return self._fd

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def exclusive_lock(path, blocking: bool = False):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT)
    try:
        while True:
            try:
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                return _Locked(fd)
            except OSError as error:
                if not blocking:
                    raise BlockingIOError(str(error)) from error
                time.sleep(0.5)
    except BaseException:
        os.close(fd)
        raise


def run_as_game(argv: list[str]) -> list[str]:
    """The executor runs as SYSTEM; files it writes inherit the game's access."""
    return list(argv)


def is_privileged() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


# ---------------------------------------------------------------- executor channel
class ExecutorServer(_channel.LoopbackExecutorServer):
    def __init__(self, address, handler, panel_group: str = ''):  # noqa: ARG002
        super().__init__(address, handler, _setting('HEIMDALL_EXECUTOR_KEY_FILE'))


def executor_connect(address, timeout: float) -> socket.socket:
    return _channel.connect(address, timeout, _setting('HEIMDALL_EXECUTOR_KEY_FILE'))
