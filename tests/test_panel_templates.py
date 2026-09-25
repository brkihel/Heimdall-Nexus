"""Every panel page the app renders has its template, and no link points at a retired page."""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / 'servicos/painel'


class PanelTemplateTests(unittest.TestCase):
    def test_rendered_templates_exist(self):
        source = (PANEL / 'app.py').read_text(encoding='utf-8')
        names = set(re.findall(r"pagina\(pedido, '([\w-]+\.html)'", source))
        self.assertIn('paginas.html', names)
        for name in names:
            with self.subTest(name=name):
                self.assertTrue((PANEL / 'modelos' / name).is_file())

    def test_old_in_frame_editor_is_not_linked(self):
        # /jarl/site only redirects to the Layout Editor now.
        for template in (PANEL / 'modelos').glob('*.html'):
            with self.subTest(template=template.name):
                self.assertNotIn('{{ raiz }}/site"', template.read_text(encoding='utf-8'))


if __name__ == '__main__':
    unittest.main()
