"""Portable checks for setup choices and archive extraction; no host mutation."""
import io
import json
import sys
import tarfile
import tempfile
import threading
import unittest
from unittest.mock import patch
import urllib.error
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'deploy'))
import installer
import setup_server
import quick_tunnel


def choices(**updates):
    values = dict(domain='play.example.org', server_address='', server_name='Example Server',
                  world='ExampleWorld', port=2456, game_password='', public=True,
                  crossplay=False, bepinex=False, modpack='', features=['servidor'],
                  panel_user='jarl', panel_password='a sufficiently long password',
                  tls=False, email='', start_game=False)
    values.update(updates)
    return installer.Choices.parse(values)


class VisualInstallerTests(unittest.TestCase):
    def test_vanilla_defaults_to_stopped_game(self):
        data = choices()
        self.assertFalse(data.bepinex)
        self.assertFalse(data.start_game)
        self.assertEqual(data.server_address, data.domain)
        self.assertEqual(data.system_user, 'heimdall')
        self.assertNotIn('panel_password', data.public_summary())

    def test_linux_service_account_is_independent_from_panel_login(self):
        data = choices(system_user='nexus_srv', panel_user='my_jarl')
        self.assertEqual(data.system_user, 'nexus_srv')
        self.assertEqual(data.panel_user, 'my_jarl')
        for name in ('root', 'valheim', 'www-data', 'a', 'bad.name'):
            with self.subTest(name=name), self.assertRaises(installer.InstallError):
                choices(system_user=name)

    def test_https_requires_domain_and_email(self):
        for values in ({'domain': '127.0.0.1', 'tls': True, 'email': 'a@example.org'},
                       {'tls': True, 'email': ''}):
            with self.subTest(values=values), self.assertRaises(installer.InstallError):
                choices(**values)

    def test_world_name_matches_panel_rules(self):
        with self.assertRaises(installer.InstallError):
            choices(world='my.world')

    def test_modpack_requires_bepinex(self):
        with self.assertRaises(installer.InstallError):
            choices(modpack='Author/Pack')
        self.assertEqual(choices(modpack='Author/Pack', bepinex=True).modpack, 'Author/Pack')
        with self.assertRaises(installer.InstallError):
            choices(install_modpack=True)
        self.assertTrue(choices(modpack='Author/Pack', bepinex=True,
                                install_modpack=True).install_modpack)

    def test_temporary_url_parser_accepts_only_quick_tunnel_host(self):
        self.assertEqual(quick_tunnel.find_url('Ready: https://bright-saga.trycloudflare.com\n'),
                         'https://bright-saga.trycloudflare.com')
        self.assertIsNone(quick_tunnel.find_url('https://bright-saga.trycloudflare.com.evil.test'))

    def test_temporary_tunnel_process_reports_link(self):
        with tempfile.TemporaryDirectory() as directory:
            fake = Path(directory) / 'cloudflared'
            fake.write_text('#!/bin/sh\necho "Ready: https://bright-saga.trycloudflare.com"\nsleep 5\n')
            fake.chmod(0o755)
            process, url = quick_tunnel.start(18965, binary=str(fake), timeout=3)
            try:
                self.assertEqual(url, 'https://bright-saga.trycloudflare.com')
                self.assertIsNone(process.poll())
            finally:
                process.terminate()
                process.wait(timeout=3)

    def test_steamcmd_archive_rejects_traversal(self):
        memory = io.BytesIO()
        with tarfile.open(fileobj=memory, mode='w:gz') as archive:
            payload = b'bad'
            entry = tarfile.TarInfo('../escape')
            entry.size = len(payload)
            archive.addfile(entry, io.BytesIO(payload))
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(installer.InstallError):
                installer.extract_steamcmd(memory.getvalue(), Path(directory))

    def test_steamcmd_native_binary_keeps_executable_bit(self):
        memory = io.BytesIO()
        with tarfile.open(fileobj=memory, mode='w:gz') as archive:
            payload = b'fake executable'
            entry = tarfile.TarInfo('linux32/steamcmd')
            entry.size = len(payload)
            entry.mode = 0o755
            archive.addfile(entry, io.BytesIO(payload))
        with tempfile.TemporaryDirectory() as directory:
            installer.extract_steamcmd(memory.getvalue(), Path(directory))
            self.assertTrue((Path(directory) / 'linux32/steamcmd').stat().st_mode & 0o111)

    def test_bepinex_archive_rejects_symlink(self):
        memory = io.BytesIO()
        with zipfile.ZipFile(memory, 'w') as archive:
            entry = zipfile.ZipInfo('BepInExPack_Valheim/BepInEx/core/link')
            entry.create_system = 3
            entry.external_attr = 0o120777 << 16
            archive.writestr(entry, 'target')
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaises(installer.InstallError):
                installer.extract_bepinex(memory.getvalue(), Path(directory))

    def test_wizard_requires_one_time_cookie_and_same_origin(self):
        server = setup_server.SetupServer(0)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        base = f'http://127.0.0.1:{server.server_port}'
        try:
            with self.assertRaises(urllib.error.HTTPError) as denied:
                urllib.request.urlopen(base + '/api/state', timeout=2)
            self.assertEqual(denied.exception.code, 401)
            opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor())
            response = opener.open(base + '/claim?token=' + server.token, timeout=2)
            self.assertEqual(response.status, 200)
            self.assertIn('Heimdall Nexus', response.read().decode())
            response = opener.open(base + '/api/state', timeout=2)
            self.assertFalse(json.load(response)['running'])
            request = urllib.request.Request(base + '/api/start', data=b'{}',
                                             headers={'Origin': 'http://other.example'})
            with self.assertRaises(urllib.error.HTTPError) as rejected:
                opener.open(request, timeout=2)
            self.assertEqual(rejected.exception.code, 403)
            server.public_origin = 'https://bright-saga.trycloudflare.com'
            request = urllib.request.Request(base + '/api/start', data=b'{}',
                                             headers={'Origin': server.public_origin})
            with self.assertRaises(urllib.error.HTTPError) as accepted_origin:
                opener.open(request, timeout=2)
            self.assertEqual(accepted_origin.exception.code, 400)  # form rejected after Origin passed
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=2)


if __name__ == '__main__':
    unittest.main()


class SteamCmdRetryTests(unittest.TestCase):
    def test_game_download_retries_missing_configuration(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            state = root / 'attempts'
            steamcmd = root / 'steamcmd' / 'steamcmd.sh'
            steamcmd.parent.mkdir()
            # Fails twice like a freshly bootstrapped SteamCMD, then installs the game.
            steamcmd.write_text(f'''#!/bin/sh
case "$*" in *app_update*) ;; *) exit 0 ;; esac
n=$(cat "{state}" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "{state}"
if [ $n -lt 3 ]; then printf "\\033[0mERROR! Failed to install app '896660' (Missing configuration)\\n\\033[0m\\n"; exit 8; fi
mkdir -p "{root}/current" && touch "{root}/current/valheim_server.x86_64"
''')
            steamcmd.chmod(0o755)
            lines = []
            engine = installer.Installer(choices(), lambda step, line: lines.append(line), game_root=root)
            with patch.object(installer.time, 'sleep'), \
                 patch.object(engine, 'command', wraps=lambda step, argv, timeout=0:
                              installer.Installer.command(engine, step, argv[4:], timeout)):
                engine.game()
            self.assertEqual(state.read_text().strip(), '3')
            retries = [l for l in lines if 'Retrying' in l]
            self.assertEqual(len(retries), 2)
            self.assertIn("ERROR! Failed to install app '896660' (Missing configuration)", retries[0])
            self.assertFalse(any('\x1b' in l for l in lines))
