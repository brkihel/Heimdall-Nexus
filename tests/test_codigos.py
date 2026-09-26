"""Error codes: one catalog, documented, and used consistently."""
import importlib.util
import re
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'servicos/painel'))
import atualizacao  # noqa: E402
import codigos  # noqa: E402


class CodeTests(unittest.TestCase):
    def test_codes_are_well_formed_and_explained(self):
        for code, info in codigos.CATALOGO.items():
            with self.subTest(code=code):
                self.assertRegex(code, codigos.CODE)
                self.assertTrue(info['titulo'] and info['solucao'])

    def test_documentation_matches_catalog(self):
        spec = importlib.util.spec_from_file_location('gerar', ROOT / 'ferramentas/gerar-codigos.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        self.assertEqual((ROOT / 'docs/CODIGOS-DE-ERRO.md').read_text(encoding='utf-8'), module.render(),
                         'run: python3 ferramentas/gerar-codigos.py')

    def test_every_code_used_in_code_exists(self):
        used = set()
        for path in [ROOT / 'deploy/update.sh', *(ROOT / 'servicos/painel').glob('*.py')]:
            used |= set(re.findall(r'HN-[A-Z]{3,5}-\d{3}', path.read_text()))
        self.assertTrue(used)
        self.assertEqual(used - set(codigos.CATALOGO), set())
        self.assertEqual(set(atualizacao.STEPS) - set(codigos.CATALOGO), set())

    def test_prefix_round_trip(self):
        text = codigos.com_codigo('HN-UPD-003', 'falha no Git: x')
        self.assertEqual(codigos.separa(text), ('HN-UPD-003', 'falha no Git: x'))
        self.assertEqual(codigos.separa('sem código'), ('', 'sem código'))

    def test_update_errors_carry_codes(self):
        with self.assertRaises(atualizacao.UpdateError) as caught:
            atualizacao.set_channel('bad channel')
        self.assertEqual(caught.exception.code, 'HN-UPD-007')
        self.assertTrue(str(caught.exception).startswith('HN-UPD-007: '))

    def test_progress_reports_step_failure_and_interruption(self):
        header = '2026-09-24 10:00:00 Updating to abc1234 (dev/sagas)'
        running = atualizacao.progress([header, '::heimdall step 2/7 HN-UPD-102 x'], True)
        self.assertEqual((running['state'], running['step'], running['code']),
                         ('running', 2, 'HN-UPD-102'))
        failed = atualizacao.progress([header, '::heimdall step 2/7 HN-UPD-102 x',
                                       '::heimdall fail HN-UPD-102 line 9'], False)
        self.assertEqual((failed['state'], failed['code']), ('failed', 'HN-UPD-102'))
        cut = atualizacao.progress([header, '::heimdall step 3/7 HN-UPD-103 x'], False)
        self.assertEqual(cut['code'], 'HN-UPD-121')
        done = atualizacao.progress([header, '::heimdall step 7/7 HN-UPD-108 x',
                                     '::heimdall done'], False)
        self.assertEqual((done['state'], done['step']), ('done', 7))


if __name__ == '__main__':
    unittest.main()
