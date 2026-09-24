"""World biome map for the public Crônicas page.

The bridge derives a 512x512 biome grid from the world seed. This module turns
it into a PNG. In the default "explored" mode only land near consented, shared
locations is revealed; the rest stays under fog so the map does not spoil the
world.
"""
from __future__ import annotations

import base64
import hashlib
import sqlite3
import struct
import time
import zlib
from pathlib import Path

import sagas

SIZE = sagas.ATLAS_SIZE
EDGE = 10500.0
REVEAL_METERS = 700.0
PALETTE = bytes.fromhex(
    '05090d'  # 0 outside the world
    '7da04a'  # 1 Meadows
    '3f5b32'  # 2 Black Forest
    '6b5a3a'  # 3 Swamp
    'c9d0d6'  # 4 Mountain
    'c9b458'  # 5 Plains
    '6d6f86'  # 6 Mistlands
    '8a3324'  # 7 Ashlands
    'dfe9f2'  # 8 Deep North
    '1d4a6b'  # 9 Ocean
    '0b1117'  # 10 fog
)
FOG = 10
_cache: dict[str, str] = {}


def _points(db: sqlite3.Connection, world: str) -> list[tuple[int, int]]:
    """Shared locations rounded to 100 m cells; consent is read from players."""
    cells = db.execute('''SELECT DISTINCT CAST(ROUND(e.x / 100.0) AS INTEGER),
                          CAST(ROUND(e.z / 100.0) AS INTEGER)
                          FROM events e JOIN players p ON p.world=e.world AND p.id=e.actor
                          WHERE e.world=? AND p.share_profile=1 AND p.share_map=1
                            AND e.x IS NOT NULL AND e.z IS NOT NULL''', (world,)).fetchall()
    live = db.execute('''SELECT CAST(ROUND(x / 100.0) AS INTEGER), CAST(ROUND(z / 100.0) AS INTEGER)
                         FROM players WHERE world=? AND share_profile=1 AND share_position=1
                           AND online=1 AND seen_at>=? AND x IS NOT NULL AND z IS NOT NULL''',
                      (world, int(time.time()) - 90)).fetchall()
    return sorted({(a, b) for a, b in cells + live})


def _png(pixels: bytearray) -> bytes:
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack('>I', len(data)) + kind + data + \
            struct.pack('>I', zlib.crc32(kind + data) & 0xffffffff)
    raw = bytearray()
    for row in range(SIZE):
        raw.append(0)
        raw += pixels[row * SIZE:(row + 1) * SIZE]
    return b'\x89PNG\r\n\x1a\n' + \
        chunk(b'IHDR', struct.pack('>IIBBBBB', SIZE, SIZE, 8, 3, 0, 0, 0)) + \
        chunk(b'PLTE', PALETTE) + chunk(b'IDAT', zlib.compress(bytes(raw), 9)) + \
        chunk(b'IEND', b'')


def summary(state: Path, world: str) -> dict | None:
    """Cheap description sent with every overview; the image is sent on request."""
    settings = sagas.load_settings(state)
    grid = state / 'atlas' / f'{world}.biomes'
    if settings['map_mode'] == 'off' or not sagas.IDENTIFIER.fullmatch(world or '') or \
            not grid.is_file():
        return None
    points: list[tuple[int, int]] = []
    if settings['map_mode'] == 'explored':
        with sqlite3.connect(f'file:{state / "sagas.sqlite3"}?mode=ro', uri=True, timeout=3) as db:
            points = _points(db, world)
    key = hashlib.sha256(repr((grid.stat().st_mtime_ns, settings['map_mode'], points))
                         .encode()).hexdigest()[:24]
    return {'key': key, 'mode': settings['map_mode'], 'edge': EDGE, 'size': SIZE,
            'points': points}


def image(state: Path, world: str, info: dict) -> str:
    """Return the map as a data URI, cached by content key."""
    if info['key'] in _cache:
        return _cache[info['key']]
    grid = (state / 'atlas' / f'{world}.biomes').read_bytes()
    if len(grid) != SIZE * SIZE:
        raise ValueError('invalid atlas')
    if info['mode'] == 'full':
        pixels = bytearray(grid)
    else:
        pixels = bytearray(b if b == 0 else FOG for b in grid)
        meters = EDGE * 2 / SIZE
        radius = int(REVEAL_METERS / meters) + 1
        for cx, cz in info['points']:
            column = int((cx * 100 + EDGE) / meters)
            row = int((EDGE - cz * 100) / meters)
            for dy in range(-radius, radius + 1):
                y = row + dy
                if not 0 <= y < SIZE:
                    continue
                for dx in range(-radius, radius + 1):
                    x = column + dx
                    if 0 <= x < SIZE and dx * dx + dy * dy <= radius * radius:
                        pixels[y * SIZE + x] = grid[y * SIZE + x]
    uri = 'data:image/png;base64,' + base64.b64encode(_png(pixels)).decode('ascii')
    if len(_cache) > 16:
        _cache.clear()
    _cache[info['key']] = uri
    return uri
