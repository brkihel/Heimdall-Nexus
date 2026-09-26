"""Host operating system layer: everything Heimdall Nexus does differently on Linux and Windows.

The rest of the code asks this package for services, logs, locks, file
ownership, the executor channel and default paths, and never calls systemctl,
journalctl, fcntl, pwd or grp directly. Linux keeps its exact behavior; Windows
maps each operation to its native counterpart (Windows services, log files,
NTFS inheritance, an authenticated loopback channel).

Service data keeps systemd's vocabulary (ActiveState, SubState,
ActiveEnterTimestamp, MemoryCurrent, NRestarts, InvocationID) on both systems,
so the panel and its pages read one format.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

IS_WINDOWS = sys.platform == 'win32'

if IS_WINDOWS:
    from . import _windows as _impl
else:
    from . import _linux as _impl

DEFAULTS: dict[str, str] = _impl.DEFAULTS

# Tools run by the executor use this interpreter.
PYTHON: str = _impl.PYTHON
# os.open flags that do not exist on Windows are harmless zeros there.
O_NOFOLLOW: int = getattr(os, 'O_NOFOLLOW', 0)
O_NONBLOCK: int = getattr(os, 'O_NONBLOCK', 0)


def env_path(name: str, fallback: str | None = None) -> Path:
    """A path setting: the environment wins, then this system's default."""
    value = os.environ.get(name)
    if value:
        return Path(value)
    default = DEFAULTS.get(name, fallback)
    if default is None:
        raise KeyError(f'no default path for {name}')
    return Path(default)


def env_value(name: str) -> str:
    """A text setting: the environment wins, then this system's default."""
    return os.environ.get(name) or DEFAULTS[name]


# Executable names that differ per system.
STEAMCMD: str = _impl.STEAMCMD
GAME_EXECUTABLE: str = _impl.GAME_EXECUTABLE


# ---------------------------------------------------------------- services
service_show = _impl.service_show
service_action = _impl.service_action
service_is_active = _impl.service_is_active
service_active_seconds = _impl.service_active_seconds
service_logs = _impl.service_logs
service_logged_since_start = _impl.service_logged_since_start
service_log_text = _impl.service_log_text
service_launcher = _impl.service_launcher
timer_is_active = _impl.timer_is_active
service_file = _impl.service_file

# ---------------------------------------------------------------- one-off jobs and tools
detached_job_start = _impl.detached_job_start
detached_job_running = _impl.detached_job_running
git_available = _impl.git_available
GIT_SEARCH_PATH: str = _impl.GIT_SEARCH_PATH

# ---------------------------------------------------------------- files and accounts
chown = _impl.chown
lchown = _impl.lchown
fchown = _impl.fchown
account_ids = _impl.account_ids
group_id = _impl.group_id
account_exists = _impl.account_exists
link_directory = _impl.link_directory
exclusive_lock = _impl.exclusive_lock
run_as_game = _impl.run_as_game
open_untrusted = _impl.open_untrusted
copy_access = _impl.copy_access
is_privileged = _impl.is_privileged

# ---------------------------------------------------------------- executor channel
ExecutorServer = _impl.ExecutorServer
executor_connect = _impl.executor_connect
