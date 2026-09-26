"""Heimdall Nexus installation engine. Called only by the loopback setup wizard.

The engine keeps the game, site and panel in predictable locations so the
existing panel verbs can manage a freshly installed Valheim server. Downloads
come from Valve and the Valheim BepInEx pack's Thunderstore listing.
"""
from __future__ import annotations

import datetime as dt
import http.client
import io
import ipaddress
import json
import os
import queue
import re
import secrets
import shutil
import subprocess
import sys
import tarfile
import threading
import time
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable

import modpack as server_modpack

try:  # POSIX accounts: only the Linux installation steps use them
    import grp
    import pwd
except ImportError:  # Windows installs through deploy/windows/installer_windows.py
    grp = pwd = None


ROOT = Path(__file__).resolve().parents[1]
RUNTIME_ROOT = Path('/opt/heimdall-nexus')
ANSI = re.compile(r'\x1b\[[0-9;?]*[A-Za-z]')
GAME_ROOT = Path('/srv/valheim')
GAME_FILES = GAME_ROOT / 'current'
STEAMCMD_DIR = GAME_ROOT / 'steamcmd'
GAME_UNIT = Path('/etc/systemd/system/heimdall-valheim.service')
LAUNCHER = Path('/usr/local/lib/heimdall-nexus/valheim-launch.sh')
PANEL_CONFIG = Path('/etc/heimdall-panel/config.json')
INSTALL_STATE = Path('/var/lib/heimdall-nexus/installed.json')
STEAMCMD_URL = 'https://media.steampowered.com/installer/steamcmd_linux.tar.gz'
BEPINEX_API = 'https://thunderstore.io/api/experimental/package/denikson/BepInExPack_Valheim/'
FEATURES = {'servidor', 'jogadores', 'mundo', 'estacoes', 'recursos', 'saga'}
NAME = re.compile(r'^[A-Za-z0-9_. -]{1,40}$')
WORLD_NAME = re.compile(r'^[A-Za-z0-9_ -]{1,40}$')
HOST = re.compile(r'^[A-Za-z0-9.-]{1,253}$')
PACK = re.compile(r'^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$')


class InstallError(RuntimeError):
    """An installation error suitable for the wizard to display."""


# Same options as servicos/painel/operacoes.py and deploy/valheim-launch.sh;
# tests/test_acesso_modificadores.py keeps the three in sync.
MODIFIERS = {
    'combat': ('veryeasy', 'easy', 'default', 'hard', 'veryhard'),
    'deathpenalty': ('casual', 'veryeasy', 'easy', 'default', 'hard', 'hardcore'),
    'resources': ('muchless', 'less', 'default', 'more', 'muchmore', 'most'),
    'raids': ('none', 'muchless', 'less', 'default', 'more', 'muchmore'),
    'portals': ('casual', 'default', 'hard', 'veryhard'),
}
WORLD_KEYS = ('playerevents', 'fire', 'nomap', 'passivemobs', 'nobuildcost')


def _parse_modifiers(data: dict) -> tuple[tuple[tuple[str, str], ...], tuple[str, ...]]:
    raw = data.get('modifiers') or {}
    keys = data.get('world_keys') or []
    if not isinstance(raw, dict) or set(raw) - set(MODIFIERS) or \
            any(raw[name] not in MODIFIERS[name] for name in raw):
        raise InstallError('Invalid world modifier.')
    if not isinstance(keys, list) or any(key not in WORLD_KEYS for key in keys):
        raise InstallError('Invalid world option.')
    chosen = tuple((name, raw[name]) for name in MODIFIERS if raw.get(name, 'default') != 'default')
    return chosen, tuple(key for key in WORLD_KEYS if key in keys)


@dataclass(frozen=True)
class Choices:
    domain: str
    server_address: str
    server_name: str
    world: str
    game_password: str
    system_user: str
    panel_user: str
    panel_password: str
    port: int
    public: bool
    crossplay: bool
    bepinex: bool
    modpack: str
    install_modpack: bool
    features: tuple[str, ...]
    tls: bool
    email: str
    start_game: bool
    modifiers: tuple[tuple[str, str], ...] = ()
    world_keys: tuple[str, ...] = ()

    @classmethod
    def parse(cls, data: dict) -> 'Choices':
        if not isinstance(data, dict):
            raise InstallError('Invalid installation request.')
        domain = str(data.get('domain', '')).strip().lower()
        address = str(data.get('server_address') or domain).strip().lower()
        server_name = str(data.get('server_name') or 'Valheim').strip()
        world = str(data.get('world') or 'Valheim').strip()
        game_password = str(data.get('game_password') or '')
        system_user = str(data.get('system_user') or 'heimdall').strip().lower()
        panel_user = str(data.get('panel_user') or 'jarl').strip()
        panel_password = str(data.get('panel_password') or '')
        email = str(data.get('email') or '').strip()
        modpack = str(data.get('modpack') or '').strip()
        if modpack and not server_modpack.is_local_pack(modpack):
            modpack = server_modpack.normalize_package(modpack)
        try:
            port = int(data.get('port', 2456))
        except (TypeError, ValueError) as exc:
            raise InstallError('Game port must be a number.') from exc
        raw_features = data.get('features', ['servidor', 'jogadores', 'mundo'])
        if not isinstance(raw_features, list) or not all(isinstance(x, str) for x in raw_features):
            raise InstallError('Invalid live data choices.')
        features = tuple(dict.fromkeys(raw_features))
        if not domain or not HOST.fullmatch(domain) or '..' in domain or domain.startswith('-'):
            raise InstallError('Enter a valid site domain or IP address.')
        if not HOST.fullmatch(address) or '..' in address or address.startswith('-'):
            raise InstallError('Enter a valid game address.')
        if not NAME.fullmatch(server_name) or not WORLD_NAME.fullmatch(world):
            raise InstallError('The server name accepts dots; the world name accepts letters, numbers, spaces, _ and -.')
        if not 1024 <= port <= 65534:
            raise InstallError('Game port must be between 1024 and 65534.')
        # Vanilla Valheim should never run open; a passwordless server needs a mod for that.
        if len(game_password) < 5 or len(game_password) > 100 or '\n' in game_password:
            raise InstallError('Game password must have at least 5 characters and no newline.')
        if game_password.casefold() in server_name.casefold():
            raise InstallError('Game password cannot appear in the server name.')
        if not re.fullmatch(r'[a-z_][a-z0-9_-]{2,30}', system_user) or system_user in {
            'root', 'valheim', 'www-data', 'nobody', 'daemon',
        }:
            raise InstallError('Linux service user needs 3–31 lowercase letters, numbers, _ or -, and cannot be a reserved account.')
        if not re.fullmatch(r'[A-Za-z0-9_-]{3,30}', panel_user):
            raise InstallError('Panel user must have 3–30 letters, numbers, _ or -.')
        if len(panel_password) < 10 or '\n' in panel_password or len(panel_password) > 200:
            raise InstallError('Panel password must have at least 10 characters and no newline.')
        if set(features) - FEATURES:
            raise InstallError('An unknown live data option was selected.')
        bepinex = data.get('bepinex') is True
        if modpack and not bepinex:
            raise InstallError('A modpack needs BepInEx.')
        if modpack and server_modpack.is_local_pack(modpack):
            try:
                server_modpack.read_local_pack(Path(modpack))
            except server_modpack.ModpackError as exc:
                raise InstallError(str(exc)) from exc
        elif modpack and not PACK.fullmatch(modpack):
            raise InstallError('Modpack not recognized. Paste the package page link from Thunderstore or Hexium, '
                               'type Author/Package, or give the full path of a .zip on this server.')
        install_modpack = data.get('install_modpack') is True
        if install_modpack and not modpack:
            raise InstallError('Choose a Hexium modpack before installing server mods.')
        tls = data.get('tls') is True
        if tls:
            try:
                ipaddress.ip_address(domain)
            except ValueError:
                pass
            else:
                raise InstallError('Automatic HTTPS needs a DNS name, not an IP address.')
            if domain in {'localhost', '127.0.0.1'} or '.' not in domain:
                raise InstallError('Automatic HTTPS needs a public DNS name.')
            if not re.fullmatch(r'[^\s@]+@[^\s@]+\.[^\s@]+', email):
                raise InstallError('Enter an email address for the HTTPS certificate.')
        return cls(domain, address, server_name, world, game_password,
                   system_user, panel_user, panel_password, port,
                   data.get('public') is True, data.get('crossplay') is True,
                   bepinex, modpack, install_modpack, features, tls, email,
                   data.get('start_game') is True, *_parse_modifiers(data))

    def public_summary(self) -> dict:
        """Safe to return to the browser or write to the installation record."""
        return {'domain': self.domain, 'server_address': self.server_address,
                'server_name': self.server_name, 'world': self.world, 'port': self.port,
                'public': self.public, 'crossplay': self.crossplay,
                'bepinex': self.bepinex, 'modpack': self.modpack,
                'install_modpack': self.install_modpack,
                'features': list(self.features), 'tls': self.tls,
                'start_game': self.start_game, 'system_user': self.system_user,
                'panel_user': self.panel_user,
                'modifiers': dict(self.modifiers), 'world_keys': list(self.world_keys)}


def fetch_bytes(url: str, limit: int) -> bytes:
    if not url.startswith('https://'):
        raise InstallError('Refused a download outside HTTPS.')
    request = urllib.request.Request(url, headers={'User-Agent': 'Heimdall-Nexus-Installer/1.0'})
    with urllib.request.urlopen(request, timeout=45) as response:
        data = response.read(limit + 1)
    if len(data) > limit:
        raise InstallError('Downloaded archive is larger than expected.')
    return data


def _safe_relative(name: str) -> Path:
    posix = PurePosixPath(name)
    if posix.is_absolute() or not posix.parts or '..' in posix.parts or any('\\' in p for p in posix.parts):
        raise InstallError('Archive contains an unsafe path.')
    return Path(*posix.parts)


def extract_steamcmd(data: bytes, target: Path) -> None:
    """Extract only regular Valve archive files beneath target."""
    with tarfile.open(fileobj=io.BytesIO(data), mode='r:gz') as archive:
        for member in archive:
            relative = _safe_relative(member.name)
            destination = target / relative
            if member.isdir():
                destination.mkdir(parents=True, exist_ok=True)
            elif member.isfile():
                if member.size > 20_000_000:
                    raise InstallError('SteamCMD archive contains an unexpectedly large file.')
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.extractfile(member) as source, destination.open('wb') as output:
                    shutil.copyfileobj(source, output)
                # SteamCMD's archive also includes native executables without a .sh suffix.
                destination.chmod(0o755 if member.mode & 0o111 or relative.name.endswith('.sh') else 0o644)
            else:
                raise InstallError('SteamCMD archive contains an unsupported link or file type.')


def extract_bepinex(data: bytes, target: Path) -> None:
    """Install only files beneath the pack's expected top-level folder."""
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        for member in archive.infolist():
            parts = PurePosixPath(member.filename).parts
            if not parts or parts[0] != 'BepInExPack_Valheim':
                continue  # package README/manifest/icon live outside the payload
            if len(parts) == 1:
                continue
            relative = _safe_relative('/'.join(parts[1:]))
            destination = target / relative
            if member.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
                continue
            if member.file_size > 30_000_000 or ((member.external_attr >> 16) & 0o170000) == 0o120000:
                raise InstallError('BepInEx archive contains an unsafe file.')
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(member) as source, destination.open('wb') as output:
                shutil.copyfileobj(source, output)
            destination.chmod(0o755 if relative.name.endswith('.sh') else 0o644)
    if not (target / 'BepInEx/core/BepInEx.Preloader.dll').is_file():
        raise InstallError('BepInEx download did not contain the expected server files.')


def _write_private(path: Path, content: str, *, mode: int, owner: str, group: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name('.' + path.name + '.heimdall')
    try:
        temporary.write_text(content, encoding='utf-8')
        os.chmod(temporary, mode)
        os.chown(temporary, pwd.getpwnam(owner).pw_uid, grp.getgrnam(group).gr_gid)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _env_value(value: str) -> str:
    if '\n' in value or '\r' in value or '\0' in value:
        raise InstallError('A configuration value contains an invalid control character.')
    return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'


class Installer:
    def __init__(self, choices: Choices, report: Callable[[str, str], None],
                 *, root: Path = ROOT, game_root: Path = GAME_ROOT):
        self.choices, self.report = choices, report
        self.root, self.game_root = root, game_root
        self.runtime_root = RUNTIME_ROOT
        self.game_files = game_root / 'current'
        self.steamcmd_dir = game_root / 'steamcmd'

    def command(self, step: str, argv: list[str], timeout: int = 2400) -> None:
        """Run a fixed-argument process and stream its output to the wizard."""
        self.report(step, 'Running ' + Path(argv[0]).name + '…')
        stream: queue.Queue[str | None] = queue.Queue()
        process = subprocess.Popen(argv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                   text=True, bufsize=1, env={**os.environ, 'DEBIAN_FRONTEND': 'noninteractive'})

        def reader():
            assert process.stdout is not None
            for line in process.stdout:
                stream.put(ANSI.sub('', line).rstrip()[:400])
            stream.put(None)

        threading.Thread(target=reader, daemon=True).start()
        deadline = time.monotonic() + timeout
        last = error = ''
        while True:
            try:
                item = stream.get(timeout=0.5)
            except queue.Empty:
                item = ''
            if item is None:
                # Output closed. The process may exit a moment later, so wait
                # for it instead of polling once (a lost EOF hung until timeout).
                try:
                    process.wait(timeout=max(1.0, deadline - time.monotonic()))
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                    raise InstallError(f'{step} timed out.')
                break
            if item:
                last = item
                if 'ERROR' in item or 'FAILED' in item.upper():
                    error = item
                self.report(step, item)
            if time.monotonic() > deadline:
                process.kill()
                process.wait()
                raise InstallError(f'{step} timed out.')
        if process.wait() != 0:
            raise InstallError(f'{step} failed: {error or last or "see system logs"}')

    def _chown_tree(self, path: Path) -> None:
        user = pwd.getpwnam('valheim')
        for base, directories, files in os.walk(path):
            os.lchown(base, user.pw_uid, user.pw_gid)
            for filename in files:
                os.lchown(os.path.join(base, filename), user.pw_uid, user.pw_gid)

    def dependencies(self) -> None:
        self.report('packages', 'Installing operating system packages…')
        self.command('packages', ['apt-get', 'update'], timeout=900)
        packages = ['ca-certificates', 'curl', 'tar', 'unzip', 'libc6-i386',
                    'lib32gcc-s1', 'libatomic1', 'libpulse0', 'libpulse-dev',
                    'nginx', 'python3', 'python3-venv', 'python3-pip', 'rsync']
        if self.choices.tls:
            packages += ['certbot', 'python3-certbot-nginx']
        self.command('packages', ['apt-get', 'install', '-y', *packages], timeout=1800)

    def runtime_code(self) -> None:
        """Install only the runtime code outside the operator's home directory.

        The checkout is an installation source. The panel and collectors must not
        depend on traversing its owner’s private home directory after setup.
        """
        self.report('runtime', f'Installing service code in {self.runtime_root}…')
        account_marker = Path('/etc/heimdall-nexus/panel-os-user')
        if account_marker.is_file():
            if account_marker.read_text(encoding='utf-8').strip() != self.choices.system_user:
                raise InstallError('This partial installation already uses another Linux service account.')
        else:
            try:
                pwd.getpwnam(self.choices.system_user)
            except KeyError:
                pass
            else:
                raise InstallError(f'The Linux account {self.choices.system_user} already exists. Choose another name.')
            try:
                grp.getgrnam(self.choices.system_user)
            except KeyError:
                pass
            else:
                raise InstallError(f'The Linux group {self.choices.system_user} already exists. Choose another name.')
        if self.root.resolve() == self.runtime_root.resolve():
            return
        marker = self.runtime_root / '.heimdall-nexus-runtime'
        if self.runtime_root.is_symlink():
            raise InstallError(f'{self.runtime_root} must be a real directory, not a symbolic link.')
        if self.runtime_root.exists() and any(self.runtime_root.iterdir()) and not marker.is_file():
            raise InstallError(f'{self.runtime_root} already contains unrelated files; move them before installing.')
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        os.chown(self.runtime_root, 0, 0)
        self.runtime_root.chmod(0o755)
        # Mark the destination before copying, so a partial copy can be retried.
        marker.write_text('Heimdall Nexus service code\n', encoding='utf-8')
        marker.chmod(0o644)
        parts = ('deploy', 'servicos/painel', 'ferramentas', 'site/web')
        excludes = ('--exclude=.git/', '--exclude=.venv/', '--exclude=__pycache__/',
                    '--exclude=.agora-code/', '--exclude=*.pyc', '--exclude=*.bak*',
                    '--exclude=mapa/', '--exclude=assets/mods/')
        for part in parts:
            source = self.root / part
            if not source.is_dir():
                raise InstallError(f'The checkout is missing {part}.')
            target = self.runtime_root / part
            target.mkdir(parents=True, exist_ok=True)
            self.command('runtime', ['rsync', '-a', '--chown=root:root', *excludes,
                                     str(source) + '/', str(target) + '/'], timeout=180)
            # Rsync preserves source directory modes; a private checkout must
            # not make the installed copy inaccessible to systemd services.
            for base, directories, _ in os.walk(target):
                os.chmod(base, 0o755)
                directories[:] = [name for name in directories
                                  if name not in {'.venv', '.git', '__pycache__'}]

    def account(self) -> None:
        self.report('account', 'Creating the dedicated valheim system account…')
        if subprocess.run(['id', '-u', 'valheim'], capture_output=True).returncode != 0:
            self.command('account', ['useradd', '--system', '--home-dir', str(self.game_root),
                                     '--create-home', '--shell', '/usr/sbin/nologin', 'valheim'])
        for path in (self.game_root, self.game_files, self.steamcmd_dir,
                     self.game_root / 'saves', self.game_root / 'saves/worlds_local',
                     self.game_root / 'config/BepInEx', self.game_root / 'backups'):
            path.mkdir(parents=True, exist_ok=True)
            user = pwd.getpwnam('valheim')
            os.chown(path, user.pw_uid, user.pw_gid)
            path.chmod(0o750)

    def steamcmd(self) -> None:
        executable = self.steamcmd_dir / 'steamcmd.sh'
        if not executable.is_file():
            self.report('steamcmd', 'Downloading SteamCMD from Valve…')
            extract_steamcmd(fetch_bytes(STEAMCMD_URL, 20_000_000), self.steamcmd_dir)
            self._chown_tree(self.steamcmd_dir)
        if not executable.is_file():
            raise InstallError('SteamCMD archive did not contain steamcmd.sh.')

    def game(self) -> None:
        steamcmd = ['runuser', '-u', 'valheim', '--', str(self.steamcmd_dir / 'steamcmd.sh')]
        # A fresh SteamCMD updates and restarts itself on first run; downloading an
        # app in that same session often fails with "Missing configuration".
        self.report('valheim', 'Updating SteamCMD…')
        self.command('valheim', [*steamcmd, '+quit'], timeout=900)
        self.report('valheim', 'Downloading Valheim Dedicated Server (Steam App 896660)…')
        for attempt in range(1, 4):
            try:
                self.command('valheim', [*steamcmd, '+force_install_dir', str(self.game_files),
                                         '+login', 'anonymous', '+app_update', '896660',
                                         'validate', '+quit'], timeout=3600)
                break
            except InstallError as exc:
                if attempt == 3:
                    raise
                self.report('valheim', f'SteamCMD did not finish ({exc}). Retrying ({attempt + 1}/3)…')
                time.sleep(10)
        if not (self.game_files / 'valheim_server.x86_64').is_file():
            raise InstallError('SteamCMD finished but the Valheim server binary is missing.')

    def bepinex(self) -> None:
        if not self.choices.bepinex:
            self.report('bepinex', 'Vanilla server selected; BepInEx is skipped.')
            return
        self.report('bepinex', 'Checking the current Valheim BepInEx pack…')
        metadata = json.loads(fetch_bytes(BEPINEX_API, 500_000))
        version = metadata.get('latest') or {}
        url = str(version.get('download_url') or '')
        if not url.startswith('https://thunderstore.io/package/download/denikson/BepInExPack_Valheim/'):
            raise InstallError('Thunderstore returned an unexpected BepInEx download address.')
        self.report('bepinex', f'Downloading BepInExPack Valheim {version.get("version_number", "")}…')
        extract_bepinex(fetch_bytes(url, 30_000_000), self.game_files)
        config_in_game = self.game_files / 'BepInEx/config'
        persistent_config = self.game_root / 'config/BepInEx'
        if config_in_game.is_dir() and not config_in_game.is_symlink():
            shutil.copytree(config_in_game, persistent_config, dirs_exist_ok=True)
            shutil.rmtree(config_in_game)
        if not config_in_game.exists():
            config_in_game.symlink_to(persistent_config, target_is_directory=True)
        self._chown_tree(self.game_files)
        self._chown_tree(persistent_config)

    def server_modpack(self) -> None:
        lock_path = self.game_files / 'mods.lock.json'
        if not self.choices.install_modpack:
            if not lock_path.exists():
                lock_path.write_text('{"packages": {}}\n', encoding='utf-8')
                user = pwd.getpwnam('valheim')
                os.chown(lock_path, user.pw_uid, user.pw_gid)
                lock_path.chmod(0o640)
            return
        self.report('modpack', 'Resolving and installing server-compatible modpack packages…')
        user = pwd.getpwnam('valheim')
        try:
            server_modpack.install(self.choices.modpack, self.game_files,
                                   self.game_root / 'config/BepInEx',
                                   lambda message: self.report('modpack', message),
                                   user.pw_uid, user.pw_gid)
        except server_modpack.ModpackError as exc:
            raise InstallError(str(exc)) from exc
        self._chown_tree(self.game_files / 'BepInEx')
        self._chown_tree(self.game_root / 'config/BepInEx')

    def game_service(self) -> None:
        selected = self.choices
        self.report('game-service', 'Writing Valheim settings and systemd service…')
        settings = {
            'VH_NAME': selected.server_name,
            'VH_WORLD': selected.world,
            'VH_PORT': str(selected.port),
            'VH_PASSWORD': selected.game_password,
            'VH_PUBLIC': '1' if selected.public else '0',
            'VH_CROSSPLAY': '1' if selected.crossplay else '0',
            'VH_BEPINEX': '1' if selected.bepinex else '0',
            'VH_GAMEDIR': str(self.game_files),
            'VH_SAVEDIR': str(self.game_root / 'saves'),
            # A new world has no modifiers to preserve: manage them from the start
            # when the admin chose any (Jarl > Server Config shows the same options).
            'VH_MODIFIERS_MANAGED': '1' if selected.modifiers or selected.world_keys else '0',
            'VH_MODIFIERS': ','.join(f'{name}={value}' for name, value in selected.modifiers),
            'VH_SETKEYS': ','.join(selected.world_keys),
        }
        body = '# Heimdall Nexus managed Valheim settings\n' + ''.join(
            f'{key}={_env_value(value)}\n' for key, value in settings.items())
        _write_private(self.game_root / 'server.env', body, mode=0o640,
                       owner='root', group='valheim')
        launcher = self.root / 'deploy/valheim-launch.sh'
        unit = (self.root / 'deploy/systemd/heimdall-valheim.service').read_text(encoding='utf-8')
        unit = unit.replace('@GAME_ROOT@', str(self.game_root)).replace('@LAUNCHER@', str(LAUNCHER))
        LAUNCHER.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(launcher, LAUNCHER)
        LAUNCHER.chmod(0o755)
        GAME_UNIT.write_text(unit, encoding='utf-8')
        GAME_UNIT.chmod(0o644)
        self.command('game-service', ['systemctl', 'daemon-reload'], timeout=60)

    def website(self) -> None:
        selected = self.choices
        self.report('website', 'Installing the editable site and administration panel…')
        args = [str(self.runtime_root / 'deploy/install-web.sh'), '--root', str(self.runtime_root),
                '--domain', selected.domain, '--server-address', selected.server_address,
                '--panel-os-user', selected.system_user,
                '--server-name', selected.server_name, '--server-port', str(selected.port),
                '--world-name', selected.world,
                '--modpack', 'none' if not selected.modpack or server_modpack.is_local_pack(selected.modpack)
                else selected.modpack,
                '--features', ','.join(selected.features) or 'none',
                '--cookie-secure', 'true' if selected.tls else 'false', '--no-start']
        self.command('website', args, timeout=1800)

    def panel_credentials(self) -> None:
        self.report('panel', 'Securing the panel administrator account…')
        sys.path.insert(0, str(self.runtime_root / 'servicos/painel'))
        import nucleo  # imported after the web phase creates panel paths
        config = nucleo.le_config()
        config.update({'usuario': self.choices.panel_user,
                       'senha': nucleo.cifra_senha(self.choices.panel_password),
                       'segredo': config.get('segredo') or secrets.token_urlsafe(48)})
        _write_private(PANEL_CONFIG, json.dumps(config, ensure_ascii=False, indent=2) + '\n',
                       mode=0o600, owner=self.choices.system_user,
                       group=self.choices.system_user)

    def services(self) -> None:
        self.report('services', 'Starting the web panel and its data collectors…')
        self.command('services', ['systemctl', 'enable', '--now',
                                  'heimdall-executor.service', 'heimdall-panel.service',
                                  'heimdall-schedule.timer', 'nginx.service'], timeout=180)
        # nginx is usually already running after apt installs it. Starting an
        # active unit does not load the vhost written by install-web.sh.
        self.command('services', ['nginx', '-t'], timeout=30)
        self.command('services', ['systemctl', 'reload', 'nginx.service'], timeout=30)
        self._verify_web_routes()
        if set(self.choices.features) & {'servidor', 'jogadores', 'mundo', 'estacoes', 'recursos'}:
            self.command('services', ['systemctl', 'enable', '--now', 'heimdall-status.timer'])
        if 'saga' in self.choices.features:
            self.command('services', ['systemctl', 'enable', '--now', 'heimdall-saga.timer'])
        if self.choices.tls:
            self.report('https', 'Requesting an HTTPS certificate from Let’s Encrypt…')
            self.command('https', ['certbot', '--nginx', '--non-interactive', '--agree-tos',
                                   '--email', self.choices.email, '--redirect',
                                   '-d', self.choices.domain], timeout=600)
        if self.choices.start_game:
            self.report('game-start', 'Starting Valheim and enabling it on boot…')
            self.command('game-start', ['systemctl', 'enable', '--now', 'heimdall-valheim.service'],
                         timeout=300)
        else:
            self.report('game-start', 'Valheim is installed and ready. Start it from the panel when you choose.')

    def _verify_web_routes(self) -> None:
        self.report('services', 'Checking the site and panel through Nginx…')
        for path in ('/', '/jarl/entrar'):
            last = 'no response'
            for _ in range(20):
                connection = http.client.HTTPConnection('127.0.0.1', 80, timeout=3)
                try:
                    connection.request('GET', path, headers={'Host': self.choices.domain})
                    response = connection.getresponse()
                    last = f'HTTP {response.status}'
                    if response.status == 200:
                        break
                except OSError as error:
                    last = str(error)
                finally:
                    connection.close()
                time.sleep(0.5)
            else:
                raise InstallError(f'{path} did not open through Nginx ({last}). '
                                   'Check the Nginx and heimdall-panel services.')

    def run(self) -> dict:
        if os.geteuid() != 0:
            raise InstallError('The visual installer must run as root (sudo).')
        self.dependencies()
        self.runtime_code()
        self.account()
        self.steamcmd()
        self.game()
        self.bepinex()
        self.server_modpack()
        self.game_service()
        self.website()
        self.panel_credentials()
        self.services()
        summary = self.choices.public_summary()
        summary.update({'product': 'Heimdall Nexus', 'author': 'BRKiHeL',
                        'installed_at': dt.datetime.now(dt.timezone.utc).isoformat()})
        INSTALL_STATE.parent.mkdir(parents=True, exist_ok=True)
        _write_private(INSTALL_STATE, json.dumps(summary, ensure_ascii=False, indent=2) + '\n',
                       mode=0o600, owner='root', group='root')
        self.report('complete', 'Installation complete. The panel can now manage this Valheim server.')
        return {'site': ('https://' if self.choices.tls else 'http://') + self.choices.domain + '/',
                'panel': ('https://' if self.choices.tls else 'http://') + self.choices.domain + '/jarl/entrar',
                'game_started': self.choices.start_game}
