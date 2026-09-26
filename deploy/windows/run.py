"""Entry point of every Heimdall Windows service, like systemd's EnvironmentFile.

Loads heimdall.env into the environment and then runs a script or module:

    python -X utf8 run.py <script.py> [arguments]
    python -X utf8 run.py -m <module> [arguments]

Keeping the settings in one file (instead of inside each service definition)
lets the panel and updates change them without re-registering services.
"""
from __future__ import annotations

import os
import runpy
import sys
from pathlib import Path

BASE = Path(os.environ.get('HEIMDALL_BASE_DIR')
            or Path(os.environ.get('ProgramData', r'C:\ProgramData')) / 'HeimdallNexus')


def load_env(path: Path) -> dict[str, str]:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    import importlib.util
    spec = importlib.util.spec_from_file_location('launcher_windows', Path(__file__).with_name('launcher-windows.py'))
    launcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(launcher)
    sys.path.pop(0)
    try:
        return launcher.parse_env(path.read_text(encoding='utf-8'))
    except FileNotFoundError:
        return {}


def main() -> None:
    env_file = Path(os.environ.get('HEIMDALL_ENV_FILE') or BASE / 'etc' / 'heimdall.env')
    for key, value in load_env(env_file).items():
        os.environ.setdefault(key, value)
    arguments = sys.argv[1:]
    if not arguments:
        raise SystemExit(__doc__)
    if arguments[0] == '-m':
        sys.argv = arguments[1:]
        runpy.run_module(arguments[1], run_name='__main__', alter_sys=True)
        return
    script = Path(arguments[0]).resolve()
    sys.argv = [str(script), *arguments[1:]]
    sys.path.insert(0, str(script.parent))
    runpy.run_path(str(script), run_name='__main__')


if __name__ == '__main__':
    main()
