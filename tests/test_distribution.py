import importlib.util
import json
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SYNC_PATH = ROOT / "site/web/sync_modpack.py"
spec = importlib.util.spec_from_file_location("sync_modpack", SYNC_PATH)
sync_modpack = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync_modpack)


class ModpackSyncTests(unittest.TestCase):
    def test_dependency_parser_keeps_hyphens_in_package_name(self):
        self.assertEqual(
            sync_modpack.parse_dependency("Azumatt-Build_Camera_Custom_Hammers_Edition-1.2.3"),
            ("Azumatt-Build_Camera_Custom_Hammers_Edition", "Azumatt", "1.2.3"),
        )

    def test_rejects_unpinned_dependency(self):
        with self.assertRaises(sync_modpack.SyncError):
            sync_modpack.parse_dependency("owner-package-latest")

    def test_list_uses_manual_description_override(self):
        responses = {
            sync_modpack.API + "Pack/One/": {
                "package_url": "https://valheim.hexium.gg/mods/Pack/One",
                "latest": {"version_number": "2.0.0", "dependencies": ["Owner-ExampleMod-1.2.0"]},
            },
            sync_modpack.API + "Owner/ExampleMod/": {
                "owner": "Owner", "name": "ExampleMod", "package_url": "https://example.invalid/mod",
                "latest": {"version_number": "1.2.1", "description": "Store copy", "icon": "https://example.invalid/icon"},
            },
        }
        result = sync_modpack.build_list("Pack/One", {"Owner-ExampleMod": "Texto revisado"},
                                         fetch=lambda url: responses[url])
        self.assertEqual(result["versao_pack"], "2.0.0")
        self.assertEqual(result["modpack_owner"], "Pack")
        self.assertEqual(result["total"], 1)
        self.assertEqual(result["mods"][0]["descricao"], "Texto revisado")
        self.assertTrue(result["mods"][0]["traduzida"])

    def test_diff_reports_add_remove_and_version_changes(self):
        old = {"mods": [{"pacote": "a", "versao": "1"}, {"pacote": "b", "versao": "1"}]}
        new = {"mods": [{"pacote": "a", "versao": "2"}, {"pacote": "c", "versao": "1"}]}
        self.assertEqual(sync_modpack.changes(old, new), (["c"], ["b"], ["a"]))

    def test_atomic_writer_produces_valid_json(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "nested/mods.json"
            sync_modpack.atomic_json(path, {"mods": [], "total": 0})
            self.assertEqual(json.loads(path.read_text()), {"mods": [], "total": 0})
            self.assertEqual(list(path.parent.iterdir()), [path])


class DistributionConfigTests(unittest.TestCase):
    def test_site_manifest_has_home_wiki_and_page_templates(self):
        manifest = json.loads((ROOT / "site/web/site-pages.json").read_text())
        pages = {page["id"]: page for page in manifest["paginas"]}
        self.assertTrue({"inicio", "wiki", "mapa", "historias", "armaria", "rankings"} <= set(pages))
        for page in pages.values():
            self.assertTrue((ROOT / "site/web" / page["fonte"]).is_file())
            self.assertNotIn("somente_leitura", page)
        for kind in ("wiki", "vazia"):
            template = ROOT / "site/web" / manifest["tipos"][kind]["modelo"]
            self.assertIn("{{TITULO}}", template.read_text())

    def test_visual_installer_includes_game_and_keeps_start_optional(self):
        installer = (ROOT / "deploy/install.sh").read_text()
        engine = (ROOT / "deploy/installer.py").read_text()
        self.assertIn("setup_server.py", installer)
        self.assertIn("+app_update', '896660'", engine)
        self.assertIn("if self.choices.start_game:", engine)
        self.assertIn("'--no-start'", engine)

    def test_homepage_mod_list_is_loaded_from_json(self):
        home = (ROOT / "site/web/index.html").read_text()
        self.assertIn("assets/modpack.js", home)
        self.assertIn("Cards are rendered from /mods.json", home)
        self.assertNotIn('data-mod="Azumatt-AAA_Crafting"', home)

    def test_pages_carry_identity_hooks_and_theme(self):
        for name in ("index.html", "wiki.html", "modelos-pagina/wiki.html", "modelos-pagina/vazia.html"):
            with self.subTest(page=name):
                text = (ROOT / "site/web" / name).read_text()
                self.assertIn('data-identidade="favicon"', text)
                self.assertIn('data-identidade="nome"', text)
                self.assertIn('data-identidade="rodape"', text)
                self.assertIn('href="/assets/tema.css"', text)

    def test_product_has_no_production_identity(self):
        for path in ROOT.rglob("*"):
            if any(part in {".git", "bin", "obj", "artifacts"} for part in path.parts) or not path.is_file() or path.suffix in {".webp", ".png", ".pyc"}:
                continue
            if path.name == "test_distribution.py":
                continue
            text = path.read_text(errors="ignore").lower()
            # Config file names of two public Hexium mods that the status feed can read.
            for mod_file in ("genesisproj.mrdaynight.cfg", "genesis.zzzgenesisitemstacks.cfg"):
                text = text.replace(mod_file, "")
            with self.subTest(path=str(path.relative_to(ROOT))):
                for word in ("genesisheim", "genesisproj", "162.35.119.246"):
                    self.assertFalse(word in text, f"{word} found")

    def test_status_address_is_instance_configured(self):
        status = (ROOT / "site/web/heimdall-status.py").read_text()
        installer = (ROOT / "deploy/install-web.sh").read_text()
        self.assertIn('HEIMDALL_SERVER_ADDRESS', status)
        self.assertIn('HEIMDALL_SERVER_IP', status)
        self.assertIn('HEIMDALL_SERVER_ADDRESS=$SERVER_ADDRESS', installer)

    def test_first_hexium_catalog_download_can_start_from_empty_cache(self):
        import sys
        sys.path.insert(0, str(ROOT / "servicos/painel"))
        import executor

        class Response:
            headers = {}
            def __enter__(self): return self
            def __exit__(self, *_): pass
            def read(self):
                return json.dumps([{"full_name": f"Author-Package{i}", "versions": []}
                                   for i in range(100)]).encode()

        with tempfile.TemporaryDirectory() as temporary:
            catalog = Path(temporary) / "catalogs/hexium.json"
            catalog.parent.mkdir()
            with patch.object(executor, "CATALOGO", catalog), \
                 patch.object(executor.urllib.request, "urlopen", return_value=Response()):
                result = executor._atualiza_hexium()
            self.assertEqual(result["pacotes"], 100)
            self.assertEqual(len(json.loads(catalog.read_text())), 100)


if __name__ == "__main__":
    unittest.main()
