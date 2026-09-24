"""Install a Hexium/Thunderstore Valheim modpack onto a fresh BepInEx server.

The root is either a published package (Author/Package) or a local .zip in
the same Thunderstore layout: manifest.json whose dependencies are public
packages, plus bundled plugins/, patchers/ and config/ for mods that are not
published. The selected package pins its dependency versions. Explicit client-only
packages are skipped on the dedicated server; all other dependencies are
resolved recursively. Downloads are staged and checked before files are
copied to the game directory.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Callable


HEXIUM_API = 'https://valheim.hexium.gg/api/experimental/package/'
THUNDERSTORE_API = 'https://thunderstore.io/api/experimental/package/'
ALLOWED_DOWNLOAD_HOSTS = {'cdn.hexium.gg', 'thunderstore.io', 'cdn.thunderstore.io',
                          'gcdn.thunderstore.io', 'ccdn.thunderstore.io'}
PART = re.compile(r'^[A-Za-z0-9_.-]{1,80}$')
VERSION = re.compile(r'^\d+(?:\.\d+){1,3}(?:[-+][A-Za-z0-9.-]+)?$')
DOCS = {'manifest.json', 'icon.png', 'readme.md', 'changelog.md', 'license.md', 'license.txt'}
MAX_PACKAGES = 200
MAX_DOWNLOAD = 300 * 1024 * 1024
MAX_UNCOMPRESSED = 500 * 1024 * 1024


class ModpackError(RuntimeError):
    pass


@dataclass(frozen=True)
class Package:
    owner: str
    name: str
    version: str
    dependencies: tuple[str, ...]
    download_url: str
    source: str
    client_only: bool = False

    @property
    def package_id(self) -> str:
        return f'{self.owner}-{self.name}'


def parse_dependency(raw: str) -> tuple[str, str, str]:
    before, dash, version = raw.rpartition('-')
    owner, split, name = before.partition('-')
    if not dash or not split or not PART.fullmatch(owner) or not PART.fullmatch(name) or not VERSION.fullmatch(version):
        raise ModpackError(f'Invalid modpack dependency: {raw[:100]}')
    return owner, name, version


def _version_key(value: str) -> tuple[tuple[int, ...], int, str]:
    base, _, suffix = value.partition('-')
    base = base.split('+', 1)[0]
    numbers = tuple(int(piece) for piece in base.split('.'))
    return numbers, 0 if suffix else 1, suffix


def is_local_pack(package: str) -> bool:
    return package.startswith('/') and package.lower().endswith('.zip')


def read_local_pack(path: Path) -> dict:
    """Validate a local modpack archive and return its root identity."""
    if not path.is_absolute() or path.suffix.lower() != '.zip' or not path.is_file():
        raise ModpackError(f'Local modpack not found: {path}')
    if not zipfile.is_zipfile(path):
        raise ModpackError('The local modpack is not a ZIP archive.')
    with zipfile.ZipFile(path) as bundle:
        try:
            manifest = json.loads(bundle.read('manifest.json').decode('utf-8-sig'))
        except (KeyError, ValueError) as exc:
            raise ModpackError('The local modpack is missing a valid manifest.json.') from exc
    if not isinstance(manifest, dict):
        raise ModpackError('The local modpack manifest.json must be an object.')
    owner = str(manifest.get('author') or 'Local')
    name = str(manifest.get('name') or '')
    version = str(manifest.get('version_number') or '')
    dependencies = manifest.get('dependencies') or []
    if not PART.fullmatch(owner) or not PART.fullmatch(name) or not VERSION.fullmatch(version):
        raise ModpackError('manifest.json needs a valid author, name and version_number.')
    if not isinstance(dependencies, list) or not all(isinstance(d, str) for d in dependencies):
        raise ModpackError('manifest.json dependencies must be a list of Owner-Name-Version.')
    for dependency in dependencies:
        parse_dependency(dependency)
    return {'path': path, 'owner': owner, 'name': name, 'version': version,
            'dependencies': tuple(dependencies)}


def _get_json(url: str) -> dict:
    request = urllib.request.Request(url, headers={'User-Agent': 'Heimdall-Nexus-Installer/1.0'})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.load(response)
    if not isinstance(data, dict):
        raise ModpackError('A package API returned an invalid response.')
    return data


def _metadata(owner: str, name: str, version: str | None,
              fetch: Callable[[str], dict]) -> tuple[dict, dict, str]:
    suffix = f'{owner}/{name}/'
    for base, source in ((HEXIUM_API, 'hexium'), (THUNDERSTORE_API, 'thunderstore')):
        try:
            info = fetch(base + suffix)
            selected = fetch(base + suffix + version + '/') if version else info['latest']
            if selected.get('version_number') != (version or selected.get('version_number')):
                raise ModpackError(f'{owner}/{name} returned a different version than requested.')
            return info, selected, source
        except (urllib.error.HTTPError, urllib.error.URLError, KeyError):
            continue
    raise ModpackError(f'Package or pinned version unavailable: {owner}/{name} {version or "latest"}.')


def resolve(package: str, fetch: Callable[[str], dict] = _get_json,
            local: dict | None = None) -> tuple[list[Package], list[str]]:
    """Return dependency-first install order and explicitly client-only IDs."""
    parts = package.split('/')
    if local is None and (len(parts) != 2 or not all(PART.fullmatch(part) for part in parts)):
        raise ModpackError('A modpack must be written as Author/Package.')
    installed: dict[str, Package] = {}
    seen_versions: dict[str, str] = {}
    skipped: list[str] = []
    visiting: set[str] = set()

    def visit(owner: str, name: str, version: str | None, *, root: bool = False) -> None:
        package_id = f'{owner}-{name}'
        if package_id == 'denikson-BepInExPack_Valheim':
            return  # the base BepInEx pack is installed by the engine itself
        if package_id in visiting:
            raise ModpackError(f'Circular modpack dependency: {package_id}.')
        if package_id in seen_versions:
            if version is None or _version_key(version) <= _version_key(seen_versions[package_id]):
                return
        if len(seen_versions) >= MAX_PACKAGES:
            raise ModpackError(f'The pack exceeds the limit of {MAX_PACKAGES} packages.')
        visiting.add(package_id)
        info, selected, source = _metadata(owner, name, version, fetch)
        pinned = str(selected['version_number'])
        if not VERSION.fullmatch(pinned):
            raise ModpackError(f'Invalid version of {package_id}: {pinned}.')
        seen_versions[package_id] = pinned
        listings = info.get('community_listings') or []
        categories = {c.casefold() for row in listings if row.get('community') == 'valheim'
                      for c in row.get('categories') or [] if isinstance(c, str)}
        only_client = 'client-only' in categories or 'client only' in categories
        if only_client and not root:
            if package_id not in skipped:
                skipped.append(package_id)
            installed.pop(package_id, None)
            visiting.remove(package_id)
            return
        dependencies = selected.get('dependencies') or []
        if not isinstance(dependencies, list) or not all(isinstance(d, str) for d in dependencies):
            raise ModpackError(f'Invalid dependency list in {package_id}.')
        for dependency in dependencies:
            dep_owner, dep_name, dep_version = parse_dependency(dependency)
            visit(dep_owner, dep_name, dep_version)
        download_url = str(selected.get('download_url') or '')
        parsed = urllib.parse.urlparse(download_url)
        if parsed.scheme != 'https' or parsed.hostname not in ALLOWED_DOWNLOAD_HOSTS:
            if source == 'thunderstore':
                download_url = f'https://thunderstore.io/package/download/{owner}/{name}/{pinned}/'
            else:
                raise ModpackError(f'Unexpected download URL for {package_id}.')
        installed[package_id] = Package(owner, name, pinned, tuple(dependencies), download_url, source,
                                        only_client)
        visiting.remove(package_id)

    if local is None:
        visit(parts[0], parts[1], None, root=True)
    else:
        for dependency in local['dependencies']:
            visit(*parse_dependency(dependency))
        installed[f"{local['owner']}-{local['name']}"] = Package(
            local['owner'], local['name'], local['version'], local['dependencies'], '', 'bundled')
    ordered: list[Package] = []
    ordered_ids: set[str] = set()
    ordering: set[str] = set()

    def order(package_id: str) -> None:
        if package_id in ordered_ids or package_id not in installed:
            return
        if package_id in ordering:
            raise ModpackError(f'Circular modpack dependency: {package_id}.')
        ordering.add(package_id)
        item = installed[package_id]
        for dependency in item.dependencies:
            owner, name, _ = parse_dependency(dependency)
            order(f'{owner}-{name}')
        ordering.remove(package_id)
        ordered_ids.add(package_id)
        ordered.append(item)

    for package_id in installed:
        order(package_id)
    return ordered, skipped


def download(url: str, output: Path) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.scheme != 'https' or parsed.hostname not in ALLOWED_DOWNLOAD_HOSTS:
        raise ModpackError('Refused an untrusted package download URL.')
    request = urllib.request.Request(url, headers={'User-Agent': 'Heimdall-Nexus-Installer/1.0'})
    digest = hashlib.sha256()
    size = 0
    with urllib.request.urlopen(request, timeout=300) as response, output.open('wb') as target:
        final = urllib.parse.urlparse(response.geturl())
        if final.scheme != 'https' or final.hostname not in ALLOWED_DOWNLOAD_HOSTS:
            raise ModpackError('A package download redirected to an untrusted address.')
        while block := response.read(256 * 1024):
            size += len(block)
            if size > MAX_DOWNLOAD:
                raise ModpackError('A mod package is larger than the installer limit (300 MB).')
            target.write(block)
            digest.update(block)
    return digest.hexdigest()


def _safe_zip_path(name: str) -> tuple[str, ...]:
    # Packages built on Windows may use backslashes as separators
    # (e.g. Jotunn 2.30.2 ships "plugins\\Jotunn.dll"); treat them as folders.
    raw = PurePosixPath(name.replace('\\', '/'))
    if raw.is_absolute() or '..' in raw.parts or not raw.parts or ':' in raw.parts[0]:
        raise ModpackError(f'Unsafe file path in a mod package: {name[:100]}')
    return raw.parts


def _destination(parts: tuple[str, ...], package_id: str, *, is_pack: bool,
                 keep_folders: bool = False) -> tuple[str, Path] | None:
    if len(parts) == 1 and parts[0].lower() in DOCS:
        return None
    if parts[0] == 'BepInEx':
        parts = parts[1:]
    if not parts:
        return None
    kind = parts[0].lower()
    if kind in {'plugins', 'patchers', 'config', 'core', 'monomod'}:
        rest = parts[1:]
        if not rest:
            return None
        if kind in {'plugins', 'patchers'} and rest[0] == package_id:
            rest = rest[1:]
        if not rest:
            return None
        if kind in {'config', 'core', 'monomod'}:
            return kind, Path(*rest)
        if keep_folders and len(rest) > 1:
            # A bundled mod keeps its own folder (plugins/<Mod>/...), so each
            # private mod stays separate and can later be updated on its own.
            return kind, Path(*rest)
        return kind, Path(package_id, *rest)
    # Thunderstore treats regular package files as plugin contents.
    return 'plugins', Path(package_id, *parts)


def extract_package(archive: Path, stage: Path, package_id: str, *, is_pack: bool,
                    version: str | None = None, config_only: bool = False,
                    keep_folders: bool = False) -> list[tuple[str, Path]]:
    """Unpack one package into a private staging tree, rejecting unsafe ZIPs."""
    if not zipfile.is_zipfile(archive):
        raise ModpackError(f'{package_id} was not a ZIP package.')
    written = []
    with zipfile.ZipFile(archive) as bundle:
        members = bundle.infolist()
        if len(members) > 3000 or sum(m.file_size for m in members) > MAX_UNCOMPRESSED:
            raise ModpackError(f'{package_id} contains too many files or too much data.')
        try:
            manifest = json.loads(bundle.read('manifest.json').decode('utf-8-sig'))
        except (KeyError, ValueError) as exc:
            raise ModpackError(f'{package_id} is missing a valid manifest.json.') from exc
        if version and manifest.get('version_number') != version:
            raise ModpackError(f'{package_id} download has a different version than requested.')
        for member in members:
            parts = _safe_zip_path(member.filename)
            if stat.S_ISLNK(member.external_attr >> 16):
                raise ModpackError(f'{package_id} contains a symbolic link.')
            if member.is_dir():
                continue
            location = _destination(parts, package_id, is_pack=is_pack, keep_folders=keep_folders)
            if location is None:
                continue
            kind, relative = location
            if config_only and kind != 'config':
                continue
            target = stage / kind / relative
            if target.exists() and not (is_pack and kind == 'config'):
                raise ModpackError(f'Two mod files target the same path: {kind}/{relative}.')
            target.parent.mkdir(parents=True, exist_ok=True)
            with bundle.open(member) as source, target.open('wb') as output:
                shutil.copyfileobj(source, output, 256 * 1024)
            written.append((kind, relative))
    return written


def install(package: str, game_files: Path, persistent_config: Path,
            report: Callable[[str], None], uid: int, gid: int) -> dict:
    """Install the pinned dependency closure and write the panel's lock file."""
    local = read_local_pack(Path(package)) if is_local_pack(package) else None
    packages, skipped = resolve(package, local=local)
    report(f'Resolved {len(packages)} packages; skipped {len(skipped)} client-only packages.')
    root_id = f"{local['owner']}-{local['name']}" if local else package.replace('/', '-')
    hashes = {}
    bundled: dict[str, str] = {}
    with tempfile.TemporaryDirectory(prefix='heimdall-modpack-') as temp:
        temporary = Path(temp)
        stage = temporary / 'stage'
        for index, item in enumerate(packages, 1):
            if local and item.package_id == root_id:
                report(f'[{index}/{len(packages)}] Unpacking bundled files from {local["path"].name}…')
                archive = local['path']
                hashes[item.package_id] = hashlib.sha256(archive.read_bytes()).hexdigest()
                written = extract_package(archive, stage, item.package_id, is_pack=True,
                                          version=item.version, keep_folders=True)
                for kind, relative in written:
                    if kind != 'config':
                        digest = hashlib.sha256((stage / kind / relative).read_bytes()).hexdigest()
                        bundled[f'{kind}/{relative.as_posix()}'] = digest
                        if relative.suffix.lower() == '.dll':
                            report(f'Bundled code: {kind}/{relative.as_posix()} sha256 {digest[:16]}')
                continue
            report(f'[{index}/{len(packages)}] Downloading {item.package_id} {item.version}…')
            archive = temporary / f'{index}.zip'
            hashes[item.package_id] = download(item.download_url, archive)
            extract_package(archive, stage, item.package_id, is_pack=item.package_id == root_id,
                            version=item.version,
                            config_only=item.package_id == root_id and item.client_only)
        for kind in ('core', 'monomod'):
            from_root = stage / kind
            if from_root.exists():
                for source in from_root.rglob('*'):
                    if source.is_file() and (game_files / 'BepInEx' / kind / source.relative_to(from_root)).exists():
                        raise ModpackError(f'A package would overwrite a BepInEx {kind} file: {source.name}.')
        for kind in ('plugins', 'patchers', 'config', 'core', 'monomod'):
            from_root = stage / kind
            if not from_root.exists():
                continue
            into = persistent_config if kind == 'config' else game_files / 'BepInEx' / kind
            for source in from_root.rglob('*'):
                if source.is_dir():
                    continue
                relative = source.relative_to(from_root)
                target = into / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                if kind == 'config' and target.exists():
                    continue  # preserve an operator's existing configuration
                shutil.copy2(source, target)
                os.chown(target, uid, gid)
                target.chmod(0o644)
    lock = {'modpack': f"{local['owner']}/{local['name']}" if local else package,
            'packages': {item.package_id: {
        'version': item.version, 'sha256_zip': hashes[item.package_id],
        'deps': list(item.dependencies), 'tipo': ['modpack' if item.package_id == root_id else 'plugin'],
        'source': item.source} for item in packages}, 'skipped_client_only': skipped}
    if local:
        lock['modpack_file'] = local['path'].name
        lock['packages'][root_id]['files'] = bundled
    lock_path = game_files / 'mods.lock.json'
    staged = lock_path.with_name('.mods.lock.json.heimdall')
    staged.write_text(json.dumps(lock, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    os.chown(staged, uid, gid)
    staged.chmod(0o640)
    os.replace(staged, lock_path)
    report(f'Modpack installed: {len(packages)} packages. Client-only skipped: {", ".join(skipped) or "none"}.')
    return lock
