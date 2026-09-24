#!/usr/bin/env python3
"""Automatic values the site's pages can carry as @@NAME@@ tags.

One source for every page generator, and for the panel's legend:

    ./values.py --json     # {"NMODS": "81", ...}, what the tags would print now

The names and their descriptions shown to the editor live in site-pages.json;
this file only computes the values.
"""
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

BASE = Path(__file__).parent


def values() -> dict:
    mods = json.loads((BASE / 'mods.json').read_text(encoding='utf-8'))
    owner = mods.get('modpack_owner')
    if not owner:
        owner = urlparse(mods.get('modpack', '')).path.rstrip('/').split('/')[-2:-1]
        owner = owner[0] if owner else ''
    own = sum(1 for m in mods['mods'] if m['autor'] == owner)
    return {
        'NMODS': str(mods['total']),
        'VERSAOPACK': mods['versao_pack'],
        'NPROPRIOS': str(own),
        'MODPACK': mods['modpack'],
    }


def fill(text: str, extra: dict | None = None) -> str:
    """Replaces every known tag; unknown @@...@@ are left for the caller to catch."""
    for name, value in {**values(), **(extra or {})}.items():
        text = text.replace(f'@@{name}@@', value)
    return text


if __name__ == '__main__':
    if '--json' in sys.argv:
        print(json.dumps(values(), ensure_ascii=False))
    else:
        raise SystemExit(__doc__)
