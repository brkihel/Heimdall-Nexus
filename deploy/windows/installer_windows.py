"""Heimdall Nexus installation engine for Windows. Called by the setup wizard.

The same choices as the Linux installer produce the same layout, mapped to
Windows conventions:

- code and its Python in %ProgramFiles%\\HeimdallNexus (only administrators write there);
- data in %ProgramData%\\HeimdallNexus, with inheritance cut at the top so only
  SYSTEM and administrators get in by default;
- each service with the smallest account that works: the executor and the
  SYSTEM jobs as LocalSystem; the panel, the game, the Sagas jobs and the web
  server as their own virtual accounts, each granted only its folders;
- Caddy serves the site and proxies the panel, with automatic HTTPS.

Every step can run again after a failure without undoing the previous ones.
"""
from __future__ import annotations

import ctypes
import datetime as dt
import hashlib
import http.client
import io
import json
import os
import secrets
import shutil
import subprocess
import sys
import time
import zipfile
from pathlib import Path
from typing import Callable

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
import installer as common  # noqa: E402  (Choices, downloads, BepInEx extraction)
import modpack as server_modpack  # noqa: E402
import services  # noqa: E402

InstallError = common.InstallError
Choices = common.Choices

PROGRAM_DATA = Path(os.environ.get('ProgramData', r'C:\ProgramData'))
PROGRAM_FILES = Path(os.environ.get('ProgramFiles', r'C:\Program Files'))
BASE = Path(os.environ.get('HEIMDALL_BASE_DIR') or PROGRAM_DATA / 'HeimdallNexus')
APP_BASE = Path(os.environ.get('HEIMDALL_APP_BASE') or PROGRAM_FILES / 'HeimdallNexus')

STEAMCMD_URL = 'https://steamcdn-a.akamaihd.net/client/installer/steamcmd.zip'
CADDY_URL = 'https://github.com/caddyserver/caddy/releases/download/v2.11.4/caddy_2.11.4_windows_amd64.zip'
CADDY_SHA256 = '1708333f79e274c7697285afe6d592ab39314e0b131e9ec6bea08ad27df62ebf'
SYSTEM_SID = '*S-1-5-18'
ADMINS_SID = '*S-1-5-32-544'
PANEL = 'NT SERVICE\\heimdall-panel'
GAME = 'NT SERVICE\\heimdall-valheim'
SAGAS = 'NT SERVICE\\heimdall-sagas-jobs'
WEB = 'NT SERVICE\\heimdall-web'
FIREWALL_GROUP = 'Heimdall Nexus'


def is_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except (AttributeError, OSError):
        return False


class Layout:
    """Every path of a Windows installation, in one place."""

    def __init__(self, base: Path = BASE, app_base: Path = APP_BASE):
        self.base, self.app_base = base, app_base
        self.app = app_base / 'app'
        self.venv = app_base / 'venv'
        self.python = self.venv / 'Scripts' / 'python.exe'
        self.tools = app_base / 'tools'
        self.etc = base / 'etc'
        self.panel_etc = self.etc / 'panel'
        self.env_file = self.etc / 'heimdall.env'
        self.executor_key = self.etc / 'executor.key'
        self.panel_config = self.panel_etc / 'config.json'
        self.valheim = base / 'valheim'
        self.game_files = self.valheim / 'current'
        self.steamcmd = self.valheim / 'steamcmd'
        self.state = base / 'state'
        self.site = self.state / 'site'
        self.data = self.state / 'dados'
        self.sagas = self.state / 'sagas'
        self.panel_state = base / 'panel'
        self.swap = self.panel_state / 'troca'
        self.web = base / 'web'
        self.logs = base / 'logs'
        self.run = base / 'run'
        self.backups = base / 'backups'
        self.caddy = base / 'caddy'
        self.service_files = base / 'services'
        self.cache = base / 'cache'
        self.installed = self.state / 'installed.json'


def env_value(value: str) -> str:
    return common._env_value(value)


class WindowsInstaller:
    def __init__(self, choices: Choices, report: Callable[[str, str], None], *,
                 root: Path | None = None, layout: Layout | None = None):
        self.choices, self.report = choices, report
        self.root = root or HERE.parents[1]
        self.paths = layout or Layout()

    # ------------------------------------------------------------ helpers
    def command(self, step: str, argv: list[str], timeout: int = 2400, ok_codes=(0,), cwd=None) -> str:
        self.report(step, 'Running ' + Path(argv[0]).name + '…')
        try:
            done = subprocess.run(argv, capture_output=True, text=True, errors='replace',
                                  timeout=timeout, cwd=cwd)
        except subprocess.TimeoutExpired as error:
            raise InstallError(f'{step} timed out.') from error
        output = (done.stdout or '') + (done.stderr or '')
        for line in output.splitlines()[-12:]:
            if line.strip():
                self.report(step, common.ANSI.sub('', line).strip()[:400])
        if done.returncode not in ok_codes:
            last = next((line for line in reversed(output.splitlines()) if line.strip()), 'no output')
            raise InstallError(f'{step} failed ({done.returncode}): {last[:300]}')
        return output

    def icacls(self, path: Path, *arguments: str) -> None:
        self.command('permissions', ['icacls', str(path), *arguments, '/Q'], timeout=600)

    def grant(self, path: Path, account: str, rights: str, *, tree: bool = True) -> None:
        inherit = '(OI)(CI)' if tree and path.is_dir() else ''
        self.icacls(path, '/grant', f'{account}:{inherit}{rights}')

    # ------------------------------------------------------------ steps
    def check(self) -> None:
        if not is_admin():
            raise InstallError('Run the Windows installer as administrator.')
        import platform
        if sys.maxsize <= 2 ** 32 or platform.machine().upper() not in ('AMD64', 'X86_64', 'ARM64'):
            raise InstallError('Heimdall Nexus needs 64-bit Windows.')
        if sys.version_info < (3, 10):
            raise InstallError('The installer needs Python 3.10 or newer.')
        existing = subprocess.run(['sc.exe', 'query', 'heimdall-valheim'], capture_output=True, text=True)
        marker = self.paths.installed
        if existing.returncode == 0 and not self.paths.service_files.joinpath('heimdall-valheim.xml').is_file() \
                and not marker.is_file():
            raise InstallError('A heimdall-valheim service exists that this installer did not create.')

    def folders(self) -> None:
        self.report('folders', f'Preparing {self.paths.base}…')
        paths = self.paths
        for folder in (paths.base, paths.etc, paths.panel_etc, paths.valheim, paths.game_files,
                       paths.steamcmd, paths.valheim / 'saves' / 'worlds_local',
                       paths.valheim / 'config' / 'BepInEx', paths.valheim / 'backups',
                       paths.valheim / 'logs', paths.valheim / 'run', paths.state, paths.site, paths.data / 'catalogs',
                       paths.data / 'downloads', paths.sagas / 'inbox', paths.panel_state, paths.swap,
                       paths.web / 'api', paths.web / 'assets', paths.logs, paths.run,
                       paths.backups / 'panel', paths.backups / 'web', paths.caddy,
                       paths.service_files, paths.cache, paths.app_base, paths.tools):
            folder.mkdir(parents=True, exist_ok=True)
        # Only SYSTEM and administrators by default; each service gets its folders later.
        self.icacls(paths.base, '/inheritance:r', '/grant:r', f'{SYSTEM_SID}:(OI)(CI)F',
                    f'{ADMINS_SID}:(OI)(CI)F')

    def runtime_code(self) -> None:
        target = self.paths.app
        self.report('runtime', f'Installing Heimdall code in {target}…')
        if self.root.resolve() == target.resolve():
            return
        marker = target / '.heimdall-nexus-runtime'
        if target.exists() and any(target.iterdir()) and not marker.is_file():
            raise InstallError(f'{target} already contains unrelated files; move them before installing.')
        target.mkdir(parents=True, exist_ok=True)
        marker.write_text('Heimdall Nexus service code\n', encoding='utf-8')
        ignore = shutil.ignore_patterns('.git', '.venv', '__pycache__', '*.pyc', '*.bak*', '.agora-code',
                                        'mapa', 'mods')
        for part in ('deploy', 'servicos/painel', 'ferramentas', 'site/web', 'dist', 'extensoes/sagas/dist'):
            source = self.root / part
            if source.is_dir():
                shutil.copytree(source, target / part, ignore=ignore, dirs_exist_ok=True)
            elif part in ('deploy', 'servicos/painel', 'ferramentas', 'site/web'):
                raise InstallError(f'The checkout is missing {part}.')
        version = self.root / 'deploy' / 'VERSION'
        info = {'version': version.read_text(encoding='ascii').strip() if version.is_file() else ''}
        try:
            info['commit'] = subprocess.run(['git', '-C', str(self.root), 'rev-parse', 'HEAD'],
                                            capture_output=True, text=True, timeout=10).stdout.strip()
            info['branch'] = subprocess.run(['git', '-C', str(self.root), 'rev-parse', '--abbrev-ref', 'HEAD'],
                                            capture_output=True, text=True, timeout=10).stdout.strip()
        except OSError:
            pass
        (target / '.heimdall-version.json').write_text(json.dumps(info) + '\n', encoding='utf-8')

    def python_environment(self) -> None:
        venv = self.paths.venv
        self.report('python', 'Preparing the Python environment of the services…')
        if not self.paths.python.is_file():
            self.command('python', [sys.executable, '-m', 'venv', str(venv)], timeout=600)
        requirements = [self.paths.app / 'deploy' / 'requirements-panel.txt',
                        self.paths.app / 'deploy' / 'windows' / 'requirements-windows.txt']
        argv = [str(self.paths.python), '-m', 'pip', 'install', '--disable-pip-version-check',
                '--no-input', '--quiet']
        for file in requirements:
            argv += ['-r', str(file)]
        self.command('python', argv, timeout=1800)

    def steamcmd(self) -> None:
        executable = self.paths.steamcmd / 'steamcmd.exe'
        if not executable.is_file():
            self.report('steamcmd', 'Downloading SteamCMD from Valve…')
            data = common.fetch_bytes(STEAMCMD_URL, 20_000_000)
            with zipfile.ZipFile(io.BytesIO(data)) as bundle:
                names = bundle.namelist()
                if names != ['steamcmd.exe']:
                    raise InstallError('The SteamCMD archive has unexpected contents.')
                bundle.extract('steamcmd.exe', self.paths.steamcmd)
        signature = subprocess.run(['powershell.exe', '-NoProfile', '-Command',
                                    f"(Get-AuthenticodeSignature -LiteralPath '{executable}').SignerCertificate.Subject"],
                                   capture_output=True, text=True, timeout=60).stdout
        if 'O=Valve' not in signature:
            raise InstallError('SteamCMD is not signed by Valve; refusing to run it.')

    def game(self) -> None:
        steamcmd = str(self.paths.steamcmd / 'steamcmd.exe')
        # SteamCMD updates and restarts itself on the first run (exit code 7).
        self.report('valheim', 'Updating SteamCMD…')
        self.command('valheim', [steamcmd, '+quit'], timeout=900, ok_codes=(0, 7))
        self.report('valheim', 'Downloading Valheim Dedicated Server (Steam App 896660)…')
        for attempt in range(1, 4):
            try:
                self.command('valheim', [steamcmd, '+force_install_dir', str(self.paths.game_files),
                                         '+login', 'anonymous', '+app_update', '896660', 'validate', '+quit'],
                             timeout=3600)
                break
            except InstallError as error:
                if attempt == 3:
                    raise
                self.report('valheim', f'SteamCMD did not finish ({error}). Retrying ({attempt + 1}/3)…')
                time.sleep(10)
        if not (self.paths.game_files / 'valheim_server.exe').is_file():
            raise InstallError('SteamCMD finished but valheim_server.exe is missing.')

    def bepinex(self) -> None:
        if not self.choices.bepinex:
            self.report('bepinex', 'Vanilla server selected; BepInEx is skipped.')
            return
        self.report('bepinex', 'Checking the current Valheim BepInEx pack…')
        metadata = json.loads(common.fetch_bytes(common.BEPINEX_API, 500_000))
        version = metadata.get('latest') or {}
        url = str(version.get('download_url') or '')
        if not url.startswith('https://thunderstore.io/package/download/denikson/BepInExPack_Valheim/'):
            raise InstallError('Thunderstore returned an unexpected BepInEx download address.')
        self.report('bepinex', f'Downloading BepInExPack Valheim {version.get("version_number", "")}…')
        common.extract_bepinex(common.fetch_bytes(url, 30_000_000), self.paths.game_files)
        if not (self.paths.game_files / 'winhttp.dll').is_file():
            raise InstallError('The BepInEx pack did not include its Windows loader (winhttp.dll).')
        config_in_game = self.paths.game_files / 'BepInEx' / 'config'
        persistent = self.paths.valheim / 'config' / 'BepInEx'
        if config_in_game.is_dir() and not config_in_game.is_junction() and not config_in_game.is_symlink():
            shutil.copytree(config_in_game, persistent, dirs_exist_ok=True)
            shutil.rmtree(config_in_game)
        if not config_in_game.exists():
            import _winapi
            _winapi.CreateJunction(str(persistent), str(config_in_game))

    def server_modpack(self) -> None:
        lock_path = self.paths.game_files / 'mods.lock.json'
        if not self.choices.install_modpack:
            if not lock_path.exists():
                lock_path.write_text('{"packages": {}}\n', encoding='utf-8')
            return
        self.report('modpack', 'Resolving and installing server-compatible modpack packages…')
        try:
            server_modpack.install(self.choices.modpack, self.paths.game_files,
                                   self.paths.valheim / 'config' / 'BepInEx',
                                   lambda message: self.report('modpack', message), -1, -1)
        except server_modpack.ModpackError as error:
            raise InstallError(str(error)) from error

    def game_settings(self) -> None:
        selected = self.choices
        self.report('game-service', 'Writing the Valheim settings…')
        settings = {
            'VH_NAME': selected.server_name, 'VH_WORLD': selected.world, 'VH_PORT': str(selected.port),
            'VH_PASSWORD': selected.game_password, 'VH_PUBLIC': '1' if selected.public else '0',
            'VH_CROSSPLAY': '1' if selected.crossplay else '0', 'VH_BEPINEX': '1' if selected.bepinex else '0',
            'VH_GAMEDIR': str(self.paths.game_files), 'VH_SAVEDIR': str(self.paths.valheim / 'saves'),
            'VH_MODIFIERS_MANAGED': '1' if selected.modifiers or selected.world_keys else '0',
            'VH_MODIFIERS': ','.join(f'{name}={value}' for name, value in selected.modifiers),
            'VH_SETKEYS': ','.join(selected.world_keys),
        }
        body = '# Heimdall Nexus managed Valheim settings\n' + ''.join(
            f'{key}={env_value(value)}\n' for key, value in settings.items())
        (self.paths.valheim / 'server.env').write_text(body, encoding='utf-8')

    def environment(self) -> None:
        """heimdall.env, the Windows counterpart of /etc/heimdall-nexus/heimdall.env."""
        paths, selected = self.paths, self.choices
        if paths.env_file.is_file():
            self.report('website', f'Keeping the existing settings in {paths.env_file}.')
            return
        values = {
            'HEIMDALL_BASE_DIR': paths.base, 'HEIMDALL_APP_BASE': paths.app_base,
            'HEIMDALL_ROOT': paths.app, 'HEIMDALL_SITE_DIR': paths.site, 'HEIMDALL_DATA_DIR': paths.data,
            'HEIMDALL_VALHEIM_DIR': paths.valheim, 'HEIMDALL_WEB_DIR': paths.web,
            'HEIMDALL_STATE_DIR': paths.state, 'HEIMDALL_SAGAS_DIR': paths.sagas,
            'HEIMDALL_PANEL_STATE_DIR': paths.panel_state, 'HEIMDALL_PANEL_SWAP_DIR': paths.swap,
            'HEIMDALL_PANEL_SOCKET': '127.0.0.1:8792', 'HEIMDALL_EXECUTOR_KEY_FILE': paths.executor_key,
            'HEIMDALL_GAME_SERVICE': 'heimdall-valheim',
            'HEIMDALL_PANEL_AUDIT_FILE': paths.logs / 'auditoria.jsonl',
            'HEIMDALL_PANEL_BACKUP_DIR': paths.backups / 'panel',
            'HEIMDALL_WEB_BACKUP_DIR': paths.backups / 'web',
            'HEIMDALL_CHRONICLE_DIR': paths.state / 'cronica', 'HEIMDALL_PROFILES_DIR': paths.state / 'perfis',
            'HEIMDALL_MODS_LOCK': paths.game_files / 'mods.lock.json',
            'HEIMDALL_STATUS_FILE': paths.web / 'api' / 'status.json',
            'HEIMDALL_SAGA_FILE': paths.web / 'api' / 'saga.json',
            'HEIMDALL_LOCATIONS_FILE': paths.web / 'mapa' / 'locais.json',
            'HEIMDALL_GAME_SERVICE_FILE': paths.service_files / 'heimdall-valheim.xml',
            'HEIMDALL_MAINTENANCE_LOCK': paths.run / 'heimdall-maintenance.lock',
            'HEIMDALL_LOG_DIR': paths.logs, 'HEIMDALL_RUN_DIR': paths.run,
            'HEIMDALL_WORLD_NAME': selected.world, 'HEIMDALL_SERVER_NAME': selected.server_name,
            'HEIMDALL_SERVER_ADDRESS': selected.server_address, 'HEIMDALL_SERVER_IP': '',
            'HEIMDALL_SERVER_PORT': selected.port, 'HEIMDALL_TIMEZONE': 'UTC',
            'HEIMDALL_PANEL_COOKIE_SECURE': 'true' if selected.tls else 'false',
            'HEIMDALL_PANEL_OS_USER': 'heimdall-panel', 'HEIMDALL_WEB_USER': 'heimdall-web',
            'PAINEL_RAIZ': '/jarl', 'PAINEL_CONFIG': paths.panel_config,
        }
        body = '# Heimdall Nexus settings (Windows)\n' + ''.join(
            f'{key}={env_value(str(value))}\n' for key, value in values.items())
        paths.env_file.write_text(body, encoding='utf-8')

    def website(self) -> None:
        """The editable site and its first publication (install-web.sh on Linux)."""
        paths, selected = self.paths, self.choices
        app_site = paths.app / 'site' / 'web'
        self.report('website', 'Installing the editable site…')
        sys.path.insert(0, str(app_site))
        if not (paths.site / '.heimdall-instance').exists():
            shutil.copytree(app_site, paths.site, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'mods.json', 'mods'))
            import identidade
            ident = identidade.carregar(paths.site)
            ident['nome'] = selected.server_name[:60] or ident['nome']
            ident['url'] = ('https://' if selected.tls else 'http://') + selected.domain
            ident = identidade.validar(ident)
            (paths.site / identidade.ARQUIVO).write_text(json.dumps(ident, ensure_ascii=False, indent=2) + '\n',
                                                          encoding='utf-8')
            manifest = json.loads((paths.site / 'site-pages.json').read_text(encoding='utf-8'))
            sources = [p['fonte'] for p in manifest['paginas']] + \
                [t['modelo'] for t in manifest.get('tipos', {}).values()]
            for relative in sources:
                page = paths.site / relative
                text = identidade.aplicar(page.read_text(encoding='utf-8'), ident)
                text = text.replace('seu-servidor.example.com', selected.server_address)
                page.write_text(text.replace(':2456', f':{selected.port}'), encoding='utf-8')
            (paths.site / '.heimdall-instance').write_text('', encoding='utf-8')
        modpack_config = paths.etc / 'modpack.json'
        if not modpack_config.exists():
            package = '' if not selected.modpack or server_modpack.is_local_pack(selected.modpack) else selected.modpack
            modpack_config.write_text(json.dumps({'package': package,
                                                  'description_overrides': str(paths.site / 'descricoes-pt.json')},
                                                 ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        for helper in ('publicar.py', 'values.py', 'sync_modpack.py', 'identidade.py', 'navegacao.py', 'sistema.py'):
            shutil.copy2(app_site / helper, paths.site / helper)
        self.command('website', [str(paths.python), '-X', 'utf8', str(app_site / 'migrar-paginas.py'),
                                 str(app_site), str(paths.site)], timeout=120)
        for catalog in ('hexium', 'thunderstore'):
            file = paths.data / 'catalogs' / f'{catalog}.json'
            if not file.exists():
                file.write_text('[]\n', encoding='utf-8')
        if not (paths.site / 'descricoes-pt.json').exists():
            (paths.site / 'descricoes-pt.json').write_text('{}\n', encoding='utf-8')
        package = json.loads(modpack_config.read_text(encoding='utf-8'))['package']
        if package:
            self.command('website', [str(paths.python), '-X', 'utf8', str(paths.site / 'sync_modpack.py'),
                                     '--config', str(modpack_config), '--output', str(paths.site / 'mods.json'),
                                     '--apply'], timeout=600)
        elif not (paths.site / 'mods.json').exists():
            (paths.site / 'mods.json').write_text(
                '{"modpack":"","modpack_owner":"","versao_pack":"","total":0,"mods":[]}\n', encoding='utf-8')
        api = paths.web / 'api'
        for name, empty in (('status.json', {'online': False, 'servidor': {}, 'jogadores': {}}),
                            ('saga.json', {'total_vikings': 0, 'jogadores': []})):
            if not (api / name).exists():
                (api / name).write_text(json.dumps(empty) + '\n', encoding='utf-8')
        (api / 'features.json').write_text(json.dumps({'enabled': list(selected.features)}) + '\n',
                                           encoding='utf-8')
        if (paths.site / 'assets').is_dir():
            shutil.copytree(paths.site / 'assets', paths.web / 'assets', dirs_exist_ok=True)
        env = {**os.environ, 'HEIMDALL_WEB_DIR': str(paths.web), 'HEIMDALL_WEB_USER': 'heimdall-web',
               'HEIMDALL_WEB_BACKUP_DIR': str(paths.backups / 'web'), 'HEIMDALL_SITE_DIR': str(paths.site),
               'HEIMDALL_ROOT': str(paths.app)}
        done = subprocess.run([str(paths.python), '-X', 'utf8', str(paths.site / 'publicar.py')], env=env,
                              capture_output=True, text=True, errors='replace', timeout=600)
        if done.returncode:
            raise InstallError('Publishing the site failed: ' + (done.stderr or done.stdout).strip()[-300:])

    def web_server(self) -> None:
        paths, selected = self.paths, self.choices
        caddy = paths.tools / 'caddy.exe'
        if not caddy.is_file():
            self.report('website', 'Downloading the Caddy web server…')
            data = common.fetch_bytes(CADDY_URL, 80_000_000)
            if hashlib.sha256(data).hexdigest() != CADDY_SHA256:
                raise InstallError('The Caddy download does not match its pinned hash.')
            with zipfile.ZipFile(io.BytesIO(data)) as bundle:
                caddy.write_bytes(bundle.read('caddy.exe'))
        sys.path.insert(0, str(HERE))
        import web
        (paths.caddy / 'Caddyfile').write_text(
            web.caddyfile(selected.domain, paths.web, tls=selected.tls, email=selected.email), encoding='utf-8')

    def panel_credentials(self) -> None:
        self.report('panel', 'Securing the panel administrator account…')
        sys.path.insert(0, str(self.paths.app / 'servicos' / 'painel'))
        os.environ['PAINEL_CONFIG'] = str(self.paths.panel_config)
        import nucleo
        nucleo.CONFIG = self.paths.panel_config
        config = nucleo.le_config()
        config.update({'usuario': self.choices.panel_user,
                       'senha': nucleo.cifra_senha(self.choices.panel_password),
                       'segredo': config.get('segredo') or secrets.token_urlsafe(48)})
        self.paths.panel_config.write_text(json.dumps(config, ensure_ascii=False, indent=2) + '\n',
                                           encoding='utf-8')
        if not self.paths.executor_key.is_file():
            self.paths.executor_key.write_text(secrets.token_hex(32) + '\n', encoding='ascii')

    def register_services(self) -> None:
        self.report('services', 'Registering the Windows services…')
        paths = self.paths
        winsw = services.fetch_winsw(paths.cache)
        definitions = services.definitions(game_autostart=self.choices.start_game)
        definitions.append(services.Service(
            'heimdall-web', 'Heimdall Nexus - web server', 'Caddy: the public site and the panel proxy.',
            (), start='Automatic', stop_seconds=20))
        for service in definitions:
            if service.name == 'heimdall-web':
                self._register_caddy(service, winsw)
                continue
            services.install(service, winsw=winsw, folder=paths.service_files, python=paths.python,
                             root=paths.app, logs=paths.logs, valheim=paths.valheim)
        jobs = {'heimdall-schedule': True,
                'heimdall-status': bool(set(self.choices.features) & {'servidor', 'jogadores', 'mundo',
                                                                       'estacoes', 'recursos'}),
                'heimdall-saga': 'saga' in self.choices.features}
        jobs_file = paths.state / 'jobs.json'
        if jobs_file.is_file():
            jobs = {**jobs, **json.loads(jobs_file.read_text(encoding='utf-8'))}
        jobs_file.write_text(json.dumps(jobs, indent=2) + '\n', encoding='utf-8')

    def _register_caddy(self, service, winsw: Path) -> None:
        paths = self.paths
        wrapper, definition = paths.service_files / 'heimdall-web.exe', paths.service_files / 'heimdall-web.xml'
        if subprocess.run(['sc.exe', 'query', 'heimdall-web'], capture_output=True).returncode == 0:
            subprocess.run([str(wrapper), 'stop'], capture_output=True, timeout=60)
            subprocess.run([str(wrapper), 'uninstall'], capture_output=True, timeout=60)
        shutil.copyfile(winsw, wrapper)
        sys.path.insert(0, str(HERE))
        import web
        definition.write_text(web.service_xml(paths.tools / 'caddy.exe', paths.caddy, paths.logs), encoding='utf-8')
        self.command('services', [str(wrapper), 'install'], timeout=120)
        self.command('services', ['sc.exe', 'config', 'heimdall-web', 'obj=', WEB], timeout=60)

    def permissions(self) -> None:
        """Each virtual account gets exactly what its Linux counterpart could reach."""
        self.report('permissions', 'Granting each service only its own folders…')
        p = self.paths
        read, modify = '(RX)', '(M)'
        for path, account, rights in (
            (p.panel_etc, PANEL, modify), (p.executor_key, PANEL, read), (p.env_file, PANEL, read),
            (p.env_file, SAGAS, read), (p.site, PANEL, read), (p.data, PANEL, read), (p.web, PANEL, read),
            (p.sagas, PANEL, read), (p.swap, PANEL, modify), (p.logs, PANEL, read), (p.valheim, PANEL, read),
            (p.sagas, SAGAS, modify), (p.valheim, GAME, modify), (p.sagas / 'inbox', GAME, modify),
            (p.env_file, GAME, read), (p.web, WEB, read), (p.caddy, WEB, modify),
        ):
            self.grant(path, account, rights)
        # The game reads its settings but must not rewrite them.
        server_env = p.valheim / 'server.env'
        self.icacls(server_env, '/inheritance:r', '/grant:r', f'{SYSTEM_SID}:F', f'{ADMINS_SID}:F',
                    f'{GAME}:R', f'{PANEL}:R')
        # Secrets only the panel reads.
        for secret in (p.executor_key, p.panel_config):
            if secret.exists():
                self.icacls(secret, '/inheritance:r', '/grant:r', f'{SYSTEM_SID}:F', f'{ADMINS_SID}:F',
                            f'{PANEL}:{"R" if secret == p.executor_key else "M"}')

    def firewall(self) -> None:
        self.report('firewall', 'Opening the game ports in Windows Firewall…')
        subprocess.run(['netsh', 'advfirewall', 'firewall', 'delete', 'rule', f'name={FIREWALL_GROUP} - Valheim'],
                       capture_output=True)
        port = self.choices.port
        self.command('firewall', ['netsh', 'advfirewall', 'firewall', 'add', 'rule',
                                  f'name={FIREWALL_GROUP} - Valheim', 'dir=in', 'action=allow',
                                  'protocol=UDP', f'localport={port}-{port + 1}',
                                  f'program={self.paths.game_files / "valheim_server.exe"}',
                                  'profile=any'], timeout=60)
        subprocess.run(['netsh', 'advfirewall', 'firewall', 'delete', 'rule', f'name={FIREWALL_GROUP} - Web'],
                       capture_output=True)
        self.command('firewall', ['netsh', 'advfirewall', 'firewall', 'add', 'rule',
                                  f'name={FIREWALL_GROUP} - Web', 'dir=in', 'action=allow', 'protocol=TCP',
                                  'localport=80,443', 'profile=any'], timeout=60)

    def start(self) -> None:
        self.report('services', 'Starting the panel, the site and the jobs…')
        for name in ('heimdall-executor', 'heimdall-panel', 'heimdall-web', 'heimdall-jobs', 'heimdall-sagas-jobs'):
            self.command('services', [str(self.paths.service_files / f'{name}.exe'), 'start'], timeout=120,
                         ok_codes=(0, 1))
        self._verify_web_routes()
        if self.choices.start_game:
            self.report('game-start', 'Starting Valheim…')
            self.command('game-start', [str(self.paths.service_files / 'heimdall-valheim.exe'), 'start'],
                         timeout=180)
        else:
            self.report('game-start', 'Valheim is installed and ready. Start it from the panel when you choose.')

    def _verify_web_routes(self) -> None:
        self.report('services', 'Checking the site and panel through Caddy…')
        for path in ('/', '/jarl/entrar'):
            last = 'no response'
            for _ in range(60):
                connection = http.client.HTTPConnection('127.0.0.1', 80, timeout=3)
                try:
                    connection.request('GET', path, headers={'Host': self.choices.domain})
                    response = connection.getresponse()
                    last = f'HTTP {response.status}'
                    if response.status in (200, 308) or (self.choices.tls and response.status in (301, 302)):
                        break
                except OSError as error:
                    last = str(error)
                finally:
                    connection.close()
                time.sleep(1)
            else:
                raise InstallError(f'{path} did not open through Caddy ({last}). '
                                   f'See the logs in {self.paths.logs}.')

    def run(self) -> dict:
        self.check()
        self.folders()
        self.runtime_code()
        self.python_environment()
        self.steamcmd()
        self.game()
        self.bepinex()
        self.server_modpack()
        self.game_settings()
        self.environment()
        self.website()
        self.web_server()
        self.panel_credentials()
        self.register_services()
        self.permissions()
        self.firewall()
        self.start()
        summary = self.choices.public_summary()
        summary.update({'product': 'Heimdall Nexus', 'author': 'BRKiHeL', 'platform': 'windows',
                        'installed_at': dt.datetime.now(dt.timezone.utc).isoformat()})
        self.paths.installed.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        self.report('complete', 'Installation complete. The panel can now manage this Valheim server.')
        scheme = 'https://' if self.choices.tls else 'http://'
        return {'site': scheme + self.choices.domain + '/', 'panel': scheme + self.choices.domain + '/jarl/entrar',
                'game_started': self.choices.start_game}
