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

    def test_battle_art_loads_on_story_and_map_pages_only(self):
        source = '<html><head></head><body></body></html>'
        for path in ('historias/index.html', 'mapa/index.html'):
            self.assertIn('/assets/boss-fights.css?v=', publicar.public_html(source, path))
        self.assertNotIn('/assets/boss-fights.js', publicar.public_html(source, 'wiki/index.html'))

    def test_new_page_identity_is_resolved_when_published(self):
        import identidade
        source = (SITE / 'historias.html').read_text(encoding='utf-8')
        identity = identidade.carregar(SITE)
        identity['nome'] = 'Meu Mundo'
        identity['url'] = 'https://example.test'
        published = publicar.public_html(identidade.aplicar(source, identity), 'historias/index.html')
        self.assertIn('content="Meu Mundo"', published)
        self.assertIn('href="https://example.test/historias/"', published)
