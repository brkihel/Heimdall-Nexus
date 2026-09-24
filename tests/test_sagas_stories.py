"""Stories use only current consented facts and never need a real API request."""
import json
import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'servicos/painel'))
import sagas  # noqa: E402
import stories  # noqa: E402
import executor  # noqa: E402

WORLD = 'a' * 64
ACTOR = 'b' * 64


def state_ready(state, limit=3):
    (state / 'settings.json').write_text(json.dumps({
        'version': 1, 'enabled': True, 'gear': True, 'events': True,
        'clock': True, 'kill_mode': 'all'}))
    (state / 'story-settings.json').write_text(json.dumps({
        'enabled': True, 'model': 'openrouter/free', 'allow_paid': False,
        'daily_limit': limit}))
    (state / 'openrouter.key').write_text('sk-or-test-key-long-enough\n')
    with sagas.connect(state / 'sagas.sqlite3') as db:
        db.execute('INSERT INTO worlds(id,name) VALUES(?,?)', (WORLD, 'Midgard'))
        db.execute('''INSERT INTO players(world,id,name,online,share_profile,share_map,
                      share_position,share_stories,x,z,seen_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                   (WORLD, ACTOR, 'Astrid', 1, 1, 1, 0, 1, None, None, 100))
        for index in range(2):
            db.execute('''INSERT INTO events(world,actor,id,kind,name,target,stars,
                          quantity,occurred_at,boss,elite) VALUES(?,?,?,?,?,?,?,?,?,?,?)''',
                       (WORLD, ACTOR, f'event{index:011d}', 'kill', 'Astrid',
                        'Greydwarf', 0, 1, 100 + index, 0, 0))


def response():
    return {'title': 'A chama sob as árvores',
            'text': 'A floresta guardava silêncio enquanto Astrid atravessava o caminho. '
                    'O primeiro encontro interrompeu aquela calma, e a coragem encontrou '
                    'uma forma discreta de permanecer.\n\nAo fim, o fogo voltou a iluminar '
                    'as árvores. Nada ali prometia uma vitória maior; restava apenas a '
                    'lembrança dos encontros registrados naquela jornada.',
            'evidence': ['e1', 'e2']}


class StoryTests(unittest.TestCase):
    def test_free_is_default_and_paid_requires_opt_in(self):
        self.assertEqual(stories.DEFAULT['model'], 'openrouter/free')
        with self.assertRaises(stories.StoryError):
            stories.valid_config({'enabled': True, 'model': 'vendor/paid',
                                  'allow_paid': False, 'daily_limit': 3})

    def test_key_is_redacted_from_executor_audit(self):
        key = 'sk-or-this-is-a-private-test-key'
        self.assertEqual(executor.audit_payload('sagas.story.key', {'key': key}),
                         {'acao': 'definir'})
        self.assertNotIn(key, json.dumps(executor.audit_payload(
            'sagas.story.key', {'key': key})))

    def test_openrouter_request_uses_fixed_https_host_and_separate_auth_header(self):
        class Reply:
            status = 200
            def read(self, _maximum):
                return json.dumps({'choices': [{'message': {'content':
                    json.dumps(response())}}]}).encode()
        class Connection:
            def request(self, method, path, body, headers):
                self.call = (method, path, body, headers)
            def getresponse(self):
                return Reply()
            def close(self):
                pass
        connection = Connection()
        with patch.object(stories.http.client, 'HTTPSConnection', return_value=connection) as factory:
            result = stories._request('sk-or-test-private-value', 'openrouter/free',
                                      'viking', [{'ref': 'e1', 'kind': 'death'}])
        factory.assert_called_once_with('openrouter.ai', timeout=30)
        self.assertEqual(connection.call[0:2],
                         ('POST', '/api/v1/chat/completions'))
        self.assertEqual(connection.call[3]['Authorization'],
                         'Bearer sk-or-test-private-value')
        self.assertNotIn(b'sk-or-test-private-value', connection.call[2])
        self.assertEqual(result['title'], response()['title'])

    def test_generates_character_and_server_chapters_with_evidence(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            state_ready(state)
            captured = []

            def fake_request(key, model, scope, facts):
                captured.append((key, model, scope, facts))
                return response()

            with patch.object(stories, '_request', side_effect=fake_request):
                stories.generate(state, WORLD, ACTOR)
                stories.generate(state, WORLD)
            self.assertEqual(len(captured), 2)
            self.assertEqual(captured[0][2], 'viking')
            self.assertEqual(captured[1][2], 'server')
            self.assertNotIn(WORLD, json.dumps(captured[0][3]))
            self.assertNotIn(ACTOR, json.dumps(captured[0][3]))
            self.assertNotIn('sk-or-', json.dumps(captured[0][3]))
            public = stories.public_list(state / 'sagas.sqlite3', WORLD)
            self.assertEqual({story['scope'] for story in public}, {'viking', 'server'})
            self.assertEqual(len(public[0]['evidence']), 2)
            with self.assertRaisesRegex(stories.StoryError, 'já existe'):
                stories.generate(state, WORLD, ACTOR)

    def test_revocation_removes_character_and_server_stories(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            state_ready(state)
            with patch.object(stories, '_request', return_value=response()):
                stories.generate(state, WORLD, ACTOR)
                stories.generate(state, WORLD)
            with sagas.connect(state / 'sagas.sqlite3') as db:
                sagas.ingest(db, sagas.validate({
                    'version': 1, 'type': 'withdraw', 'world': WORLD, 'actor': ACTOR}))
                self.assertEqual(db.execute('SELECT count(*) FROM stories').fetchone()[0], 0)
            self.assertEqual(stories.public_list(state / 'sagas.sqlite3', WORLD), [])

    def test_story_opt_out_erases_chapters_but_keeps_shared_events(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            state_ready(state)
            with patch.object(stories, '_request', return_value=response()):
                stories.generate(state, WORLD, ACTOR)
            with sagas.connect(state / 'sagas.sqlite3') as db:
                sagas.ingest(db, sagas.validate({
                    'version': 1, 'type': 'presence', 'world': WORLD, 'actor': ACTOR,
                    'name': 'Astrid', 'online': True, 'share_profile': True,
                    'share_stories': False, 'share_map': True,
                    'share_position': False, 'gear': []}))
                self.assertEqual(db.execute('SELECT count(*) FROM stories').fetchone()[0], 0)
                self.assertEqual(db.execute('SELECT count(*) FROM events').fetchone()[0], 2)

    def test_failed_attempt_consumes_limit_and_invalid_references_are_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            state_ready(state, limit=1)
            invalid = {**response(), 'evidence': ['e999']}
            with patch.object(stories, '_request', return_value=invalid):
                with self.assertRaises(stories.StoryError):
                    stories.generate(state, WORLD, ACTOR)
            with patch.object(stories, '_request', return_value=response()) as request:
                with self.assertRaisesRegex(stories.StoryError, 'limite diário'):
                    stories.generate(state, WORLD, ACTOR)
                request.assert_not_called()
            with sagas.connect(state / 'sagas.sqlite3') as db:
                self.assertEqual(db.execute('SELECT count(*) FROM stories').fetchone()[0], 0)

    def test_admin_filter_hides_chapter_when_its_evidence_is_hidden(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            state_ready(state)
            with patch.object(stories, '_request', return_value=response()):
                stories.generate(state, WORLD, ACTOR)
            settings = sagas.load_settings(state)
            settings['kill_mode'] = 'bosses'
            (state / 'settings.json').write_text(json.dumps(settings))
            self.assertEqual(stories.public_list(state / 'sagas.sqlite3', WORLD), [])

    def test_worker_processes_durable_request_without_live_provider(self):
        with tempfile.TemporaryDirectory() as temporary:
            state = Path(temporary)
            state_ready(state)
            queue = state / 'story-jobs'
            queue.mkdir()
            (queue / '0001.json').write_text(json.dumps({'world': WORLD, 'actor': ACTOR}))
            spec = importlib.util.spec_from_file_location(
                'sagas_story_worker', ROOT / 'servicos/painel/story-worker.py')
            worker = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(worker)
            with patch.object(stories, '_request', return_value=response()):
                result = worker.main(state)
            self.assertTrue(result['ok'])
            self.assertEqual(list(queue.glob('*.json')), [])
            self.assertEqual(stories.public_list(state / 'sagas.sqlite3', WORLD)[0]['title'],
                             response()['title'])


if __name__ == '__main__':
    unittest.main()
