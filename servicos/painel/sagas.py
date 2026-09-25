"""Optional Heimdall Sagas telemetry store and public, consent-filtered views.

The game bridge writes bounded JSON envelopes to a local directory. This module
never imports a game assembly or accepts telemetry over HTTP.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import sqlite3
import stat
import time
from contextlib import nullcontext
from datetime import datetime, timezone
from pathlib import Path

STATE = Path(os.environ.get('HEIMDALL_SAGAS_DIR', '/var/lib/heimdall-nexus/sagas'))
INBOX = STATE / 'inbox'
REJECTED = STATE / 'rejected'
DATABASE = STATE / 'sagas.sqlite3'
SETTINGS = STATE / 'settings.json'
IDENTIFIER = re.compile(r'^[a-f0-9]{24,64}$')
EVENT_ID = re.compile(r'^[A-Za-z0-9_-]{8,96}$')
BIOME = re.compile(r'^[A-Za-z][A-Za-z0-9_]{0,39}$')
KINDS = {'kill', 'death', 'drop', 'collect', 'pickup', 'boss', 'bounty', 'discover'}
MAX_PACKET = 64 * 1024
MAX_BATCH = 500
MAX_EVENTS_STORED = 100000
MAX_STORIES_STORED = 1000
KILL_MODES = {'all', 'notable', 'bosses'}
MAP_MODES = {'off', 'explored', 'full'}
DEFAULT_SETTINGS = {'version': 1, 'enabled': False, 'gear': True,
                    'events': True, 'clock': True, 'kill_mode': 'all',
                    'map_mode': 'explored'}


class InvalidPacket(ValueError):
    pass


def load_settings(state: Path = STATE) -> dict:
    try:
        saved = json.loads((state / 'settings.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return DEFAULT_SETTINGS.copy()
    required = {'version', 'enabled', 'gear', 'events', 'clock'}
    # Older installs lack the later optional keys; they get the defaults.
    if not isinstance(saved, dict) or not required <= set(saved) or \
            not set(saved) <= set(DEFAULT_SETTINGS) or \
            type(saved.get('version')) is not int or saved['version'] != 1 or any(
                not isinstance(saved[key], bool) for key in ('enabled', 'gear', 'events', 'clock')) or \
            not isinstance(saved.get('kill_mode', 'all'), str) or \
            saved.get('kill_mode', 'all') not in KILL_MODES or \
            not isinstance(saved.get('map_mode', 'explored'), str) or \
            saved.get('map_mode', 'explored') not in MAP_MODES:
        return DEFAULT_SETTINGS.copy()
    return {**DEFAULT_SETTINGS, **saved}


def keep_kill(packet: dict, mode: str) -> bool:
    """Deaths are always kept; only credited creature kills use this filter."""
    if packet['type'] != 'event' or packet['kind'] != 'kill':
        return True
    return mode == 'all' or packet['boss'] or mode == 'notable' and (
        packet['elite'] or packet['stars'] >= 3)


def _label(value: object, maximum: int) -> str:
    if not isinstance(value, str) or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise InvalidPacket('invalid text field')
    return value.strip()


def _identity(value: object) -> str:
    if not isinstance(value, str) or not IDENTIFIER.fullmatch(value):
        raise InvalidPacket('invalid opaque identity')
    return value


def _number(value: object, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise InvalidPacket('invalid number')
    result = float(value)
    if not math.isfinite(result) or not minimum <= result <= maximum:
        raise InvalidPacket('number out of range')
    return result


def validate(raw: object) -> dict:
    """Accept only the first, intentionally small protocol version."""
    if not isinstance(raw, dict) or raw.get('version') != 1:
        raise InvalidPacket('unsupported envelope')
    typ = raw.get('type')
    if typ not in {'presence', 'event', 'clock', 'withdraw'}:
        raise InvalidPacket('unsupported type')
    out = {'version': 1, 'type': typ, 'world': _identity(raw.get('world'))}
    if typ == 'clock':
        out['world_name'] = _label(raw.get('world_name', ''), 64)
        out['day'] = int(_number(raw.get('day'), 0, 10000000))
        out['fraction'] = _number(raw.get('fraction'), 0, 1)
        return out
    out['actor'] = _identity(raw.get('actor'))
    if typ == 'withdraw':
        return out
    if typ == 'presence':
        out['name'] = _label(raw.get('name'), 64)
        for key in ('online', 'share_profile', 'share_map', 'share_position'):
            if not isinstance(raw.get(key), bool):
                raise InvalidPacket('invalid sharing flag')
            out[key] = raw[key]
        if not isinstance(raw.get('share_stories', False), bool):
            raise InvalidPacket('invalid story sharing flag')
        out['share_stories'] = bool(raw.get('share_stories', False) and out['share_profile'])
        if out['share_position'] and out['online']:
            out['x'] = _number(raw.get('x'), -20000, 20000)
            out['z'] = _number(raw.get('z'), -20000, 20000)
        else:
            out['x'] = out['z'] = None
        gear = raw.get('gear') or []
        if not isinstance(gear, list) or len(gear) > 32:
            raise InvalidPacket('invalid equipment list')
        out['gear'] = []
        if out['share_profile']:
            for item in gear:
                if not isinstance(item, dict):
                    raise InvalidPacket('invalid equipment item')
                out['gear'].append({
                    'name': _label(item.get('name'), 120),
                    'slot': _label(item.get('slot'), 40),
                    'quality': int(_number(item.get('quality'), 1, 1000)),
                    'durability': _number(item.get('durability'), 0, 10000),
                })
        return out
    event_id = raw.get('id')
    if not isinstance(event_id, str) or not EVENT_ID.fullmatch(event_id):
        raise InvalidPacket('invalid event id')
    out['id'] = event_id
    kind = raw.get('kind')
    if kind not in KINDS:
        raise InvalidPacket('unsupported event kind')
    out['kind'] = kind
    for flag in ('boss', 'elite'):
        if raw.get(flag, False) is not False and raw.get(flag) is not True:
            raise InvalidPacket('invalid event classification')
        out[flag] = bool(raw.get(flag, False)) if kind == 'kill' or \
            kind == 'discover' and flag == 'boss' else False
    out['name'] = _label(raw.get('name'), 120)
    out['target'] = _label(raw.get('target', ''), 120)
    out['stars'] = int(_number(raw.get('stars', 0), 0, 100))
    out['quantity'] = int(_number(raw.get('quantity', 1), 1, 100000))
    reported = raw.get('utc')
    if reported is not None:
        reported = int(_number(reported, 1577836800, int(time.time()) + 120))
        if reported < int(time.time()) - 7 * 86400:
            raise InvalidPacket('event time too old')
    out['occurred_at'] = reported
    if raw.get('has_location') is True:
        out['x'] = _number(raw.get('x'), -20000, 20000)
        out['z'] = _number(raw.get('z'), -20000, 20000)
        biome = raw.get('biome', '')
        if not isinstance(biome, str) or biome and not BIOME.fullmatch(biome):
            raise InvalidPacket('invalid biome')
        out['biome'] = biome
    else:
        out['x'] = out['z'] = None
        out['biome'] = ''
    return out


SCHEMA = """
PRAGMA foreign_keys=ON;
CREATE TABLE IF NOT EXISTS worlds (
  id TEXT PRIMARY KEY, name TEXT NOT NULL DEFAULT '',
  day INTEGER, fraction REAL, clock_at INTEGER
);
CREATE TABLE IF NOT EXISTS players (
  world TEXT NOT NULL, id TEXT NOT NULL, name TEXT NOT NULL,
  online INTEGER NOT NULL, share_profile INTEGER NOT NULL,
  share_map INTEGER NOT NULL, share_position INTEGER NOT NULL,
  share_stories INTEGER NOT NULL DEFAULT 0,
  x REAL, z REAL, seen_at INTEGER NOT NULL,
  gear_json TEXT NOT NULL DEFAULT '[]',
  PRIMARY KEY(world, id), FOREIGN KEY(world) REFERENCES worlds(id)
);
CREATE TABLE IF NOT EXISTS events (
  world TEXT NOT NULL, actor TEXT NOT NULL, id TEXT NOT NULL,
  kind TEXT NOT NULL, name TEXT NOT NULL, target TEXT NOT NULL,
  stars INTEGER NOT NULL, quantity INTEGER NOT NULL,
  boss INTEGER NOT NULL DEFAULT 0, elite INTEGER NOT NULL DEFAULT 0,
  biome TEXT NOT NULL DEFAULT '', x REAL, z REAL, occurred_at INTEGER NOT NULL,
  PRIMARY KEY(world, actor, id), FOREIGN KEY(world) REFERENCES worlds(id)
);
CREATE INDEX IF NOT EXISTS events_by_time ON events(world, occurred_at DESC);
CREATE INDEX IF NOT EXISTS events_by_actor ON events(world, actor, occurred_at DESC);
CREATE INDEX IF NOT EXISTS events_by_age ON events(occurred_at DESC);
CREATE TABLE IF NOT EXISTS stories (
  id TEXT PRIMARY KEY, world TEXT NOT NULL, scope TEXT NOT NULL,
  actor TEXT NOT NULL, title TEXT NOT NULL, text TEXT NOT NULL,
  model TEXT NOT NULL, fingerprint TEXT NOT NULL, created_at INTEGER NOT NULL,
  auto INTEGER NOT NULL DEFAULT 0,
  UNIQUE(world, scope, actor, fingerprint)
);
CREATE INDEX IF NOT EXISTS stories_by_world ON stories(world, created_at DESC);
CREATE TABLE IF NOT EXISTS story_refs (
  story_id TEXT NOT NULL REFERENCES stories(id) ON DELETE CASCADE,
  world TEXT NOT NULL, actor TEXT NOT NULL, event_id TEXT NOT NULL,
  PRIMARY KEY(story_id, world, actor, event_id)
);
CREATE INDEX IF NOT EXISTS story_refs_by_actor ON story_refs(world, actor);
CREATE TABLE IF NOT EXISTS story_triggers (
  world TEXT NOT NULL, actor TEXT NOT NULL, event_id TEXT NOT NULL,
  created_at INTEGER NOT NULL, PRIMARY KEY(world, actor, event_id)
);
CREATE TABLE IF NOT EXISTS story_trigger_tries (
  world TEXT NOT NULL, actor TEXT NOT NULL, event_id TEXT NOT NULL,
  count INTEGER NOT NULL, next_at INTEGER NOT NULL, PRIMARY KEY(world, actor, event_id)
);
CREATE TABLE IF NOT EXISTS story_attempts (
  day TEXT PRIMARY KEY, count INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS maintenance (key TEXT PRIMARY KEY, value INTEGER NOT NULL);
"""


def connect(path: Path = DATABASE) -> sqlite3.Connection:
    path.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(path, timeout=10)
    db.row_factory = sqlite3.Row
    db.execute('PRAGMA busy_timeout=10000')
    db.executescript(SCHEMA)
    columns = {row[1] for row in db.execute('PRAGMA table_info(players)')}
    if 'gear_json' not in columns:
        db.execute("ALTER TABLE players ADD COLUMN gear_json TEXT NOT NULL DEFAULT '[]'")
    if 'share_stories' not in columns:
        db.execute('ALTER TABLE players ADD COLUMN share_stories INTEGER NOT NULL DEFAULT 0')
    world_columns = {row[1] for row in db.execute('PRAGMA table_info(worlds)')}
    if 'name' not in world_columns:
        db.execute("ALTER TABLE worlds ADD COLUMN name TEXT NOT NULL DEFAULT ''")
    event_columns = {row[1] for row in db.execute('PRAGMA table_info(events)')}
    for flag in ('boss', 'elite'):
        if flag not in event_columns:
            db.execute(f'ALTER TABLE events ADD COLUMN {flag} INTEGER NOT NULL DEFAULT 0')
    if 'biome' not in event_columns:
        db.execute("ALTER TABLE events ADD COLUMN biome TEXT NOT NULL DEFAULT ''")
    if 'auto' not in {row[1] for row in db.execute('PRAGMA table_info(stories)')}:
        db.execute('ALTER TABLE stories ADD COLUMN auto INTEGER NOT NULL DEFAULT 0')
    return db


def ingest(db: sqlite3.Connection, packet: dict, now: int | None = None,
           commit: bool = True) -> None:
    now = now or int(time.time())
    world = packet['world']
    with (db if commit else nullcontext()):
        db.execute('INSERT OR IGNORE INTO worlds(id) VALUES(?)', (world,))
        if packet['type'] == 'withdraw':
            db.execute('''DELETE FROM stories WHERE id IN
                          (SELECT story_id FROM story_refs WHERE world=? AND actor=?)''',
                       (world, packet['actor']))
            db.execute('DELETE FROM events WHERE world=? AND actor=?',
                       (world, packet['actor']))
            db.execute('DELETE FROM players WHERE world=? AND id=?',
                       (world, packet['actor']))
        elif packet['type'] == 'clock':
            db.execute('UPDATE worlds SET name=?, day=?, fraction=?, clock_at=? WHERE id=?',
                       (packet['world_name'], packet['day'], packet['fraction'], now, world))
        elif packet['type'] == 'presence':
            db.execute('''INSERT INTO players(world,id,name,online,share_profile,share_map,
                          share_position,share_stories,x,z,seen_at,gear_json)
                          VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                          ON CONFLICT(world,id) DO UPDATE SET
                          name=excluded.name, online=excluded.online,
                          share_profile=excluded.share_profile, share_map=excluded.share_map,
                          share_position=excluded.share_position,
                          share_stories=excluded.share_stories, x=excluded.x, z=excluded.z,
                          seen_at=excluded.seen_at, gear_json=excluded.gear_json''',
                       (world, packet['actor'], packet['name'], int(packet['online']),
                        int(packet['share_profile']), int(packet['share_map']),
                        int(packet['share_position']), int(packet['share_stories']),
                        packet['x'], packet['z'], now,
                        json.dumps(packet['gear'], ensure_ascii=False, separators=(',', ':'))))
            if not packet['share_stories']:
                db.execute('''DELETE FROM stories WHERE id IN
                              (SELECT story_id FROM story_refs WHERE world=? AND actor=?)''',
                           (world, packet['actor']))
            if not packet['share_profile']:
                db.execute('DELETE FROM events WHERE world=? AND actor=?',
                           (world, packet['actor']))
            elif not packet['share_map']:
                db.execute("UPDATE events SET x=NULL, z=NULL, biome='' WHERE world=? AND actor=?",
                           (world, packet['actor']))
        else:
            consent = db.execute('''SELECT share_profile, share_map FROM players
                                    WHERE world=? AND id=?''',
                                 (world, packet['actor'])).fetchone()
            if consent is None or not consent['share_profile']:
                return
            x, z = (packet['x'], packet['z']) if consent['share_map'] else (None, None)
            biome = packet['biome'] if consent['share_map'] else ''
            db.execute('''INSERT OR IGNORE INTO events
                          (world,actor,id,kind,name,target,stars,quantity,x,z,occurred_at,boss,elite,biome)
                          VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)''',
                       (world, packet['actor'], packet['id'], packet['kind'],
                        packet['name'], packet['target'], packet['stars'],
                        packet['quantity'], x, z,
                        packet['occurred_at'] or now, int(packet['boss']), int(packet['elite']), biome))


def maintain(db: sqlite3.Connection, now: int | None = None) -> None:
    """Keep the event ledger bounded without work on every five-second import."""
    now = int(time.time()) if now is None else now
    last = db.execute("SELECT value FROM maintenance WHERE key='last_prune'").fetchone()
    if last is not None and now - last['value'] < 3600:
        return
    with db:
        db.execute('''DELETE FROM events WHERE rowid IN (
                      SELECT rowid FROM events ORDER BY occurred_at DESC, rowid DESC
                      LIMIT -1 OFFSET ?)''', (MAX_EVENTS_STORED,))
        db.execute('''DELETE FROM stories WHERE EXISTS (
                      SELECT 1 FROM story_refs r LEFT JOIN events e ON
                        e.world=r.world AND e.actor=r.actor AND e.id=r.event_id
                      WHERE r.story_id=stories.id AND e.id IS NULL)''')
        db.execute('''DELETE FROM stories WHERE id IN (
                      SELECT id FROM stories ORDER BY created_at DESC, id DESC
                      LIMIT -1 OFFSET ?)''', (MAX_STORIES_STORED,))
        db.execute('''INSERT INTO maintenance(key,value) VALUES('last_prune',?)
                      ON CONFLICT(key) DO UPDATE SET value=excluded.value''', (now,))


CARTOGRAPHY_META = re.compile(r'^cartography-([a-f0-9]{64})\.meta$')
CARTOGRAPHY_SIZE = 4096
CARTOGRAPHY_LAYERS = {'base.rgb': 3, 'height.rg': 2, 'abyss.r8': 1, 'paper.r8': 1}


def import_cartography(state: Path) -> None:
    """Move complete world-map layers written by the bridge into private storage."""
    inbox = state / 'inbox'
    for legacy in inbox.glob('atlas-*.biomes'):
        legacy.unlink(missing_ok=True)  # replaced by the cartography layers
    for meta_path in inbox.glob('cartography-*.meta'):
        match = CARTOGRAPHY_META.fullmatch(meta_path.name)
        world = match.group(1) if match else ''
        layers = {layer: inbox / f'cartography-{world}.{layer}' for layer in CARTOGRAPHY_LAYERS}
        try:
            if not match:
                raise ValueError('invalid meta')
            descriptor = os.open(meta_path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, 'rb') as source:
                info = os.fstat(source.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > 1024:
                    raise ValueError('invalid meta')
                meta = json.loads(source.read(1025).decode('utf-8'))
            if meta != {'version': 1, 'world': world, 'size': CARTOGRAPHY_SIZE, 'pixelSize': 6}:
                raise ValueError('unexpected meta')
            n = CARTOGRAPHY_SIZE * CARTOGRAPHY_SIZE
            target = state / 'cartography' / world
            target.mkdir(parents=True, mode=0o750, exist_ok=True)
            for layer, path in layers.items():
                expected = n * CARTOGRAPHY_LAYERS[layer]
                descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(descriptor, 'rb') as source:
                    info = os.fstat(source.fileno())
                    if not stat.S_ISREG(info.st_mode) or info.st_size != expected:
                        raise ValueError('invalid layer')
                    temporary = target / ('.' + layer + '.tmp')
                    with temporary.open('wb') as output:
                        shutil.copyfileobj(source, output, length=1024 * 1024)
                        output.flush()
                        os.fsync(output.fileno())
                    if temporary.stat().st_size != expected:
                        raise ValueError('short layer')
            for layer in layers:
                os.replace(target / ('.' + layer + '.tmp'), target / layer)
            with (target / '.meta.tmp').open('w', encoding='utf-8') as output:
                json.dump(meta, output)
                output.flush()
                os.fsync(output.fileno())
            os.replace(target / '.meta.tmp', target / 'meta.json')
        except (OSError, ValueError, UnicodeError):
            if match:
                for layer in layers:
                    (state / 'cartography' / world / ('.' + layer + '.tmp')).unlink(missing_ok=True)
        for path in layers.values():
            path.unlink(missing_ok=True)
        meta_path.unlink(missing_ok=True)


def process_inbox(state: Path = STATE, limit: int = MAX_BATCH) -> dict:
    """Only complete .json files are processed; duplicate delivery is harmless."""
    inbox, rejected = state / 'inbox', state / 'rejected'
    inbox.mkdir(parents=True, exist_ok=True)
    rejected.mkdir(parents=True, exist_ok=True)
    counts = {'accepted': 0, 'rejected': 0, 'dropped': 0}
    settings = load_settings(state)
    rejected_count = sum(1 for _ in rejected.glob('*.json'))
    with connect(state / 'sagas.sqlite3') as db:
        maintain(db)
        import_cartography(state)
        files = sorted(inbox.glob('*.json'))
        accepted_paths = []
        db.execute('BEGIN')
        for index, path in enumerate(files):
            if index >= limit:
                break
            try:
                descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
                with os.fdopen(descriptor, 'rb') as source:
                    if not stat.S_ISREG(os.fstat(source.fileno()).st_mode):
                        raise InvalidPacket('not a regular file')
                    content = source.read(MAX_PACKET + 1)
                if len(content) > MAX_PACKET:
                    raise InvalidPacket('packet too large')
                packet = validate(json.loads(content))
            except (OSError, UnicodeError, ValueError):
                if rejected_count < 1000:
                    path.replace(rejected / path.name)
                    rejected_count += 1
                else:
                    path.unlink()
                counts['rejected'] += 1
                continue
            if packet['type'] != 'withdraw' and (
                    not settings['enabled'] or
                    packet['type'] == 'event' and not settings['events'] or
                    packet['type'] == 'clock' and not settings['clock'] or
                    not keep_kill(packet, settings['kill_mode'])):
                path.unlink()
                counts['dropped'] += 1
                continue
            if packet['type'] == 'presence' and not settings['gear']:
                packet['gear'] = []
            try:
                ingest(db, packet, commit=False)
            except sqlite3.Error:
                break  # Keep valid packets in the inbox until storage recovers.
            accepted_paths.append(path)
        try:
            db.commit()
        except sqlite3.Error:
            db.rollback()
        else:
            for path in accepted_paths:
                path.unlink()
            counts['accepted'] = len(accepted_paths)
    return counts


def public_view(path: Path = DATABASE, world: str = '', limit: int = 50) -> dict:
    """Read-only response; a withdrawn profile is hidden immediately."""
    settings = load_settings(path.parent)
    if not path.is_file() or not settings['enabled']:
        return {'available': False, 'worlds': [], 'players': [], 'events': []}
    limit = max(1, min(100, limit))
    with sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=3) as db:
        db.row_factory = sqlite3.Row
        worlds = [dict(r) for r in db.execute(
            'SELECT id, name, day, fraction, clock_at FROM worlds ORDER BY clock_at DESC, id')]
        if not worlds:
            return {'available': True, 'worlds': [], 'players': [], 'events': []}
        selected = world if any(w['id'] == world for w in worlds) else worlds[0]['id']
        players = []
        for row in db.execute('''SELECT id, name, online, share_position, x, z, seen_at, gear_json
                                 FROM players WHERE world=? AND share_profile=1
                                 ORDER BY online DESC, name COLLATE NOCASE''', (selected,)):
            player = dict(row)
            player['gear'] = json.loads(player.pop('gear_json'))
            if not settings['gear']:
                player['gear'] = []
            player['online'] = bool(player['online'] and int(time.time()) - player['seen_at'] < 90)
            if not player.pop('share_position') or not player['online']:
                player['x'] = player['z'] = None
            players.append(player)
        event_columns = {row[1] for row in db.execute('PRAGMA table_info(events)')}
        boss = 'e.boss' if 'boss' in event_columns else '0'
        elite = 'e.elite' if 'elite' in event_columns else '0'
        biome = 'e.biome' if 'biome' in event_columns else "''"
        events = [dict(row) for row in db.execute(f'''SELECT e.id, e.actor, e.kind, e.name,
                         e.target, e.stars, e.quantity, e.occurred_at,
                         {boss} AS boss, {elite} AS elite,
                         CASE WHEN p.share_map=1 THEN {biome} ELSE '' END AS biome,
                         CASE WHEN p.share_map=1 THEN e.x END AS x,
                         CASE WHEN p.share_map=1 THEN e.z END AS z
                         FROM events e JOIN players p ON p.world=e.world AND p.id=e.actor
                         WHERE e.world=? AND p.share_profile=1 AND
                           (?='all' OR e.kind!='kill' OR
                            (?='bosses' AND {boss}=1) OR
                            (?='notable' AND ({boss}=1 OR {elite}=1 OR e.stars>=3)))
                         ORDER BY e.occurred_at DESC LIMIT ?''',
                         (selected, settings['kill_mode'], settings['kill_mode'],
                          settings['kill_mode'], limit))]
        if not settings['events']:
            events = []
        if not settings['clock']:
            for entry in worlds:
                entry['day'] = entry['fraction'] = entry['clock_at'] = None
        return {'available': True, 'world': selected, 'worlds': worlds,
                'players': players, 'events': events,
                'generated_at': datetime.now(timezone.utc).isoformat()}


def admin_status(state: Path = STATE, game: Path | None = None) -> dict:
    """Operational counts only; never returns private player data."""
    database = state / 'sagas.sqlite3'
    result = {'installed': database.is_file(), 'queued': 0, 'rejected': 0,
              'worlds': 0, 'players': 0, 'events': 0, 'bridge': False,
              'storage_error': False, 'settings': load_settings(state),
              'profiles': 0, 'map_players': 0, 'last_data_at': None,
              'atlas': sum(1 for _ in (state / 'cartography').glob('*/published.json'))
              if (state / 'cartography').is_dir() else 0,
              'atlas_waiting': sum(1 for _ in (state / 'cartography').glob('*/meta.json'))
              if (state / 'cartography').is_dir() else 0,
              'atlas_error': sum(1 for _ in (state / 'cartography').glob('*/failed.json'))
              if (state / 'cartography').is_dir() else 0}
    for key, folder in (('queued', 'inbox'), ('rejected', 'rejected')):
        path = state / folder
        if path.is_dir():
            result[key] = sum(1 for _ in path.glob('*.json'))
    if game is not None:
        result['bridge'] = (game / 'current/BepInEx/plugins/HeimdallSagas/HeimdallSagas.Bridge.dll').is_file()
    if database.is_file():
        try:
            with sqlite3.connect(f'file:{database}?mode=ro', uri=True, timeout=3) as db:
                for name in ('worlds', 'players', 'events'):
                    result[name] = db.execute(f'SELECT count(*) FROM {name}').fetchone()[0]
                result['profiles'] = db.execute(
                    'SELECT count(*) FROM players WHERE share_profile=1').fetchone()[0]
                result['map_players'] = db.execute(
                    'SELECT count(*) FROM players WHERE share_profile=1 AND share_map=1').fetchone()[0]
                result['last_data_at'] = db.execute(
                    '''SELECT max(t) FROM (SELECT max(seen_at) AS t FROM players
                       UNION ALL SELECT max(clock_at) FROM worlds)''').fetchone()[0]
        except sqlite3.Error:
            result.update(storage_error=True, worlds=0, players=0, events=0)
    return result
