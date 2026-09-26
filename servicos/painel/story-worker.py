#!/usr/bin/python3
"""Process one durable story request outside the panel and game processes."""
import json
import os
import sqlite3
import time
from pathlib import Path

import hostos
import sagas
import stories


def main(state: Path = sagas.STATE) -> dict | None:
    queue = state / 'story-jobs'
    files = sorted(queue.glob('*.json')) if queue.is_dir() else []
    if not files:
        return automatic(state)
    path = files[0]
    try:
        fd = hostos.open_untrusted(path)
        with os.fdopen(fd, 'rb') as source:
            raw = source.read(1025)
        if len(raw) > 1024:
            raise stories.StoryError('HN-STO-016', 'solicitação de história inválida')
        job = json.loads(raw)
        if not isinstance(job, dict) or set(job) != {'world', 'actor'} or \
                not isinstance(job['world'], str) or not isinstance(job['actor'], str):
            raise stories.StoryError('HN-STO-016', 'solicitação de história inválida')
        result = stories.generate(state, job['world'], job['actor'])
        status = {'ok': True, 'scope': result['scope'], 'title': result['title']}
    except (OSError, ValueError, sqlite3.Error) as error:
        status = failure(error)
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
        status = {'ok': True, 'scope': result['scope'], 'auto': True, 'title': result['title']}
    except (OSError, ValueError, sqlite3.Error) as error:
        status = {**failure(error), 'auto': True}
    record(state, status)
    return status


def failure(error: Exception) -> dict:
    if isinstance(error, stories.StoryError):
        return {'ok': False, 'code': error.code, 'message': str(error),
                'retry': error.transient}
    return {'ok': False, 'code': 'HN-STO-018', 'message': 'HN-STO-018: erro interno ao gerar a história'}


def record(state: Path, status: dict) -> None:
    status['at'] = int(time.time())
    try:
        history = json.loads((state / 'story-history.json').read_text(encoding='utf-8'))
        history = history if isinstance(history, list) else []
    except (OSError, ValueError):
        history = []
    history = (history + [status])[-10:]
    temporary = state / '.story-history.tmp'
    temporary.write_text(json.dumps(history, ensure_ascii=False), encoding='utf-8')
    os.replace(temporary, state / 'story-history.json')
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
