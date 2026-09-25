"""Birds Eye world map for the public Crônicas page.

The bridge exports cartography layers once per world (4096x4096, 6 m per
pixel). This module draws the Birds Eye style from them (contours, hard and
soft shadows, paper veil) and cuts XYZ WebP tiles that Leaflet shows.
The composition follows NomapPrinter by shudnal (Unlicense), commit
b923b15b9fbc23bcee4a0f8c6b76c438c8d28182; the starfield is our own.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import time
from pathlib import Path

import sagas

SIZE = sagas.CARTOGRAPHY_SIZE
PIXEL = 6
SPAN = SIZE * PIXEL            # 24,576 m, centred on the world origin
MAX_NATIVE_ZOOM = 4            # 256 * 2**4 = 4096 px
URL = '/api/sagas/v1/atlas'
EXTERNAL_STYLES = {'vanilla': 'Vanilla', 'topografico': 'Topográfico',
                   'birds-eye': 'Birds Eye'}


def _atomic_json(path: Path, value: dict) -> None:
    temporary = path.with_name('.' + path.name + '.tmp')
    with temporary.open('w', encoding='utf-8') as output:
        json.dump(value, output)
        output.flush()
        os.fsync(output.fileno())
    os.replace(temporary, path)


def revision(folder: Path) -> str:
    stamp = [(folder / 'meta.json').read_text(encoding='utf-8')]
    stamp += [f'{layer}:{(folder / layer).stat().st_mtime_ns}' for layer in sagas.CARTOGRAPHY_LAYERS]
    return hashlib.sha256('|'.join(stamp).encode()).hexdigest()[:16]


# ---------------------------------------------------------------- rendering
def _contours(np, height, water, graduation, alpha):
    levels = np.where(water > 0, 0, np.minimum(height.astype(np.int16) + graduation, 255)) // graduation
    n = height.shape[0]
    center = levels[1:-1, 1:-1]
    orth = np.zeros(center.shape, bool)
    diag = np.zeros(center.shape, bool)
    for dy, dx in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        orth |= levels[1 + dy:n - 1 + dy, 1 + dx:n - 1 + dx] < center
    for dy, dx in ((-1, -1), (-1, 1), (1, -1), (1, 1)):
        diag |= levels[1 + dy:n - 1 + dy, 1 + dx:n - 1 + dx] < center
    strength = np.where((center % 5) == 1, alpha, alpha // 2)
    result = np.zeros(height.shape, np.uint8)
    result[1:-1, 1:-1] = np.where(orth, strength, np.where(diag, strength // 2, 0))
    return result


def _shadows(np, height):
    # South-to-north rays that lose 2 height bytes per texel.
    h = height.astype(np.int16)
    hard = np.zeros(h.shape, np.uint8)
    horizon = h[0].copy()
    for row in range(1, h.shape[0]):
        horizon -= 2
        hard[row] = np.where(horizon > h[row], 23, 0)
        horizon = np.maximum(horizon, h[row])
    delta = np.zeros(h.shape, np.int16)
    delta[1:] = h[1:] - h[:-1]
    soft = (np.abs(delta) * 8).astype(np.uint8)  # keeps the original byte wraparound
    soft_color = np.where(delta >= 0, 255, 0).astype(np.float32)
    hard_color = np.where(hard > 0, 0, 255).astype(np.float32)
    maximum = np.maximum(soft, hard).astype(np.float32)
    t = np.full(h.shape, .5, np.float32)
    np.divide(hard.astype(np.float32) - soft, maximum * 2, out=t, where=maximum > 0)
    t[maximum > 0] += .5
    color = np.clip(soft_color + (hard_color - soft_color) * t, 0, 255).astype(np.uint8)
    alpha = np.minimum(soft.astype(np.int16) + hard, 255).astype(np.uint8)
    return color, alpha


def _starfield(np, n):
    """Night sky outside the world's edge: dark blue gradient with sparse stars."""
    rng = np.random.default_rng(1597)
    y, x = np.mgrid[0:n, 0:n].astype(np.float32) / n - .5
    glow = np.clip(1 - np.sqrt(x * x + y * y) * 1.2, 0, 1)
    sky = np.stack([8 + glow * 10, 12 + glow * 16, 20 + glow * 26], axis=-1)
    stars = rng.random((n, n)) > .9985
    sky[stars] = rng.integers(120, 230, (int(stars.sum()), 1))
    return sky.astype(np.uint8)


def render_birds_eye(folder: Path):
    """Return the Birds Eye map as an RGB array, north up."""
    import numpy as np
    n = SIZE
    data = np.fromfile(folder / 'base.rgb', np.uint8).reshape(n, n, 3)
    heights = np.fromfile(folder / 'height.rg', np.uint8).reshape(n, n, 2)
    abyss = np.fromfile(folder / 'abyss.r8', np.uint8).reshape(n, n).astype(bool)
    paper = np.fromfile(folder / 'paper.r8', np.uint8).reshape(n, n)
    data[abyss] = _starfield(np, n)[abyss]
    shade, shade_alpha = _shadows(np, heights[:, :, 0])
    lines = _contours(np, heights[:, :, 0], heights[:, :, 1], 128, 64)
    result = np.empty_like(data)
    for y in range(0, n, 256):  # strips keep peak memory low
        part = slice(y, min(y + 256, n))
        rgb = np.rint(data[part].astype(np.float32) * (1 - lines[part, :, None].astype(np.float32) / 255))
        a = shade_alpha[part, :, None].astype(np.float32) / 255
        rgb = np.clip(np.rint(rgb + (shade[part, :, None] - rgb) * a), 0, 255)
        veil = paper[part, :, None].astype(np.float32)
        rgb = np.where(abyss[part, :, None], data[part], rgb + (veil - rgb) * np.float32(51 / 255))
        result[part] = np.clip(np.rint(rgb), 0, 255).astype(np.uint8)
    return result[::-1]  # layers run south to north


def write_tiles(image, target: Path) -> int:
    """XYZ WebP tiles, zoom 0..MAX_NATIVE_ZOOM, written through temporary names."""
    from PIL import Image
    count = 0
    with Image.fromarray(image) as native:
        for zoom in range(MAX_NATIVE_ZOOM + 1):
            size = 256 * 2 ** zoom
            level = native if size == SIZE else native.resize((size, size), Image.Resampling.LANCZOS)
            for x in range(2 ** zoom):
                folder = target / str(zoom) / str(x)
                folder.mkdir(parents=True, exist_ok=True)
                for y in range(2 ** zoom):
                    tile = level.crop((x * 256, y * 256, (x + 1) * 256, (y + 1) * 256))
                    temporary = folder / f'.{y}.tmp'
                    tile.save(temporary, 'WEBP', quality=86, method=4)
                    os.chmod(temporary, 0o644)
                    os.replace(temporary, folder / f'{y}.webp')
                    count += 1
            if level is not native:
                level.close()
    return count


def publish(state: Path = sagas.STATE) -> list[str]:
    """Render into private storage. Never publish unmasked world tiles as files."""
    settings = sagas.load_settings(state)
    root = state / 'cartography'
    done = []
    if settings['map_mode'] == 'off' or not settings['enabled']:
        return done
    if not root.is_dir():
        return done
    for folder in sorted(root.iterdir()):
        if not (folder / 'meta.json').is_file() or not sagas.IDENTIFIER.fullmatch(folder.name):
            continue
        try:
            rev = revision(folder)
        except (OSError, ValueError):
            continue
        published = folder / 'published.json'
        tiles_root = folder / 'tiles'
        try:
            if json.loads(published.read_text())['revision'] == rev and (tiles_root / rev).is_dir():
                continue
        except (OSError, ValueError, KeyError):
            pass
        failure = folder / 'failed.json'
        try:
            last_failure = json.loads(failure.read_text())
            if last_failure['revision'] == rev and time.time() - last_failure['at'] < 600:
                continue
        except (OSError, ValueError, KeyError, TypeError):
            pass
        started = time.time()
        tiles_root.mkdir(mode=0o700, exist_ok=True)
        temporary = tiles_root / f'.{rev}.tmp'
        shutil.rmtree(temporary, ignore_errors=True)
        try:
            tiles = write_tiles(render_birds_eye(folder), temporary)
        except Exception as error:
            shutil.rmtree(temporary, ignore_errors=True)
            _atomic_json(failure, {'revision': rev, 'at': int(time.time()),
                                   'code': 'HN-ATL-001'})
            print(f'Failed to render world {folder.name}: {type(error).__name__}: {error}', flush=True)
            continue
        shutil.rmtree(tiles_root / rev, ignore_errors=True)
        os.replace(temporary, tiles_root / rev)
        info = {'revision': rev, 'tiles': tiles, 'published_at': int(time.time()),
                'seconds': round(time.time() - started, 1)}
        _atomic_json(published, info)
        failure.unlink(missing_ok=True)
        for old in tiles_root.iterdir():
            if old.is_dir() and old.name != rev:
                shutil.rmtree(old, ignore_errors=True)
        done.append(rev)
    return done


# ---------------------------------------------------------------- public API
def _points(db: sqlite3.Connection, world: str) -> list[list[int]]:
    """Shared locations rounded to 100 m cells, for the known-lands fog."""
    cells = db.execute('''SELECT DISTINCT CAST(ROUND(e.x / 100.0) AS INTEGER),
                          CAST(ROUND(e.z / 100.0) AS INTEGER)
                          FROM events e JOIN players p ON p.world=e.world AND p.id=e.actor
                          WHERE e.world=? AND p.share_profile=1 AND p.share_map=1
                            AND e.x IS NOT NULL AND e.z IS NOT NULL LIMIT 5000''', (world,)).fetchall()
    live = db.execute('''SELECT CAST(ROUND(x / 100.0) AS INTEGER),
                              CAST(ROUND(z / 100.0) AS INTEGER)
                       FROM players WHERE world=? AND share_profile=1 AND share_map=1
                         AND share_position=1 AND online=1 AND seen_at>=?
                         AND x IS NOT NULL AND z IS NOT NULL LIMIT 200''',
                      (world, int(time.time()) - 90)).fetchall()
    return [[a * 100, b * 100] for a, b in sorted(set(cells + live))]


def _external(world: str) -> tuple[Path, dict] | None:
    """Find an optional, separately generated atlas for this exact world UID.

    The configured directory is private to the panel. The site must not expose
    its raw tiles, or the known-lands consent mask could be bypassed.
    """
    configured = os.environ.get('HEIMDALL_EXTERNAL_ATLAS_DIR', '')
    if not configured:
        return None
    root = Path(configured)
    metadata = root / 'metadata.json'
    try:
        if root.is_symlink() or metadata.is_symlink() or metadata.stat().st_size > 16384:
            return None
        info = json.loads(metadata.read_text(encoding='utf-8'))
        uid = info['uid']
        revision_id = info['revision']
        styles = info['styles']
        if type(uid) is not int or uid == 0 or \
                hashlib.sha256(str(uid).encode()).hexdigest() != world or \
                not isinstance(revision_id, str) or not re.fullmatch(r'[a-f0-9]{12}', revision_id) or \
                (info['size'], info['tileSize'], info['maxNativeZoom'], info['worldSpan']) != \
                (8192, 256, 5, SPAN) or \
                not isinstance(styles, list) or not styles or len(styles) > 3:
            return None
        names = [item['id'] for item in styles]
        if len(set(names)) != len(names) or any(name not in EXTERNAL_STYLES for name in names):
            return None
        tiles = root / 'tiles' / revision_id
        if tiles.is_symlink() or not tiles.is_dir():
            return None
        return root, {'revision': revision_id, 'styles': names}
    except (OSError, ValueError, KeyError, TypeError):
        return None


def summary(state: Path, world: str) -> dict | None:
    settings = sagas.load_settings(state)
    if not settings['enabled'] or settings['map_mode'] == 'off' or not sagas.IDENTIFIER.fullmatch(world or ''):
        return None
    external = _external(world)
    if external:
        _, info = external
        return {'mode': settings['map_mode'],
                'tiles': f'{URL}/{world}/{info["revision"]}/{{style}}/{{z}}/{{x}}/{{y}}.webp',
                'styles': [{'id': key, 'label': EXTERNAL_STYLES[key]} for key in info['styles']],
                'maxNativeZoom': 5, 'span': SPAN, 'radius': 10500}
    try:
        info = json.loads((state / 'cartography' / world / 'published.json').read_text())
        rev = info['revision']
        if not re.fullmatch(r'[a-f0-9]{16}', rev) or not (state / 'cartography' / world / 'tiles' / rev).is_dir():
            return None
    except (OSError, ValueError, KeyError, TypeError):
        return None
    result = {'mode': settings['map_mode'], 'tiles': f'{URL}/{world}/{rev}/{{z}}/{{x}}/{{y}}.webp',
              'styles': [{'id': 'birds-eye', 'label': 'Birds Eye'}],
              'maxNativeZoom': MAX_NATIVE_ZOOM, 'span': SPAN, 'radius': 10500}
    return result


def tile(state: Path, world: str, revision_id: str, z: int, x: int, y: int,
         style: str = 'birds-eye') -> bytes | None:
    """Read a private tile and apply current consent before returning any bytes."""
    if not sagas.IDENTIFIER.fullmatch(world or '') or \
            not re.fullmatch(r'(?:[a-f0-9]{12}|[a-f0-9]{16})', revision_id):
        return None
    info = summary(state, world)
    if info is None or f'/{revision_id}/' not in info['tiles'] or \
            not (0 <= z <= info['maxNativeZoom'] and 0 <= x < 2 ** z and 0 <= y < 2 ** z):
        return None
    if '{style}' in info['tiles']:
        external = _external(world)
        if external is None or style not in external[1]['styles']:
            return None
        source = external[0] / 'tiles' / revision_id / style / str(z) / str(x) / f'{y}.webp'
    else:
        if style != 'birds-eye':
            return None
        source = state / 'cartography' / world / 'tiles' / revision_id / str(z) / str(x) / f'{y}.webp'
    try:
        if source.is_symlink() or source.stat().st_size > 1024 * 1024 or \
                ('{style}' in info['tiles'] and
                 not source.resolve().is_relative_to(external[0].resolve())):
            return None
        content = source.read_bytes()
    except OSError:
        return None
    if info['mode'] == 'full':
        return content
    from PIL import Image, ImageDraw
    with sqlite3.connect(f'file:{state / "sagas.sqlite3"}?mode=ro', uri=True, timeout=3) as db:
        points = _points(db, world)
    size = 256 * 2 ** z
    radius = 700 * size / SPAN
    mask = Image.new('L', (256, 256), 0)
    draw = ImageDraw.Draw(mask)
    for px, pz in points:
        cx = (px + SPAN / 2) * size / SPAN - x * 256
        cy = (SPAN / 2 - pz) * size / SPAN - y * 256
        if -radius <= cx <= 256 + radius and -radius <= cy <= 256 + radius:
            draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=255)
    with Image.open(io.BytesIO(content)) as source_image:
        fog = Image.new('RGB', (256, 256), (11, 17, 23))
        fog.paste(source_image.convert('RGB'), (0, 0), mask)
        output = io.BytesIO()
        fog.save(output, 'WEBP', quality=86, method=3)
        return output.getvalue()
