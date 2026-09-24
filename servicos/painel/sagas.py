"""Optional Heimdall Sagas telemetry store and public, consent-filtered views.

The game bridge writes bounded JSON envelopes to a local directory. This module
never imports a game assembly or accepts telemetry over HTTP.
"""
from __future__ import annotations

import json
import math
import os
import re
import sqlite3
import stat
import time
from datetime import datetime, timezone
from pathlib import Path

STATE = Path(os.environ.get('HEIMDALL_SAGAS_DIR', '/var/lib/heimdall-nexus/sagas'))
INBOX = STATE / 'inbox'
REJECTED = STATE / 'rejected'
DATABASE = STATE / 'sagas.sqlite3'
SETTINGS = STATE / 'settings.json'
IDENTIFIER = re.compile(r'^[a-f0-9]{24,64}$')
EVENT_ID = re.compile(r'^[A-Za-z0-9_-]{8,96}$')
KINDS = {'kill', 'death', 'drop', 'collect', 'pickup', 'boss', 'bounty'}
MAX_PACKET = 64 * 1024
MAX_BATCH = 500
MAX_EVENTS_STORED = 100000
DEFAULT_SETTINGS = {'version': 1, 'enabled': False, 'gear': True,
                    'events': True, 'clock': True}


class InvalidPacket(ValueError):
    pass


def load_settings(state: Path = STATE) -> dict:
    try:
        saved = json.loads((state / 'settings.json').read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return DEFAULT_SETTINGS.copy()
    if not isinstance(saved, dict) or set(saved) != set(DEFAULT_SETTINGS) or \
            type(saved.get('version')) is not int or saved['version'] != 1 or any(
                not isinstance(saved[key], bool) for key in DEFAULT_SETTINGS if key != 'version'):
        return DEFAULT_SETTINGS.copy()
    return saved


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
    else:
        out['x'] = out['z'] = None
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
  x REAL, z REAL, seen_at INTEGER NOT NULL,
  gear_json TEXT NOT NULL DEFAULT '[]',
  PRIMARY KEY(world, id), FOREIGN KEY(world) REFERENCES worlds(id)
);
CREATE TABLE IF NOT EXISTS events (
  world TEXT NOT NULL, actor TEXT NOT NULL, id TEXT NOT NULL,
  kind TEXT NOT NULL, name TEXT NOT NULL, target TEXT NOT NULL,
  stars INTEGER NOT NULL, quantity INTEGER NOT NULL,
  x REAL, z REAL, occurred_at INTEGER NOT NULL,
  PRIMARY KEY(world, actor, id), FOREIGN KEY(world) REFERENCES worlds(id)
);
CREATE INDEX IF NOT EXISTS events_by_time ON events(world, occurred_at DESC);
CREATE INDEX IF NOT EXISTS events_by_actor ON events(world, actor, occurred_at DESC);
CREATE INDEX IF NOT EXISTS events_by_age ON events(occurred_at DESC);
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
    world_columns = {row[1] for row in db.execute('PRAGMA table_info(worlds)')}
    if 'name' not in world_columns:
        db.execute("ALTER TABLE worlds ADD COLUMN name TEXT NOT NULL DEFAULT ''")
    return db


def ingest(db: sqlite3.Connection, packet: dict, now: int | None = None) -> None:
    now = now or int(time.time())
    world = packet['world']
    with db:
        db.execute('INSERT OR IGNORE INTO worlds(id) VALUES(?)', (world,))
        if packet['type'] == 'withdraw':
            db.execute('DELETE FROM events WHERE world=? AND actor=?',
                       (world, packet['actor']))
            db.execute('DELETE FROM players WHERE world=? AND id=?',
                       (world, packet['actor']))
        elif packet['type'] == 'clock':
            db.execute('UPDATE worlds SET name=?, day=?, fraction=?, clock_at=? WHERE id=?',
                       (packet['world_name'], packet['day'], packet['fraction'], now, world))
        elif packet['type'] == 'presence':
            db.execute('''INSERT INTO players(world,id,name,online,share_profile,share_map,
                          share_position,x,z,seen_at,gear_json) VALUES(?,?,?,?,?,?,?,?,?,?,?)
                          ON CONFLICT(world,id) DO UPDATE SET
                          name=excluded.name, online=excluded.online,
                          share_profile=excluded.share_profile, share_map=excluded.share_map,
                          share_position=excluded.share_position, x=excluded.x, z=excluded.z,
                          seen_at=excluded.seen_at, gear_json=excluded.gear_json''',
                       (world, packet['actor'], packet['name'], int(packet['online']),
                        int(packet['share_profile']), int(packet['share_map']),
                        int(packet['share_position']), packet['x'], packet['z'], now,
                        json.dumps(packet['gear'], ensure_ascii=False, separators=(',', ':'))))
            if not packet['share_profile']:
                db.execute('DELETE FROM events WHERE world=? AND actor=?',
                           (world, packet['actor']))
            elif not packet['share_map']:
                db.execute('UPDATE events SET x=NULL, z=NULL WHERE world=? AND actor=?',
                           (world, packet['actor']))
        else:
            consent = db.execute('''SELECT share_profile, share_map FROM players
                                    WHERE world=? AND id=?''',
                                 (world, packet['actor'])).fetchone()
            if consent is None or not consent['share_profile']:
                return
            x, z = (packet['x'], packet['z']) if consent['share_map'] else (None, None)
            db.execute('''INSERT OR IGNORE INTO events
                          VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                       (world, packet['actor'], packet['id'], packet['kind'],
                        packet['name'], packet['target'], packet['stars'],
                        packet['quantity'], x, z,
                        packet['occurred_at'] or now))


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
        db.execute('''INSERT INTO maintenance(key,value) VALUES('last_prune',?)
                      ON CONFLICT(key) DO UPDATE SET value=excluded.value''', (now,))


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
        files = sorted(inbox.glob('*.json'))
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
                    packet['type'] == 'clock' and not settings['clock']):
                path.unlink()
                counts['dropped'] += 1
                continue
            if packet['type'] == 'presence' and not settings['gear']:
                packet['gear'] = []
            try:
                ingest(db, packet)
            except sqlite3.Error:
                break  # Keep valid packets in the inbox until storage recovers.
            path.unlink()
            counts['accepted'] += 1
    return counts


def public_view(path: Path = DATABASE, world: str = '', limit: int = 50) -> dict:
    """Read-only response; a withdrawn profile is hidden immediately."""
    settings = load_settings(path.parent)
    if not path.is_file() or not settings['enabled']:
        return {'available': False, 'worlds': [], 'players': [], 'events': []}
    limit = max(1, min(100, limit))
    with sqlite3.connect(f'file:{path}?mode=ro', uri=True, timeout=3) as db:
        db.row_factory = sqlite3.Row
        worlds = [dict(r) for r in db.execute('SELECT id, name, day, fraction, clock_at FROM worlds ORDER BY id')]
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
        events = [dict(row) for row in db.execute('''SELECT e.id, e.actor, e.kind, e.name,
                         e.target, e.stars, e.quantity, e.occurred_at,
                         CASE WHEN p.share_map=1 THEN e.x END AS x,
                         CASE WHEN p.share_map=1 THEN e.z END AS z
                         FROM events e JOIN players p ON p.world=e.world AND p.id=e.actor
                         WHERE e.world=? AND p.share_profile=1
                         ORDER BY e.occurred_at DESC LIMIT ?''', (selected, limit))]
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
              'settings': load_settings(state)}
    for key, folder in (('queued', 'inbox'), ('rejected', 'rejected')):
        path = state / folder
        if path.is_dir():
            result[key] = sum(1 for _ in path.glob('*.json'))
    if game is not None:
        result['bridge'] = (game / 'current/BepInEx/plugins/HeimdallSagas/HeimdallSagas.Bridge.dll').is_file()
    if database.is_file():
        with sqlite3.connect(f'file:{database}?mode=ro', uri=True, timeout=3) as db:
            for name in ('worlds', 'players', 'events'):
                result[name] = db.execute(f'SELECT count(*) FROM {name}').fetchone()[0]
    return result
