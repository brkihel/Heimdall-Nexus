"""Python blocks embedded in deploy scripts must at least compile.

A bad indent inside a heredoc only fails on the server, mid-update.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BLOCK = re.compile(r"<<'PY'\n(.*?)\nPY\n", re.S)


class EmbeddedPythonTests(unittest.TestCase):
    def test_every_heredoc_compiles(self):
        scripts = sorted((ROOT / 'deploy').glob('*.sh'))
        self.assertTrue(scripts)
        for script in scripts:
            for index, code in enumerate(BLOCK.findall(script.read_text())):
                with self.subTest(script=script.name, block=index):
                    compile(code, f'{script.name}#{index}', 'exec')


if __name__ == '__main__':
    unittest.main()
