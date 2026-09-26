"""Finds the host layer (servicos/painel/hostos) for scripts that run from the site folder.

The site helpers are copied out of the installation, so they look for it
through HEIMDALL_ROOT, the repository they came from, and the default
installation folders of each system. Updates and installers do not always pass
HEIMDALL_ROOT, so the defaults must be enough on their own.
"""
import os
import sys
from pathlib import Path


def _recorded_app() -> str:
    """Windows: where the installer put the code, possibly on another disk (HKLM, admin-only)."""
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r'SOFTWARE\HeimdallNexus', 0,
                            winreg.KEY_READ | winreg.KEY_WOW64_64KEY) as key:
            value = winreg.QueryValueEx(key, 'AppBase')[0]
        return str(Path(value) / 'app') if isinstance(value, str) and value else ''
    except (ImportError, OSError):
        return ''


_CANDIDATES = [os.environ.get('HEIMDALL_ROOT'), Path(__file__).resolve().parents[2],
               '/opt/heimdall-nexus', _recorded_app(),
               Path(os.environ.get('ProgramFiles', r'C:\Program Files')) / 'HeimdallNexus' / 'app']


def _has_layer(folder: Path) -> bool:
    try:
        return (folder / 'hostos' / '__init__.py').is_file()
    except OSError:  # a folder this account may not read is simply not the one
        return False


for _root in _CANDIDATES:
    _folder = Path(_root) / 'servicos' / 'painel' if _root else None
    if _folder and _has_layer(_folder):
        if str(_folder) not in sys.path:
            sys.path.insert(0, str(_folder))
        break
else:
    raise SystemExit('Heimdall Nexus code not found: set HEIMDALL_ROOT to the installation folder '
                     '(/opt/heimdall-nexus on Linux).')

import hostos  # noqa: E402,F401
