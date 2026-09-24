#!/usr/bin/env bash
set -euo pipefail

if [[ $# != 2 || ! -f "$1/assembly_valheim.dll" || ! -f "$1/UnityEngine.JSONSerializeModule.dll" || ! -f "$2/BepInEx.dll" ]]; then
  echo "Use: $0 GAME_MANAGED_DIR BEPINEX_CORE_DIR" >&2
  echo "Game and BepInEx assemblies are compile references; they are never packaged." >&2
  exit 2
fi
root="$(cd "$(dirname "$0")/../.." && pwd)"
game="$(realpath "$1")"
bepinex="$(realpath "$2")"
for project in Client Bridge; do
  dotnet build "$root/extensoes/sagas/mod/HeimdallSagas.$project/HeimdallSagas.$project.csproj" \
    -c Release -p:GameRefDir="$game" -p:BepInExRefDir="$bepinex"
done
python3 - "$root" <<'PY'
import json
import struct
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile
import sys

root = Path(sys.argv[1])
artifacts = root / 'artifacts/sagas'
artifacts.mkdir(parents=True, exist_ok=True)
for kind in ('Client', 'Bridge'):
    dll = root / f'extensoes/sagas/mod/HeimdallSagas.{kind}/bin/Release/net48/HeimdallSagas.{kind}.dll'
    output = artifacts / f'HeimdallSagas.{kind}-0.1.2.zip'
    with ZipFile(output, 'w', ZIP_DEFLATED) as archive:
        archive.write(dll, f'BepInEx/plugins/HeimdallSagas/HeimdallSagas.{kind}.dll')
        archive.write(root / 'extensoes/sagas/mod/README.md', 'README.md')
        if kind == 'Client':
            archive.write(root / 'extensoes/sagas/mod/manifest-client.json', 'manifest.json')
            archive.write(root / 'extensoes/sagas/mod/icon.png', 'icon.png')
    if kind == 'Client':
        with ZipFile(output) as archive:
            required = {'manifest.json', 'icon.png', 'README.md',
                        'BepInEx/plugins/HeimdallSagas/HeimdallSagas.Client.dll'}
            if not required.issubset(archive.namelist()):
                raise SystemExit('Client package is missing required Gale files.')
            manifest = json.loads(archive.read('manifest.json'))
            if manifest.get('name') != 'HeimdallSagasClient' or \
                    manifest.get('version_number') != '0.1.2':
                raise SystemExit('Client package has an unexpected identity.')
            icon = archive.read('icon.png')
            if icon[:8] != b'\x89PNG\r\n\x1a\n' or \
                    struct.unpack('>II', icon[16:24]) != (256, 256):
                raise SystemExit('Client icon must be a 256x256 PNG.')
    print(output)
PY
