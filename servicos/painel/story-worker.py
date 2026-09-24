#!/usr/bin/python3
"""Process one durable story request outside the panel and game processes."""
import json
import os
import sqlite3
import time
from pathlib import Path

import sagas
import stories


def main(state: Path = sagas.STATE) -> dict | None:
    queue = state / 'story-jobs'
    files = sorted(queue.glob('*.json')) if queue.is_dir() else []
    if not files:
        return automatic(state)
    path = files[0]
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
        with os.fdopen(fd, 'rb') as source:
            raw = source.read(1025)
        if len(raw) > 1024:
            raise stories.StoryError('solicitação de história inválida')
        job = json.loads(raw)
        if not isinstance(job, dict) or set(job) != {'world', 'actor'} or \
                not isinstance(job['world'], str) or not isinstance(job['actor'], str):
            raise stories.StoryError('solicitação de história inválida')
        result = stories.generate(state, job['world'], job['actor'])
        status = {'ok': True, 'scope': result['scope']}
    except (OSError, ValueError, sqlite3.Error) as error:
        status = {'ok': False, 'message': str(error) if isinstance(error, stories.StoryError)
                  else 'não foi possível gerar a história'}
    record(state, status)
    path.unlink(missing_ok=True)
    return status


def automatic(state: Path) -> dict | None:
    """Admin requests go first; otherwise tell one boss kill or discovery."""
    try:
        trigger = stories.next_trigger(state)
        if trigger is None:
            return None
        result = stories.generate_triggered(state, trigger)
        status = {'ok': True, 'scope': result['scope'], 'auto': True}
    except (OSError, ValueError, sqlite3.Error) as error:
        status = {'ok': False, 'auto': True,
                  'message': str(error) if isinstance(error, stories.StoryError)
                  else 'não foi possível gerar a história'}
    record(state, status)
    return status


def record(state: Path, status: dict) -> None:
    status['at'] = int(time.time())
    temp = state / '.story-last.tmp'
    with temp.open('w', encoding='utf-8') as file:
        json.dump(status, file, ensure_ascii=False)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temp, state / 'story-last.json')


if __name__ == '__main__':
    outcome = main()
    if outcome is not None:
        print(json.dumps(outcome, ensure_ascii=False))
