"""Identity, publishing paths and upload checks, without touching the host."""
import json
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "site/web"))
import identidade  # noqa: E402

os.environ.setdefault("HEIMDALL_PANEL_SOCKET", "/nonexistent/heimdall-test.sock")


class IdentityTests(unittest.TestCase):
    def test_apply_rewrites_marked_elements_and_escapes(self):
        ident = identidade.validar({**identidade.PADRAO, "nome": "Nórdicos & <Cia>",
                                    "logo": "/marca/logo-abc.png", "url": "https://exemplo.com"})
        page = (ROOT / "site/web/index.html").read_text()
        out = identidade.aplicar(page, ident)
        self.assertIn('data-identidade="nome">Nórdicos &amp; &lt;Cia&gt;</span>', out)
        self.assertIn('src="/marca/logo-abc.png"', out)
        self.assertIn('href="https://exemplo.com/"', out)
        self.assertNotIn("<Cia>", out)
        self.assertEqual(identidade.aplicar(out, ident), out)

    def test_logo_hidden_when_absent(self):
        ident = identidade.validar(identidade.PADRAO)
        out = identidade.aplicar('<img data-identidade="logo" src="/x.png">', ident)
        self.assertIn("hidden", out)

    def test_validation_rejects_bad_values(self):
        for bad in ({"nome": ""}, {"url": "javascript:alert(1)"}, {"logo": "https://evil/x.png"},
                    {"cores": {"fundo": "red"}}, {"rodape": "x" * 500}):
            with self.subTest(bad=bad), self.assertRaises(identidade.IdentidadeErro):
                identidade.validar({**identidade.PADRAO, **bad})

    def test_theme_css_overrides_every_page_variable(self):
        css = identidade.tema_css(identidade.carregar(ROOT / "site/web"))
        index = (ROOT / "site/web/index.html").read_text()
        for _, var, _, _ in identidade.CORES:
            self.assertIn(var + ":", css)
            self.assertIn(var, index)

    def test_palettes_are_complete(self):
        keys = {k for k, _, _, _ in identidade.CORES}
        for name, palette in identidade.PALETAS.items():
            with self.subTest(palette=name):
                self.assertEqual(set(palette), keys)
                identidade.validar({**identidade.PADRAO, "cores": palette})


class PublishPathTests(unittest.TestCase):
    def test_page_urls_map_to_index_files(self):
        import publicar
        self.assertEqual(publicar.saida_da_url("/"), "index.html")
        self.assertEqual(publicar.saida_da_url("/regras/"), "regras/index.html")
        for bad in ("/../etc/", "/Regras/", "regras", "/a/b/c/d/e/"):
            with self.subTest(url=bad), self.assertRaises(SystemExit):
                publicar.saida_da_url(bad)


class UploadCheckTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        sys.path.insert(0, str(ROOT / "servicos/painel"))
        import executor
        cls.executor = executor

    def test_image_kind_uses_content_not_name(self):
        kind = self.executor._image_kind
        self.assertEqual(kind(b"\x89PNG\r\n\x1a\n...."), "png")
        self.assertEqual(kind(b"\xff\xd8\xff\xe0"), "jpg")
        self.assertEqual(kind(b"RIFF\x00\x00\x00\x00WEBPVP8 "), "webp")
        self.assertEqual(kind(b'<svg xmlns="http://www.w3.org/2000/svg"></svg>'), "svg")
        self.assertIsNone(kind(b"<html><script>"))

    def test_svg_with_script_is_refused(self):
        safe = self.executor._safe_svg
        self.assertTrue(safe((ROOT / "site/web/marca/favicon.svg").read_bytes()))
        for bad in (b"<svg><script>x</script></svg>", b'<svg onload="x()"></svg>',
                    b'<svg><a xlink:href="https://evil"/></svg>', b"<svg><foreignObject/></svg>"):
            with self.subTest(svg=bad):
                self.assertFalse(safe(bad))

    def test_page_slugs(self):
        slug = self.executor.SLUG
        for good in ("regras", "guia-2", "a"):
            self.assertTrue(slug.fullmatch(good))
        for bad in ("-x", "x-", "Regras", "a/b", "a" * 41, ""):
            self.assertFalse(slug.fullmatch(bad))


if __name__ == "__main__":
    unittest.main()
