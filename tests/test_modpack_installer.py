"""Modpack planning and ZIP checks without downloads or host writes."""
import io
import json
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'deploy'))
import modpack


def api(package, version, dependencies=(), categories=()):
    owner, name = package.split('/', 1)
    selected = {'version_number': version, 'dependencies': list(dependencies),
                'download_url': f'https://cdn.hexium.gg/upload/1/{version}.zip'}
    base = f'{owner}/{name}/'
    return {modpack.HEXIUM_API + base: {
        'latest': selected,
        'community_listings': [{'community': 'valheim', 'categories': list(categories)}]},
        modpack.HEXIUM_API + base + version + '/': selected}


class ModpackInstallTests(unittest.TestCase):
    def test_dependency_order_and_client_only_skip(self):
        answers = {}
        answers.update(api('Owner/MyPack', '1.0.0',
                           ['Author-ServerMod-2.0.0', 'Artist-ClientUI-1.1.0'], ['Modpack', 'Client-only']))
        answers.update(api('Author/ServerMod', '2.0.0', ['Library-Shared-3.0.0'], ['Client & Server']))
        answers.update(api('Artist/ClientUI', '1.1.0', [], ['Client-only']))
        answers.update(api('Library/Shared', '3.0.0', [], ['Client (& Server)']))
        installed, skipped = modpack.resolve('Owner/MyPack', fetch=lambda url: answers[url])
        self.assertEqual([p.package_id for p in installed],
                         ['Library-Shared', 'Author-ServerMod', 'Owner-MyPack'])
        self.assertEqual(skipped, ['Artist-ClientUI'])
        self.assertTrue(installed[-1].client_only)  # pack configs can still be installed

    def test_shared_dependency_uses_highest_required_version(self):
        answers = {}
        answers.update(api('Owner/Pack', '1.0.0', ['A-One-1.0.0', 'B-Two-1.0.0']))
        answers.update(api('A/One', '1.0.0', ['Lib-Shared-1.0.0']))
        answers.update(api('B/Two', '1.0.0', ['Lib-Shared-2.0.0']))
        answers.update(api('Lib/Shared', '1.0.0'))
        answers[modpack.HEXIUM_API + 'Lib/Shared/2.0.0/'] = {
            'version_number': '2.0.0', 'dependencies': [],
            'download_url': 'https://cdn.hexium.gg/upload/1/2.0.0.zip'}
        packages, _ = modpack.resolve('Owner/Pack', fetch=lambda url: answers[url])
        self.assertEqual(next(p.version for p in packages if p.package_id == 'Lib-Shared'), '2.0.0')

    def test_package_extracts_plugins_and_config_in_separate_locations(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'package.zip'
            with zipfile.ZipFile(archive, 'w') as bundle:
                bundle.writestr('manifest.json', json.dumps({'version_number': '1.0.0'}))
                bundle.writestr('BepInEx/plugins/MyMod.dll', b'plugin')
                bundle.writestr('BepInEx/config/MyMod.cfg', b'config')
            stage = Path(directory) / 'stage'
            modpack.extract_package(archive, stage, 'Author-MyMod', is_pack=False, version='1.0.0')
            self.assertEqual((stage / 'plugins/Author-MyMod/MyMod.dll').read_bytes(), b'plugin')
            self.assertEqual((stage / 'config/MyMod.cfg').read_bytes(), b'config')

    def test_rejects_zip_traversal_and_mismatched_version(self):
        with tempfile.TemporaryDirectory() as directory:
            archive = Path(directory) / 'unsafe.zip'
            with zipfile.ZipFile(archive, 'w') as bundle:
                bundle.writestr('manifest.json', json.dumps({'version_number': '1.0.0'}))
                bundle.writestr('../escape.dll', b'bad')
            with self.assertRaises(modpack.ModpackError):
                modpack.extract_package(archive, Path(directory) / 'stage', 'Author-Mod',
                                        is_pack=False, version='1.0.0')
            with self.assertRaises(modpack.ModpackError):
                modpack.extract_package(archive, Path(directory) / 'stage2', 'Author-Mod',
                                        is_pack=False, version='2.0.0')

    def test_batch_install_writes_plugins_config_and_panel_lock(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            game = root / 'game'
            config = root / 'config'
            game.mkdir()
            config.mkdir()
            package = modpack.Package('Owner', 'Pack', '1.0.0', (),
                                      'https://cdn.hexium.gg/upload/1/1.0.0.zip', 'hexium')

            def fake_download(_url, output):
                with zipfile.ZipFile(output, 'w') as bundle:
                    bundle.writestr('manifest.json', json.dumps({'version_number': '1.0.0'}))
                    bundle.writestr('BepInEx/plugins/Plugin.dll', b'plugin')
                    bundle.writestr('BepInEx/config/Plugin.cfg', b'setting=1')
                return 'ab' * 32

            with patch.object(modpack, 'resolve', return_value=([package], [])), \
                 patch.object(modpack, 'download', side_effect=fake_download), \
                 patch.object(modpack.os, 'chown'):
                lock = modpack.install('Owner/Pack', game, config, lambda _line: None, 1000, 1000)
            self.assertEqual((game / 'BepInEx/plugins/Owner-Pack/Plugin.dll').read_bytes(), b'plugin')
            self.assertEqual((config / 'Plugin.cfg').read_bytes(), b'setting=1')
            self.assertEqual(lock['packages']['Owner-Pack']['version'], '1.0.0')
            self.assertEqual(json.loads((game / 'mods.lock.json').read_text())['modpack'], 'Owner/Pack')


if __name__ == '__main__':
    unittest.main()


def local_pack(path, dependencies=(), files=None, manifest=None):
    data = manifest if manifest is not None else {
        'author': 'ExampleTeam', 'name': 'ServerPack', 'version_number': '1.0.0',
        'description': 'Test', 'dependencies': list(dependencies)}
    with zipfile.ZipFile(path, 'w') as bundle:
        bundle.writestr('manifest.json', json.dumps(data))
        for name, content in (files or {}).items():
            bundle.writestr(name, content)
    return path


class LocalModpackTests(unittest.TestCase):
    def test_local_root_resolves_public_dependencies(self):
        answers = {}
        answers.update(api('Author/ServerMod', '2.0.0', ['Library-Shared-3.0.0']))
        answers.update(api('Library/Shared', '3.0.0'))
        with tempfile.TemporaryDirectory() as directory:
            path = local_pack(Path(directory) / 'pack.zip', ['Author-ServerMod-2.0.0'])
            local = modpack.read_local_pack(path)
            packages, _ = modpack.resolve(str(path), fetch=lambda url: answers[url], local=local)
        self.assertEqual([p.package_id for p in packages],
                         ['Library-Shared', 'Author-ServerMod', 'ExampleTeam-ServerPack'])
        self.assertEqual(packages[-1].source, 'bundled')

    def test_local_pack_installs_private_mods_in_own_folders(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            game, config = root / 'game', root / 'config'
            game.mkdir()
            config.mkdir()
            path = local_pack(root / 'pack.zip', files={
                'plugins/TeamSuite/TeamSuite.dll': b'suite',
                'plugins/PlayerBots/PlayerBots.dll': b'bots',
                'patchers/Compat/Compat.dll': b'patch',
                'config/TeamSuite.cfg': b'on=1'})
            self.assertTrue(modpack.is_local_pack(str(path)))
            with patch.object(modpack.os, 'chown'):
                lock = modpack.install(str(path), game, config, lambda _line: None, 1000, 1000)
            plugins = game / 'BepInEx/plugins'
            self.assertEqual((plugins / 'TeamSuite/TeamSuite.dll').read_bytes(), b'suite')
            self.assertEqual((plugins / 'PlayerBots/PlayerBots.dll').read_bytes(), b'bots')
            self.assertEqual((game / 'BepInEx/patchers/Compat/Compat.dll').read_bytes(), b'patch')
            self.assertEqual((config / 'TeamSuite.cfg').read_bytes(), b'on=1')
            entry = lock['packages']['ExampleTeam-ServerPack']
            self.assertEqual(entry['source'], 'bundled')
            self.assertIn('plugins/PlayerBots/PlayerBots.dll', entry['files'])
            self.assertEqual(lock['modpack'], 'ExampleTeam/ServerPack')

    def test_local_pack_rejects_bad_manifest_and_paths(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with self.assertRaises(modpack.ModpackError):
                modpack.read_local_pack(local_pack(root / 'a.zip', manifest={'name': 'x y'}))
            with self.assertRaises(modpack.ModpackError):
                modpack.read_local_pack(local_pack(root / 'b.zip', ['not a dependency']))
            with self.assertRaises(modpack.ModpackError):
                modpack.read_local_pack(Path('relative.zip'))
            bad = local_pack(root / 'c.zip', files={'../evil.dll': b'x'})
            with self.assertRaises(modpack.ModpackError), patch.object(modpack.os, 'chown'):
                modpack.install(str(bad), root, root, lambda _line: None, 0, 0)


class ZipPathTests(unittest.TestCase):
    def test_backslash_paths_are_folders_but_traversal_is_blocked(self):
        self.assertEqual(modpack._safe_zip_path('plugins\\Jotunn.dll'), ('plugins', 'Jotunn.dll'))
        for bad in ('..\\evil.dll', 'plugins\\..\\..\\evil.dll', '/etc/passwd', 'C:\\x.dll'):
            with self.subTest(bad=bad), self.assertRaises(modpack.ModpackError):
                modpack._safe_zip_path(bad)


class PackageNameTests(unittest.TestCase):
    def test_links_and_names_become_author_package(self):
        expected = 'TaegukGaming/Hearthbound_Valheim_Modpack'
        for raw in ('https://thunderstore.io/c/valheim/p/TaegukGaming/Hearthbound_Valheim_Modpack/',
                    'https://thunderstore.io/c/valheim/p/TaegukGaming/Hearthbound_Valheim_Modpack/versions/',
                    'https://thunderstore.io/package/TaegukGaming/Hearthbound_Valheim_Modpack/',
                    'https://valheim.hexium.gg/mods/TaegukGaming/Hearthbound_Valheim_Modpack',
                    'TaegukGaming-Hearthbound_Valheim_Modpack-6.0.0',
                    'TaegukGaming-Hearthbound_Valheim_Modpack',
                    '  TaegukGaming/Hearthbound_Valheim_Modpack  '):
            with self.subTest(raw=raw):
                self.assertEqual(modpack.normalize_package(raw), expected)

    def test_other_sites_are_not_rewritten(self):
        for raw in ('https://evil.example/mods/A/B', 'https://thunderstore.io.evil.test/p/A/B',
                    'https://thunderstore.io/c/valheim/', 'not a pack'):
            with self.subTest(raw=raw):
                self.assertEqual(modpack.normalize_package(raw), raw.strip())
