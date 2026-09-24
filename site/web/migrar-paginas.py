#!/usr/bin/env python3
"""Install new built-in pages without replacing instance-owned HTML or settings."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

BUILTIN = ('mapa', 'historias', 'armaria', 'rankings')


def migrate(reference: Path, site: Path) -> list[str]:
    expected = json.loads((reference / 'site-pages.json').read_text(encoding='utf-8'))
    path = site / 'site-pages.json'
    current = json.loads(path.read_text(encoding='utf-8'))
    added = []
    for key in BUILTIN:
        page = next(p for p in expected['paginas'] if p['id'] == key)
        registered = next((p for p in current['paginas'] if p['id'] == key), None)
        if registered and registered.get('fonte') != page['fonte']:
            continue
        if not registered and any(p.get('url') == page['url'] for p in current['paginas']):
            continue
        source = site / page['fonte']
        if source.exists() or source.is_symlink():
            if registered:
                continue
            raise ValueError(f'{source} already exists outside the page list')
        data = (reference / page['fonte']).read_bytes()
        temporary = source.with_name('.' + source.name + '.new')
        temporary.write_bytes(data)
        owner = site.stat()
        os.chown(temporary, owner.st_uid, owner.st_gid)
        os.chmod(temporary, 0o640)
        os.replace(temporary, source)
        if not registered:
            current['paginas'].append(page)
        added.append(key)
    if added:
        old = path.stat()
        temporary = path.with_name('.site-pages.json.new')
        temporary.write_text(json.dumps(current, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        os.chown(temporary, old.st_uid, old.st_gid)
        os.chmod(temporary, old.st_mode & 0o777)
        os.replace(temporary, path)
    return added


if __name__ == '__main__':
    print('New site pages:', ', '.join(migrate(Path(sys.argv[1]), Path(sys.argv[2]))) or 'none')
