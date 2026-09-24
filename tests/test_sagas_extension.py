"""Security and delivery contracts for the optional Sagas extension."""
import importlib.util
import json
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('heimdall_sagas', ROOT / 'servicos/painel/sagas.py')
sagas = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sagas)
WORLD = 'a' * 64
ACTOR = 'b' * 64


def enable(state):
    (state / 'settings.json').write_text(json.dumps({
        'version': 1, 'enabled': True, 'gear': True, 'events': True, 'clock': True}))


def set_mode(state, mode):
    settings = sagas.load_settings(state)
    settings['kill_mode'] = mode
    (state / 'settings.json').write_text(json.dumps(settings))


def presence(**changes):
    return {'version': 1, 'type': 'presence', 'world': WORLD, 'actor': ACTOR,
            'name': 'Astrid', 'online': True, 'share_profile': True,
            'share_map': True, 'share_position': True, 'x': 10, 'z': 20,
            'gear': [{'name': 'Iron Sword', 'slot': 'OneHandedWeapon',
                      'quality': 2, 'durability': 80}], **changes}


def event(**changes):
    return {'version': 1, 'type': 'event', 'world': WORLD, 'actor': ACTOR,
            'id': '1234567890abcdef', 'kind': 'death', 'name': 'Astrid',
            'target': '', 'has_location': True, 'x': 10, 'z': 20, **changes}


class SagasContractTests(unittest.TestCase):
    def test_discovery_keeps_boss_flag_and_ignores_kill_filter(self):
        packet = sagas.validate(event(kind='discover', target='Eikthyrnir', boss=True))
        self.assertTrue(packet['boss'])
        self.assertTrue(sagas.keep_kill(packet, 'bosses'))
        self.assertFalse(sagas.validate(event(kind='death', boss=True))['boss'])

    def test_atlas_import_and_fog(self):
        atlas_spec = importlib.util.spec_from_file_location('heimdall_atlas', ROOT / 'servicos/painel/atlas.py')
        atlas = importlib.util.module_from_spec(atlas_spec)
        with patch.dict(sys.modules, {'sagas': sagas}):
            atlas_spec.loader.exec_module(atlas)
        from PIL import Image
        import io
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            enable(state)
            (state / 'inbox').mkdir()
            world = 'a' * 64
            for layer, channels in sagas.CARTOGRAPHY_LAYERS.items():
                with (state / 'inbox' / f'cartography-{world}.{layer}').open('wb') as output:
                    output.truncate(sagas.CARTOGRAPHY_SIZE ** 2 * channels)
            (state / 'inbox' / f'cartography-{world}.meta').write_text(json.dumps({
                'version': 1, 'world': world, 'size': sagas.CARTOGRAPHY_SIZE, 'pixelSize': 6}))
            (state / 'inbox' / f'cartography-{"b" * 64}.meta').write_text('invalid')
            with sagas.connect(state / 'sagas.sqlite3') as db:
                sagas.ingest(db, sagas.validate(presence()), now=100)
                sagas.ingest(db, sagas.validate(event(x=0, z=0)), now=101)
            sagas.process_inbox(state)
            folder = state / 'cartography' / world
            self.assertTrue((folder / 'base.rgb').is_file())
            self.assertEqual(list((state / 'inbox').glob('cartography-*')), [])
            rev = '1' * 16
            (folder / 'published.json').write_text(json.dumps({'revision': rev}))
            tile_path = folder / 'tiles' / rev / '0' / '0' / '0.webp'
            tile_path.parent.mkdir(parents=True)
            Image.new('RGB', (256, 256), (255, 0, 0)).save(tile_path, 'WEBP')
            info = atlas.summary(state, world)
            self.assertEqual(info['mode'], 'explored')
            self.assertNotIn('points', info)
            shown = Image.open(io.BytesIO(atlas.tile(state, world, rev, 0, 0, 0)))
            self.assertGreater(shown.getpixel((128, 128))[0], 200)
            self.assertLess(shown.getpixel((0, 0))[0], 30)
            with sagas.connect(state / 'sagas.sqlite3') as db:
                sagas.ingest(db, sagas.validate(presence(share_map=False)), now=102)
            hidden = Image.open(io.BytesIO(atlas.tile(state, world, rev, 0, 0, 0)))
            self.assertLess(hidden.getpixel((128, 128))[0], 30)
            self.assertIsNone(atlas.tile(state, world, '2' * 16, 0, 0, 0))
            self.assertIsNone(atlas.tile(state, world, rev, 0, 1, 0))
            settings = sagas.load_settings(state)
            settings['map_mode'] = 'full'
            (state / 'settings.json').write_text(json.dumps(settings))
            revealed = Image.open(io.BytesIO(atlas.tile(state, world, rev, 0, 0, 0)))
            self.assertGreater(revealed.getpixel((0, 0))[0], 200)
            settings['map_mode'] = 'off'
            (state / 'settings.json').write_text(json.dumps(settings))
            self.assertIsNone(atlas.summary(state, world))
            self.assertIsNone(atlas.tile(state, world, rev, 0, 0, 0))

    def test_cartography_import_rejects_symlink_layer(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            enable(state)
            inbox = state / 'inbox'
            inbox.mkdir()
            secret = state / 'secret'
            secret.write_text('private')
            (inbox / f'cartography-{WORLD}.base.rgb').symlink_to(secret)
            (inbox / f'cartography-{WORLD}.meta').write_text(json.dumps({
                'version': 1, 'world': WORLD, 'size': sagas.CARTOGRAPHY_SIZE, 'pixelSize': 6}))
            sagas.process_inbox(state)
            self.assertEqual(secret.read_text(), 'private')
            self.assertFalse((state / 'cartography' / WORLD / 'meta.json').exists())

    def test_birds_eye_rows_put_north_at_top(self):
        import numpy as np
        atlas_spec = importlib.util.spec_from_file_location('heimdall_atlas', ROOT / 'servicos/painel/atlas.py')
        atlas = importlib.util.module_from_spec(atlas_spec)
        with patch.dict(sys.modules, {'sagas': sagas}):
            atlas_spec.loader.exec_module(atlas)
        with tempfile.TemporaryDirectory() as temporary, patch.object(atlas, 'SIZE', 4):
            folder = Path(temporary)
            base = np.zeros((4, 4, 3), np.uint8)
            base[0, :, 0] = 200  # southern row
            base[3, :, 2] = 200  # northern row
            base.tofile(folder / 'base.rgb')
            np.zeros((4, 4, 2), np.uint8).tofile(folder / 'height.rg')
            np.zeros((4, 4), np.uint8).tofile(folder / 'abyss.r8')
            np.zeros((4, 4), np.uint8).tofile(folder / 'paper.r8')
            result = atlas.render_birds_eye(folder)
            self.assertGreater(result[0, 0, 2], result[0, 0, 0])
            self.assertGreater(result[3, 0, 0], result[3, 0, 2])

    def test_legacy_settings_default_to_all_kills(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            enable(state)
            self.assertEqual(sagas.load_settings(state)['kill_mode'], 'all')
            settings = sagas.load_settings(state)
            settings['kill_mode'] = ['bosses']
            (state / 'settings.json').write_text(json.dumps(settings))
            self.assertFalse(sagas.load_settings(state)['enabled'])

    def test_kill_classification_requires_boolean_flags(self):
        for changes in ({'boss': 1}, {'elite': 'true'}):
            with self.subTest(changes=changes), self.assertRaises(sagas.InvalidPacket):
                sagas.validate(event(kind='kill', **changes))

    def test_biome_requires_map_consent_and_is_erased_on_revocation(self):
        with tempfile.TemporaryDirectory() as temporary:
            dbfile = Path(temporary) / 'sagas.sqlite3'
            enable(dbfile.parent)
            with sagas.connect(dbfile) as db:
                sagas.ingest(db, sagas.validate(presence()), now=100)
                sagas.ingest(db, sagas.validate(event(biome='BlackForest')), now=101)
                self.assertEqual(sagas.public_view(dbfile)['events'][0]['biome'],
                                 'BlackForest')
                sagas.ingest(db, sagas.validate(presence(share_map=False)), now=102)
                self.assertEqual(db.execute('SELECT biome FROM events').fetchone()[0], '')
            self.assertEqual(sagas.public_view(dbfile)['events'][0]['biome'], '')
            self.assertEqual(sagas.validate(event(id='fedcba0987654321',
                has_location=False, biome='BlackForest'))['biome'], '')
            with self.assertRaises(sagas.InvalidPacket):
                sagas.validate(event(biome='<script>'))

    def test_kill_mode_filters_history_and_new_packets_without_hiding_deaths(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            enable(state)
            inbox = state / 'inbox'
            inbox.mkdir()
            cases = [
                ('ordinary', {'kind': 'kill', 'target': 'Boar'}),
                ('elite', {'kind': 'kill', 'target': 'Draugr Elite', 'elite': True}),
                ('stars', {'kind': 'kill', 'target': 'Boar', 'stars': 3}),
                ('boss', {'kind': 'kill', 'target': 'Eikthyr', 'boss': True}),
                ('death', {'kind': 'death'}),
            ]
            with sagas.connect(state / 'sagas.sqlite3') as db:
                sagas.ingest(db, sagas.validate(presence()), now=100)
                for index, (_, changes) in enumerate(cases):
                    sagas.ingest(db, sagas.validate(event(id=f'history{index:09d}', **changes)), now=101 + index)
            set_mode(state, 'bosses')
            self.assertEqual({r['kind'] + ':' + r['target'] for r in
                              sagas.public_view(state / 'sagas.sqlite3')['events']},
                             {'kill:Eikthyr', 'death:'})
            set_mode(state, 'notable')
            self.assertEqual(len(sagas.public_view(state / 'sagas.sqlite3')['events']), 4)
            for index, (_, changes) in enumerate(cases):
                (inbox / f'{index:03d}.json').write_text(json.dumps(event(
                    id=f'incoming{index:08d}', **changes)))
            self.assertEqual(sagas.process_inbox(state),
                             {'accepted': 4, 'rejected': 0, 'dropped': 1})
            with sagas.connect(state / 'sagas.sqlite3') as db:
                self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0], 9)

    def test_credited_kill_appears_once_after_profile_consent(self):
        with tempfile.TemporaryDirectory() as temporary:
            dbfile = Path(temporary) / 'sagas.sqlite3'
            enable(dbfile.parent)
            packet = sagas.validate(event(id='c' * 64, kind='kill',
                                          target='Greydwarf', stars=2))
            with sagas.connect(dbfile) as db:
                sagas.ingest(db, sagas.validate(presence()), now=100)
                sagas.ingest(db, packet, now=101)
                sagas.ingest(db, packet, now=102)
            view = sagas.public_view(dbfile)
            self.assertEqual(len(view['events']), 1)
            self.assertEqual(view['events'][0]['target'], 'Greydwarf')
            self.assertEqual(view['events'][0]['stars'], 2)

    def test_admin_status_keeps_saved_options_visible_when_database_is_unreadable(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            enable(state)
            (state / 'sagas.sqlite3').write_text('incomplete database')
            result = sagas.admin_status(state)
            self.assertTrue(result['settings']['enabled'])
            self.assertTrue(result['storage_error'])
            self.assertEqual(result['worlds'], 0)

    def test_validation_rejects_wrong_identity_nonfinite_and_unknown_kind(self):
        for packet in (presence(actor='someone'), presence(x=float('nan')),
                       event(kind='admin'), event(id='../escape')):
            with self.subTest(packet=packet), self.assertRaises(sagas.InvalidPacket):
                sagas.validate(packet)

    def test_retries_are_idempotent_and_revocation_hides_history(self):
        with tempfile.TemporaryDirectory() as temporary:
            dbfile = Path(temporary) / 'sagas.sqlite3'
            enable(dbfile.parent)
            with sagas.connect(dbfile) as db:
                sagas.ingest(db, sagas.validate(presence()), now=100)
                packet = sagas.validate(event())
                sagas.ingest(db, packet, now=101)
                sagas.ingest(db, packet, now=102)
                self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0], 1)
            visible = sagas.public_view(dbfile)
            self.assertEqual(len(visible['events']), 1)
            self.assertEqual((visible['events'][0]['x'], visible['events'][0]['z']), (10, 20))
            with sagas.connect(dbfile) as db:
                sagas.ingest(db, sagas.validate(presence(share_profile=False)), now=103)
                self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0], 0)
            hidden = sagas.public_view(dbfile)
            self.assertEqual(hidden['players'], [])
            self.assertEqual(hidden['events'], [])

    def test_withdrawn_map_consent_erases_stored_event_coordinates(self):
        with tempfile.TemporaryDirectory() as temporary:
            dbfile = Path(temporary) / 'sagas.sqlite3'
            enable(dbfile.parent)
            with sagas.connect(dbfile) as db:
                sagas.ingest(db, sagas.validate(presence()), now=100)
                sagas.ingest(db, sagas.validate(event()), now=101)
                sagas.ingest(db, sagas.validate(presence(share_map=False)), now=102)
                self.assertEqual(tuple(db.execute('SELECT x,z FROM events').fetchone()), (None, None))
                sagas.ingest(db, sagas.validate(event(id='fedcba0987654321')), now=103)
                self.assertTrue(all(tuple(row) == (None, None)
                                    for row in db.execute('SELECT x,z FROM events')))

    def test_event_requires_current_profile_consent(self):
        with tempfile.TemporaryDirectory() as temporary:
            dbfile = Path(temporary) / 'sagas.sqlite3'
            enable(dbfile.parent)
            with sagas.connect(dbfile) as db:
                sagas.ingest(db, sagas.validate(event()), now=100)
                sagas.ingest(db, sagas.validate(presence(share_profile=False)), now=101)
                sagas.ingest(db, sagas.validate(event(id='fedcba0987654321')), now=102)
                self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0], 0)

    def test_map_and_position_consent_are_independent(self):
        with tempfile.TemporaryDirectory() as temporary:
            dbfile = Path(temporary) / 'sagas.sqlite3'
            enable(dbfile.parent)
            with sagas.connect(dbfile) as db:
                sagas.ingest(db, sagas.validate(presence(share_map=False,
                                share_position=False)), now=int(sagas.time.time()))
                sagas.ingest(db, sagas.validate(event()), now=101)
            result = sagas.public_view(dbfile)
            self.assertIsNone(result['players'][0]['x'])
            self.assertIsNone(result['events'][0]['x'])
            self.assertEqual(result['players'][0]['gear'][0]['name'], 'Iron Sword')

    def test_private_profile_drops_equipment_and_rejects_oversized_snapshot(self):
        hidden = sagas.validate(presence(share_profile=False))
        self.assertEqual(hidden['gear'], [])
        self.assertFalse(sagas.validate(presence())['share_stories'])
        self.assertFalse(sagas.validate(presence(share_profile=False,
            share_stories=True))['share_stories'])
        with self.assertRaises(sagas.InvalidPacket):
            sagas.validate(presence(share_stories='yes'))
        with self.assertRaises(sagas.InvalidPacket):
            sagas.validate(presence(gear=[{'name': 'x'}] * 33))

    def test_inbox_accepts_complete_files_and_quarantines_bad_packets(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            enable(state)
            inbox = state / 'inbox'
            inbox.mkdir()
            (inbox / 'good.json').write_text(json.dumps(presence()))
            (inbox / 'bad.json').write_text('{')
            (inbox / '.incomplete.tmp').write_text(json.dumps(event()))
            self.assertEqual(sagas.process_inbox(state), {'accepted': 1, 'rejected': 1, 'dropped': 0})
            self.assertTrue((state / 'rejected/bad.json').exists())
            self.assertTrue((inbox / '.incomplete.tmp').exists())
            self.assertEqual(len(sagas.public_view(state / 'sagas.sqlite3')['players']), 1)

    def test_inbox_does_not_follow_symlinks(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            enable(state)
            inbox = state / 'inbox'
            inbox.mkdir()
            private = state / 'private.json'
            private.write_text(json.dumps(presence()))
            (inbox / 'redirect.json').symlink_to(private)
            self.assertEqual(sagas.process_inbox(state)['rejected'], 1)
            self.assertTrue(private.exists())
            self.assertFalse((inbox / 'redirect.json').exists())
            with sagas.connect(state / 'sagas.sqlite3') as db:
                self.assertEqual(db.execute('SELECT count(*) FROM players').fetchone()[0], 0)

    def test_inbox_imports_revocation_after_events_in_filename_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            enable(state)
            inbox = state / 'inbox'
            inbox.mkdir()
            packets = [presence(), event(), presence(share_profile=False)]
            for index, packet in enumerate(packets):
                (inbox / f'{index:019d}-packet.json').write_text(json.dumps(packet))
            self.assertEqual(sagas.process_inbox(state)['accepted'], 3)
            with sagas.connect(state / 'sagas.sqlite3') as db:
                self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0], 0)
            self.assertEqual(sagas.public_view(state / 'sagas.sqlite3')['players'], [])

    def test_existing_preview_database_gains_new_columns(self):
        with tempfile.TemporaryDirectory() as temporary:
            dbfile = Path(temporary) / 'sagas.sqlite3'
            with sqlite3.connect(dbfile) as db:
                db.execute('CREATE TABLE worlds(id TEXT PRIMARY KEY, day INTEGER, fraction REAL, clock_at INTEGER)')
                db.execute('''CREATE TABLE players(world TEXT, id TEXT, name TEXT, online INTEGER,
                           share_profile INTEGER, share_map INTEGER, share_position INTEGER,
                           x REAL, z REAL, seen_at INTEGER, PRIMARY KEY(world,id))''')
                db.execute('''CREATE TABLE events(world TEXT, actor TEXT, id TEXT, kind TEXT,
                           name TEXT, target TEXT, stars INTEGER, quantity INTEGER,
                           x REAL, z REAL, occurred_at INTEGER, PRIMARY KEY(world,actor,id))''')
            with sagas.connect(dbfile) as db:
                self.assertIn('gear_json', {r[1] for r in db.execute('PRAGMA table_info(players)')})
                self.assertIn('share_stories', {r[1] for r in db.execute('PRAGMA table_info(players)')})
                self.assertIn('name', {r[1] for r in db.execute('PRAGMA table_info(worlds)')})
                self.assertTrue({'boss', 'elite', 'biome'}.issubset(
                    {r[1] for r in db.execute('PRAGMA table_info(events)')}))

    def test_storage_failure_keeps_valid_packet_for_retry(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            enable(state)
            inbox = state / 'inbox'
            inbox.mkdir()
            path = inbox / 'event.json'
            path.write_text(json.dumps(event()))
            with patch.object(sagas, 'ingest', side_effect=sqlite3.OperationalError('disk full')):
                self.assertEqual(sagas.process_inbox(state)['accepted'], 0)
            self.assertTrue(path.exists())

    def test_disabled_modules_drop_new_data_and_hide_retained_data(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            with sagas.connect(state / 'sagas.sqlite3') as db:
                sagas.ingest(db, sagas.validate(presence()), now=int(sagas.time.time()))
                sagas.ingest(db, sagas.validate(event()), now=101)
            (state / 'settings.json').write_text(json.dumps({
                'version': 1, 'enabled': True, 'gear': False, 'events': False, 'clock': False}))
            public = sagas.public_view(state / 'sagas.sqlite3')
            self.assertEqual(public['events'], [])
            self.assertEqual(public['players'][0]['gear'], [])
            inbox = state / 'inbox'
            inbox.mkdir()
            (inbox / 'event.json').write_text(json.dumps(event(id='abcdef1234567890')))
            self.assertEqual(sagas.process_inbox(state)['dropped'], 1)

    def test_full_opt_out_purges_data_even_while_extension_is_disabled(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            enable(state)
            dbfile = state / 'sagas.sqlite3'
            with sagas.connect(dbfile) as db:
                sagas.ingest(db, sagas.validate(presence()), now=100)
                sagas.ingest(db, sagas.validate(event()), now=101)
            (state / 'settings.json').write_text(json.dumps({
                'version': 1, 'enabled': False, 'gear': True,
                'events': True, 'clock': True}))
            inbox = state / 'inbox'
            inbox.mkdir()
            (inbox / 'withdraw.json').write_text(json.dumps({
                'version': 1, 'type': 'withdraw', 'world': WORLD, 'actor': ACTOR}))
            self.assertEqual(sagas.process_inbox(state)['accepted'], 1)
            with sagas.connect(dbfile) as db:
                self.assertEqual(db.execute('SELECT count(*) FROM players').fetchone()[0], 0)
                self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0], 0)

    def test_missing_or_invalid_settings_fail_closed(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            with sagas.connect(state / 'sagas.sqlite3') as db:
                sagas.ingest(db, sagas.validate(presence()), now=100)
            self.assertFalse(sagas.public_view(state / 'sagas.sqlite3')['available'])
            (state / 'settings.json').write_text('{broken')
            self.assertFalse(sagas.load_settings(state)['enabled'])
            self.assertFalse(sagas.public_view(state / 'sagas.sqlite3')['available'])

    def test_event_ledger_has_a_storage_cap(self):
        with tempfile.TemporaryDirectory() as temporary, \
                patch.object(sagas, 'MAX_EVENTS_STORED', 2):
            dbfile = Path(temporary) / 'sagas.sqlite3'
            with sagas.connect(dbfile) as db:
                sagas.ingest(db, sagas.validate(presence()), now=100)
                for index in range(3):
                    packet = sagas.validate(event(id=f'event{index:011d}'))
                    sagas.ingest(db, packet, now=100 + index)
                sagas.maintain(db, now=1000)
                self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0], 2)
                sagas.maintain(db, now=1001)
                self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0], 2)


if __name__ == '__main__':
    unittest.main()
