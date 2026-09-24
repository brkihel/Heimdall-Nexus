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
    if not queue.is_dir():
        return None
    files = sorted(queue.glob('*.json'))
    if not files:
        return None
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
    status['at'] = int(time.time())
    temp = state / '.story-last.tmp'
    with temp.open('w', encoding='utf-8') as file:
        json.dump(status, file, ensure_ascii=False)
        file.flush()
        os.fsync(file.fileno())
    os.replace(temp, state / 'story-last.json')
    path.unlink(missing_ok=True)
    return status


if __name__ == '__main__':
    outcome = main()
    if outcome is not None:
        print(json.dumps(outcome, ensure_ascii=False))
