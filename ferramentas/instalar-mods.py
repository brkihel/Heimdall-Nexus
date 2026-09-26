#!/usr/bin/python3
"""Instala um ou mais pacotes no servidor, numa unica janela de parada.

Generalizacao do instalar-explorerbiomecompat.py: trava de manutencao, mundo
salvo e conferido antes do backup, instalacao, e reversao dos arquivos escritos
se qualquer etapa falhar.

Uso: instalar-mods.py <Pasta-Do-Pacote>=<arquivo.zip> [...]
"""
import datetime, hashlib, json, os, stat, subprocess, sys, tarfile, time, zipfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'servicos' / 'painel'))
import hostos  # noqa: E402
SERVICE = os.environ.get('HEIMDALL_GAME_SERVICE', 'heimdall-valheim')

BASE = Path(os.environ.get('HEIMDALL_DATA_DIR', str(Path(__file__).resolve().parent.parent / 'dados')))
ROOT = hostos.env_path('HEIMDALL_VALHEIM_DIR')
DOCS = {'manifest.json', 'icon.png', 'readme.md', 'changelog.md', 'license.md', 'license.txt'}

def run(*a): return subprocess.run(a, check=True, capture_output=True, text=True).stdout

def estado_do_servico(nome=SERVICE):
    """The state as text, without raising when the service is stopped."""
    return 'active' if hostos.service_is_active(nome) else 'inactive'



alvos = []
for arg in sys.argv[1:]:
    pasta, _, zipname = arg.partition('=')
    alvos.append((pasta, BASE / 'downloads' / zipname))
if not alvos: raise SystemExit(__doc__)

release = (ROOT / 'current').resolve(strict=True)
lock_rel = release / 'mods.lock.json'
lock = json.loads(lock_rel.read_text())

carga, registros = {}, {}
for pasta, zpath in alvos:
    sha = hashlib.sha256(zpath.read_bytes()).hexdigest()
    with zipfile.ZipFile(zpath) as z:
        assert z.testzip() is None, f'zip corrompido: {zpath.name}'
        man = json.loads(z.read('manifest.json'))
        for dep in man.get('dependencies', []):
            dn, dv = dep.rsplit('-', 1)
            atual = '5.4.2350' if dn == 'denikson-BepInExPack_Valheim' else lock['packages'][dn]['version']
            assert tuple(map(int, atual.split('.'))) >= tuple(map(int, dv.split('.'))), dep
            print(f'  {pasta}: dependencia ok -> {dep} (instalado {atual})')
        for info in z.infolist():
            p = Path(info.filename.replace('\\', '/'))
            assert not p.is_absolute() and '..' not in p.parts, p
            assert not stat.S_ISLNK(info.external_attr >> 16), p
            if info.is_dir(): continue
            partes = p.parts
            if partes[0] == 'BepInEx': partes = partes[1:]
            if partes[0] == 'plugins':
                resto = partes[2:] if len(partes) > 2 and partes[1] == pasta else partes[1:]
                destino = release / 'BepInEx/plugins' / pasta / Path(*resto)
            elif partes[0] == 'patchers':
                destino = release / 'BepInEx/patchers' / pasta / Path(*partes[1:])
            elif partes[0] == 'config':
                destino = release / 'BepInEx/config' / Path(*partes[1:])
                if destino.exists(): continue          # nunca sobrescreve config existente
            elif p.name.lower() in DOCS:
                destino = release / 'package-docs' / pasta / p.name
            else:
                destino = release / 'BepInEx/plugins' / pasta / p.name
            assert destino not in carga, destino
            carga[destino] = z.read(info)
    registros[pasta] = {'version': man['version_number'], 'sha256_zip': sha,
                        'deps': man.get('dependencies', []), 'tipo': ['plugin']}

print()
for d in sorted(carga):
    assert not d.exists(), f'ja existe, nao vou sobrescrever: {d}'
    print('  ->', d)

trava = hostos.exclusive_lock(hostos.env_path('HEIMDALL_MAINTENANCE_LOCK'))
# Maintenance leaves the game stopped until the administrator starts it.
ativo_antes = estado_do_servico() == 'active'
if not ativo_antes:
    print('servidor ja estava parado; instalo assim e deixo como encontrei')
carimbo = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
backup = ROOT / 'backups' / f'{carimbo}-instalacao.tar.gz'
marca = time.time() - 2
escritos = []
try:
    if ativo_antes:
        hostos.service_action('stop', SERVICE, timeout=300)
    assert not hostos.service_is_active(SERVICE)
    # O que precisa ser verdade e que a ultima geracao do mundo esteja COMPLETA,
    # nao que ela seja nova. Com o servidor vazio o relogio do Valheim fica
    # parado (ZNet.UpdateNetTime so anda com jogador conectado), entao nada muda
    # e o desligamento nao escreve save novo — exigir marcador novo reprovava um
    # mundo integro. Continuamos recusando save truncado: todo .db2 mais recente
    # tem de ter o seu .ok ao lado.
    mundos = (ROOT / 'saves/worlds_local')
    dbs = sorted(mundos.rglob('_main.*.db2'), key=lambda p: p.stat().st_mtime)
    # A fresh server has no saved world until its first save; then there is
    # nothing to protect beyond the configs, which the backup still carries.
    if not dbs:
        print('\nnenhum mundo salvo ainda; o backup leva configs e opcoes do servidor')
    atual = dbs[-1] if dbs else None
    ok = atual.with_suffix('.ok') if atual else None
    assert not atual or ok.exists(), f'save incompleto: {atual.name} sem marcador .ok'
    idade = time.time() - ok.stat().st_mtime if ok else 0
    novos = [p for p in mundos.rglob('*.ok') if p.stat().st_mtime >= marca] if mundos.is_dir() else []
    if not atual:
        pass
    elif novos:
        print(f'\nmundo salvo agora: {[p.name for p in novos]}')
    else:
        print(f'\nmundo integro em {atual.name} (marcador de {idade/60:.0f} min atras); '
              f'sem save novo porque nada mudou — servidor vazio, relogio parado')
    with tarfile.open(backup, 'w:gz') as tar:
        for item in ['saves', 'config', 'server.env', 'run.sh']:
            if (ROOT / item).exists():
                tar.add(ROOT / item, arcname=item)
        tar.add(lock_rel, arcname='release/mods.lock.json')
        if hostos.service_file(SERVICE).is_file(): tar.add(hostos.service_file(SERVICE), arcname=f'service/{hostos.service_file(SERVICE).name}')
        if (release / 'BepInEx/LogOutput.log').is_file():
            tar.add(release / 'BepInEx/LogOutput.log', arcname='antes-da-instalacao.log')
    os.chmod(backup, 0o600)
    with tarfile.open(backup) as tar: nomes = tar.getnames()
    assert 'release/mods.lock.json' in nomes and 'server.env' in nomes
    print(f'backup verificado: {backup} ({backup.stat().st_size/1048576:.1f} MB, {len(nomes)} itens)')

    uid, gid = hostos.account_ids('valheim') if hostos.account_exists('valheim') else (-1, -1)
    for destino, dados in carga.items():
        destino.parent.mkdir(parents=True, exist_ok=True)
        hostos.chown(destino.parent, uid, gid); os.chmod(destino.parent, 0o755)
        destino.write_bytes(dados); hostos.chown(destino, uid, gid); os.chmod(destino, 0o644)
        escritos.append(destino)
    for pasta, reg in registros.items():
        reg['dlls'] = sorted(d.name for d in escritos
                             if d.suffix == '.dll' and d.parent.name == pasta)
        lock['packages'][pasta] = reg
    lock_rel.write_text(json.dumps(lock, indent=2, sort_keys=True) + '\n')
    hostos.chown(lock_rel, uid, gid)
    print(f'instalado; mods.lock.json agora com {len(lock["packages"])} pacotes')
except BaseException as e:
    for d in escritos:
        d.unlink(missing_ok=True)
        if d.parent.is_dir() and not any(d.parent.iterdir()): d.parent.rmdir()
    print(f'\nFALHOU, arquivos revertidos: {e!r}'); raise
finally:
    print('servidor permanece parado; inicie-o pelo painel quando quiser')
