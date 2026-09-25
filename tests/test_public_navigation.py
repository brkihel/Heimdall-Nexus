"""Navigation settings and page migration keep instance customizations intact."""
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / 'site/web'
sys.path.insert(0, str(SITE))
import navegacao  # noqa: E402
import publicar  # noqa: E402

spec = importlib.util.spec_from_file_location('migrate_pages', SITE / 'migrar-paginas.py')
migrate_pages = importlib.util.module_from_spec(spec)
spec.loader.exec_module(migrate_pages)


class NavigationTests(unittest.TestCase):
    def setUp(self):
        self.manifest = json.loads((SITE / 'site-pages.json').read_text(encoding='utf-8'))

    def test_navigation_accepts_only_known_internal_pages(self):
        config = navegacao.defaults(self.manifest)
        self.assertEqual(navegacao.validate(config, self.manifest), config)
        self.assertEqual(navegacao.public(config, self.manifest, 'Meu Mundo')['name'],
                         'Meu Mundo')
        bad = json.loads(json.dumps(config))
        bad['links'][0]['label'] = '<script>alert(1)</script>'
        with self.assertRaises(ValueError):
            navegacao.validate(bad, self.manifest)
        bad = json.loads(json.dumps(config))
        bad['links'][0]['id'] = 'https://elsewhere.test/'
        with self.assertRaises(ValueError):
            navegacao.validate(bad, self.manifest)
        bad = json.loads(json.dumps(config))
        bad['style'] = 'personalizado'
        bad['palette']['background'] = 'red;url(https://elsewhere.test/)'
        with self.assertRaises(ValueError):
            navegacao.validate(bad, self.manifest)

    def test_new_page_gets_menu_entry_without_erasing_saved_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            previous = {'paginas': self.manifest['paginas'][:2]}
            saved = navegacao.defaults(previous)
            saved['links'].reverse()
            (base / navegacao.FILE).write_text(json.dumps(saved))
            loaded = navegacao.load(base, self.manifest)
            self.assertEqual([x['id'] for x in loaded['links'][:2]], ['wiki', 'inicio'])
            self.assertIn('mapa', [x['id'] for x in loaded['links']])

    def test_removed_link_stays_removed_and_can_be_added_again(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            config = navegacao.defaults(self.manifest)
            removed = config['links'].pop(1)
            (base / navegacao.FILE).write_text(json.dumps(config))
            loaded = navegacao.load(base, self.manifest)
            self.assertNotIn(removed['id'], [link['id'] for link in loaded['links']])
            self.assertNotIn(removed['label'],
                             [link['label'] for link in navegacao.public(loaded, self.manifest)['links']])
            loaded['links'].append(removed)
            self.assertEqual(navegacao.validate(loaded, self.manifest), loaded)

    def test_legacy_navigation_is_upgraded_without_losing_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            config = navegacao.defaults(self.manifest)
            config.pop('known')
            config['version'] = 1
            for link in config['links']:
                del link['children']
            config['links'].reverse()
            (base / navegacao.FILE).write_text(json.dumps(config))
            loaded = navegacao.load(base, self.manifest)
            self.assertEqual(loaded['version'], 3)
            self.assertEqual(loaded['links'][0]['id'], config['links'][0]['id'])

    def test_existing_v2_menu_migrates_without_changing_links(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            config = navegacao.defaults(self.manifest)
            config['version'] = 2
            for link in config['links']:
                del link['children']
            (base / navegacao.FILE).write_text(json.dumps(config))
            loaded = navegacao.load(base, self.manifest)
            self.assertEqual(loaded['version'], 3)
            self.assertEqual([link['id'] for link in loaded['links']],
                             [link['id'] for link in config['links']])
            self.assertTrue(all(link['children'] == [] for link in loaded['links']))

    def test_child_links_publish_and_keep_their_place(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            config = navegacao.defaults(self.manifest)
            child = config['links'].pop(1)
            config['links'][0]['children'].append({key: child[key] for key in ('id', 'label', 'visible')})
            clean = navegacao.validate(config, self.manifest)
            public = navegacao.public(clean, self.manifest)
            self.assertEqual(public['links'][0]['children'][0]['url'], '/wiki/')
            self.assertNotIn('/wiki/', [link['url'] for link in public['links']])
            (base / navegacao.FILE).write_text(json.dumps(clean))
            self.assertEqual(navegacao.load(base, self.manifest)['links'][0]['children'],
                             clean['links'][0]['children'])
            clean['links'][0]['visible'] = False
            self.assertNotIn('/wiki/', [child['url'] for link in navegacao.public(clean, self.manifest)['links']
                                            for child in link['children']])

    def test_child_links_reject_duplicates_and_nested_menus(self):
        config = navegacao.defaults(self.manifest)
        config['links'][0]['children'].append({'id': 'wiki', 'label': 'Wiki', 'visible': True})
        with self.assertRaises(ValueError):
            navegacao.validate(config, self.manifest)
        config['links'].pop(1)
        config['links'][0]['children'][0]['children'] = []
        with self.assertRaises(ValueError):
            navegacao.validate(config, self.manifest)
        del config['links'][0]['children'][0]['children']
        config['links'][0]['children'][0]['id'] = 'https://example.test/'
        with self.assertRaises(ValueError):
            navegacao.validate(config, self.manifest)

    def test_removed_parent_promotes_its_children(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            old = navegacao.defaults(self.manifest)
            child = old['links'].pop(1)
            old['links'][0]['children'].append({key: child[key] for key in ('id', 'label', 'visible')})
            (base / navegacao.FILE).write_text(json.dumps(old))
            newer = {'paginas': [page for page in self.manifest['paginas'] if page['id'] != 'inicio']}
            loaded = navegacao.load(base, newer)
            self.assertEqual(loaded['links'][0]['id'], 'wiki')
            self.assertEqual(loaded['links'][0]['children'], [])

    def test_migration_keeps_custom_home_and_wiki(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            manifest = {**self.manifest, 'paginas': self.manifest['paginas'][:2]}
            (base / 'site-pages.json').write_text(json.dumps(manifest))
            (base / 'index.html').write_text('customized home')
            (base / 'wiki.html').write_text('customized wiki')
            self.assertEqual(migrate_pages.migrate(SITE, base),
                             ['mapa', 'historias', 'armaria', 'rankings'])
            self.assertEqual(migrate_pages.migrate(SITE, base), [])
            self.assertEqual((base / 'index.html').read_text(), 'customized home')
            self.assertEqual((base / 'wiki.html').read_text(), 'customized wiki')
            (base / 'historias.html').unlink()
            self.assertEqual(migrate_pages.migrate(SITE, base), ['historias'])
            self.assertEqual((base / 'index.html').read_text(), 'customized home')

    def test_publisher_adds_one_shared_menu_without_touching_source(self):
        source = '<html><head></head><body>customized home</body></html>'
        published = publicar.public_html(source, 'index.html')
        self.assertIn('/assets/navegacao.js?v=', published)
        self.assertIn('/assets/sagas-resumo.js?v=', published)
        self.assertIn('/assets/boss-fights.js?v=', published)
        self.assertEqual(publicar.public_html(published, 'index.html'), published)
        self.assertNotIn('navegacao.js', source)

    def test_publisher_replaces_missing_legacy_favicon(self):
        source = '<html><head><link rel="icon" href="/favicon.ico"></head><body></body></html>'
        identity = {'favicon': '/marca/new.ico'}
        published = publicar.public_html(source, 'index.html', identity)
        self.assertIn('href="/marca/new.ico"', published)
        self.assertNotIn('href="/favicon.ico"', published)
        self.assertIn('/assets/tema.css', published)
        self.assertEqual(publicar.public_html(published, 'index.html', identity), published)

    def test_battle_art_loads_on_story_and_map_pages_only(self):
        source = '<html><head></head><body></body></html>'
        for path in ('historias/index.html', 'mapa/index.html'):
            self.assertIn('/assets/boss-fights.css?v=', publicar.public_html(source, path))
        self.assertNotIn('/assets/boss-fights.js', publicar.public_html(source, 'wiki/index.html'))

    def test_fixed_story_layout_loads_only_on_story_page(self):
        source = '<html><head></head><body></body></html>'
        published = publicar.public_html(source, 'historias/index.html')
        self.assertIn('/assets/historias-layout.css?v=', published)
        self.assertEqual(publicar.public_html(published, 'historias/index.html'), published)
        self.assertNotIn('/assets/historias-layout.css',
                         publicar.public_html(source, 'mapa/index.html'))

    def test_new_page_identity_is_resolved_when_published(self):
        import identidade
        source = (SITE / 'historias.html').read_text(encoding='utf-8')
        identity = identidade.carregar(SITE)
        identity['nome'] = 'Meu Mundo'
        identity['url'] = 'https://example.test'
        published = publicar.public_html(identidade.aplicar(source, identity), 'historias/index.html')
        self.assertIn('content="Meu Mundo"', published)
        self.assertIn('href="https://example.test/historias/"', published)
