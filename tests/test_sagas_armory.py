"""Armory profiles: richer equipment, item icons and portraits stay consent-bound."""
import hashlib
import importlib.util
import json
import os
import struct
import tempfile
import time
import unittest
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('heimdall_sagas_armory', ROOT / 'servicos/painel/sagas.py')
sagas = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sagas)
WORLD = 'a' * 64
ACTOR = 'b' * 64


def chunk(name: bytes, body: bytes) -> bytes:
    return struct.pack('>I', len(body)) + name + body + struct.pack('>I', zlib.crc32(name + body) & 0xffffffff)


def png(width=4, height=4, extra=b'', color=6, rows=None):
    channels = 4 if color == 6 else 3
    raw = rows if rows is not None else b''.join(b'\x00' + b'\x80' * width * channels for _ in range(height))
    header = struct.pack('>IIBBBBB', width, height, 8, color, 0, 0, 0)
    return sagas.PNG_SIGNATURE + chunk(b'IHDR', header) + extra + \
        chunk(b'IDAT', zlib.compress(raw)) + chunk(b'IEND', b'')


def enable(state, gear=True):
    (state / 'settings.json').write_text(json.dumps({
        'version': 1, 'enabled': True, 'gear': gear, 'events': True, 'clock': True}))
    sagas.write_current_world(state, WORLD)


def presence(**changes):
    return {'version': 1, 'type': 'presence', 'world': WORLD, 'actor': ACTOR, 'name': 'Astrid',
            'online': True, 'share_profile': True, 'share_map': True, 'share_position': False,
            'gear': [], **changes}


def drop(state, kind, data):
    media_id = hashlib.sha256(data).hexdigest()
    (state / 'inbox').mkdir(exist_ok=True)
    (state / 'inbox' / f'media-{kind}-{media_id}.png').write_bytes(data)
    return media_id


class ArmoryTests(unittest.TestCase):
    def test_rich_items_are_validated_and_old_clients_still_work(self):
        old = sagas.validate(presence(gear=[{'name': 'Clava', 'slot': 'OneHandedWeapon', 'quality': 1,
                                             'durability': 50}]))
        self.assertEqual(old['gear'][0]['icon'], '')
        self.assertEqual(old['hotbar'], [])
        icon = 'c' * 64
        rich = sagas.validate(presence(
            gear=[{'name': 'Elmo', 'slot': 'Helmet', 'quality': 3, 'durability': 700, 'icon': icon,
                   'stats': [{'name': 'Armor', 'value': 26}], 'effects': ['Frost: Resistant'],
                   'socket_color': '#8A5CC8', 'sockets': [{'name': 'Ametista', 'icon': icon}]}],
            hotbar=[{'name': 'Martelo', 'slot': 'Tool', 'quality': 1, 'durability': 1, 'hotbar': 4}],
            portrait='d' * 64, vitals=[{'name': 'Health', 'value': 125}]))
        self.assertEqual(rich['gear'][0]['socket_color'], '#8a5cc8')
        self.assertEqual(rich['hotbar'][0]['hotbar'], 4)
        self.assertEqual(rich['portrait'], 'd' * 64)
        for bad in (dict(portrait='../x'), dict(gear=[{'name': 'x', 'icon': 'nothex'}]),
                    dict(hotbar=[{'name': 'x'}] * 9), dict(gear=[{'name': 'x', 'active': 'yes'}]),
                    dict(gear=[{'name': 'x', 'socket_color': 'red;'}])):
            with self.subTest(bad=bad), self.assertRaises(sagas.InvalidPacket):
                sagas.validate(presence(**bad))
        private = sagas.validate(presence(share_profile=False, portrait='d' * 64,
                                          hotbar=[{'name': 'x'}], vitals=[{'name': 'Health', 'value': 1}]))
        self.assertEqual((private['portrait'], private['hotbar'], private['vitals']), ('', [], []))

    def test_png_cleaning_keeps_only_the_picture(self):
        clean = sagas.clean_png(png(extra=chunk(b'tEXt', b'comment\x00hello')), 'icon')
        self.assertNotIn(b'tEXt', clean)
        self.assertEqual(sagas.clean_png(clean, 'icon'), clean)
        bomb = png(width=8, height=8, rows=b'\x00' * 100000)
        broken = bytearray(png())
        broken[-20] ^= 1
        for name, data, kind in (('too wide for an icon', png(width=129, height=4), 'icon'),
                                 ('inflates past its size', bomb, 'icon'),
                                 ('bad checksum', bytes(broken), 'icon'),
                                 ('palette chunk', png(extra=chunk(b'PLTE', b'\x00' * 3)), 'icon'),
                                 ('not a png', b'GIF89a' + b'\x00' * 40, 'portrait')):
            with self.subTest(name), self.assertRaises(ValueError):
                sagas.clean_png(data, kind)

    def test_media_is_served_only_while_the_profile_shows_it(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            enable(state)
            icon = drop(state, 'icon', png())
            portrait = drop(state, 'portrait', png(width=16, height=24))
            fake = 'e' * 64
            (state / 'inbox' / f'media-icon-{fake}.png').write_bytes(png())  # name is not its hash
            (state / 'inbox' / 'presence.json').write_text(json.dumps(presence(
                gear=[{'name': 'Elmo', 'slot': 'Helmet', 'quality': 1, 'durability': 1, 'icon': icon}],
                portrait=portrait)))
            sagas.process_inbox(state)
            self.assertFalse((state / 'media' / f'{fake}.png').exists())
            self.assertEqual(list((state / 'inbox').glob('media-*')), [])
            database = state / 'sagas.sqlite3'
            self.assertIsNotNone(sagas.media_file(WORLD, ACTOR, icon, database))
            self.assertIsNotNone(sagas.media_file(WORLD, ACTOR, portrait, database))
            self.assertIsNone(sagas.media_file(WORLD, 'f' * 64, icon, database))
            self.assertIsNone(sagas.media_file(WORLD, ACTOR, '../' + icon, database))
            profile = sagas.viking_view(WORLD, ACTOR, database)
            self.assertEqual(profile['portrait'], portrait)
            self.assertEqual(profile['gear'][0]['icon'], icon)
            # A presence without a portrait keeps the last one; closing the profile removes it.
            (state / 'inbox' / 'later.json').write_text(json.dumps(presence()))
            sagas.process_inbox(state)
            self.assertEqual(sagas.viking_view(WORLD, ACTOR, database)['portrait'], portrait)
            (state / 'inbox' / 'closed.json').write_text(json.dumps(presence(share_profile=False)))
            sagas.process_inbox(state)
            self.assertIsNone(sagas.media_file(WORLD, ACTOR, portrait, database))
            self.assertIsNone(sagas.viking_view(WORLD, ACTOR, database))

    def test_admin_can_hide_equipment_and_pictures(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            enable(state)
            icon = drop(state, 'icon', png())
            (state / 'inbox' / 'presence.json').write_text(json.dumps(presence(
                gear=[{'name': 'Elmo', 'slot': 'Helmet', 'quality': 1, 'durability': 1, 'icon': icon}])))
            sagas.process_inbox(state)
            enable(state, gear=False)
            database = state / 'sagas.sqlite3'
            self.assertIsNone(sagas.media_file(WORLD, ACTOR, icon, database))
            self.assertEqual(sagas.viking_view(WORLD, ACTOR, database)['gear'], [])

    def test_unused_pictures_expire(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            enable(state)
            kept = drop(state, 'icon', png())
            stale = drop(state, 'icon', png(width=2, height=2))
            (state / 'inbox' / 'presence.json').write_text(json.dumps(presence(
                gear=[{'name': 'Elmo', 'slot': 'Helmet', 'quality': 1, 'durability': 1, 'icon': kept}])))
            sagas.process_inbox(state)
            old = time.time() - (sagas.MEDIA_UNUSED_DAYS + 1) * 86400
            for media_id in (kept, stale):
                os.utime(state / 'media' / f'{media_id}.png', (old, old))
            with sagas.connect(state / 'sagas.sqlite3') as db:
                sagas.prune_media(state, db)
            self.assertTrue((state / 'media' / f'{kept}.png').exists())
            self.assertFalse((state / 'media' / f'{stale}.png').exists())


if __name__ == '__main__':
    unittest.main()
