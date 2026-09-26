"""Periodic jobs on Windows, the counterpart of the systemd timers.

Two services run this file: heimdall-jobs as SYSTEM (public status, saga
feed, Jarl's scheduled tasks) and heimdall-sagas-jobs as its own low-privilege
account (Sagas import, stories, map). Each job keeps the interval of its Linux
timer and runs in its own thread, so a long map render never delays the
five-second import.

A job only runs while it is enabled in HEIMDALL_STATE_DIR/jobs.json, the
equivalent of `systemctl enable --now <job>.timer`.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]

# name: (group, script, first run after start in s, interval in s, timeout in s)
JOBS = {
    'heimdall-status': ('system', 'site/web/heimdall-status.py', 30, 60, 120),
    'heimdall-saga': ('system', 'site/web/heimdall-saga.py', 90, 300, 300),
    'heimdall-schedule': ('system', 'servicos/painel/run-schedules.py', 0, 'minute', None),
    'heimdall-sagas-ingest': ('sagas', 'servicos/painel/ingest-sagas.py', 30, 5, 120),
    'heimdall-sagas-story': ('sagas', 'servicos/painel/story-worker.py', 45, 30, 90),
    'heimdall-sagas-atlas': ('sagas', 'servicos/painel/atlas-worker.py', 120, 60, 900),
}


def state_dir() -> Path:
    base = Path(os.environ.get('HEIMDALL_BASE_DIR')
                or Path(os.environ.get('ProgramData', r'C:\ProgramData')) / 'HeimdallNexus')
    return Path(os.environ.get('HEIMDALL_STATE_DIR') or base / 'state')


def enabled() -> set[str]:
    try:
        data = json.loads((state_dir() / 'jobs.json').read_text(encoding='utf-8'))
        return {name for name, on in data.items() if on is True}
    except (OSError, ValueError, AttributeError):
        return set()


def seconds_to_next_minute() -> float:
    return 60 - time.time() % 60


def run_job(name: str, stop: threading.Event) -> None:
    _, script, first, interval, timeout = JOBS[name]
    if stop.wait(first if interval != 'minute' else seconds_to_next_minute()):
        return
    while not stop.is_set():
        if name in enabled():
            started = time.monotonic()
            try:
                done = subprocess.run([sys.executable, '-X', 'utf8', str(ROOT / script)],
                                      cwd=str((ROOT / script).parent), timeout=timeout,
                                      capture_output=True, text=True, errors='replace')
                if done.returncode:
                    print(f'{name} exited with {done.returncode}: {(done.stderr or done.stdout)[-800:]}',
                          flush=True)
            except subprocess.TimeoutExpired:
                print(f'{name} took longer than {timeout} s and was stopped', flush=True)
            except OSError as error:
                print(f'{name} could not start: {error}', flush=True)
            spent = time.monotonic() - started
        else:
            spent = 0
        wait = seconds_to_next_minute() if interval == 'minute' else max(1.0, interval - spent)
        stop.wait(wait)


def main() -> None:
    group = sys.argv[1] if len(sys.argv) > 1 else ''
    names = [name for name, job in JOBS.items() if job[0] == group]
    if not names:
        raise SystemExit('usage: jobs.py system|sagas')
    stop = threading.Event()
    threads = [threading.Thread(target=run_job, args=(name, stop), name=name, daemon=True) for name in names]
    for thread in threads:
        thread.start()
    print(f'jobs for {group}: {", ".join(names)}', flush=True)
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        stop.set()


if __name__ == '__main__':
    main()
