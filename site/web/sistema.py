"""Finds the host layer (servicos/painel/hostos) for scripts that run from the site folder.

The site helpers are copied out of the installation, so they locate it through
HEIMDALL_ROOT, or through the repository when run from a checkout.
"""
import os
import sys
from pathlib import Path

for _root in (os.environ.get('HEIMDALL_ROOT'), Path(__file__).resolve().parents[2]):
    _folder = Path(_root) / 'servicos' / 'painel' if _root else None
    if _folder and (_folder / 'hostos').is_dir():
        if str(_folder) not in sys.path:
            sys.path.insert(0, str(_folder))
        break

import hostos  # noqa: E402,F401
