"""Where this Windows installation lives.

By default, code in %ProgramFiles%\\HeimdallNexus and data in
%ProgramData%\\HeimdallNexus. The desktop app can install everything under one
folder on another disk instead (<root>\\program and <root>\\data). The
installer records both folders in HKLM\\SOFTWARE\\HeimdallNexus, which only
administrators can change, so every script, service and the app find them.
An environment variable still wins, for tests and for the services' own setup.
"""
from __future__ import annotations

import os
from pathlib import Path

KEY = r'SOFTWARE\HeimdallNexus'


def recorded(name: str) -> str:
    """A value from HKLM\\SOFTWARE\\HeimdallNexus, or '' off Windows or before installing."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, KEY, 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            value, kind = winreg.QueryValueEx(key, name)
        return value if kind == winreg.REG_SZ and isinstance(value, str) else ''
    except (ImportError, OSError):
        return ''


def data_dir() -> Path:
    return Path(os.environ.get('HEIMDALL_BASE_DIR') or recorded('DataDir')
                or Path(os.environ.get('ProgramData', r'C:\ProgramData')) / 'HeimdallNexus')


def app_base() -> Path:
    return Path(os.environ.get('HEIMDALL_APP_BASE') or recorded('AppBase')
                or Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'HeimdallNexus')


def record(app: Path, data: Path, root: Path | None) -> None:
    """Written by the installer, as administrator."""
    import winreg
    with winreg.CreateKeyEx(winreg.HKEY_LOCAL_MACHINE, KEY, 0,
                            winreg.KEY_WRITE | winreg.KEY_WOW64_64KEY) as key:
        winreg.SetValueEx(key, 'AppBase', 0, winreg.REG_SZ, str(app))
        winreg.SetValueEx(key, 'DataDir', 0, winreg.REG_SZ, str(data))
        winreg.SetValueEx(key, 'Root', 0, winreg.REG_SZ, str(root) if root else '')
