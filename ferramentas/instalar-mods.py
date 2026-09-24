#!/usr/bin/python3
"""Instala um ou mais pacotes no servidor, numa unica janela de parada.

Generalizacao do instalar-explorerbiomecompat.py: trava de manutencao, mundo
salvo e conferido antes do backup, instalacao, e reversao dos arquivos escritos
se qualquer etapa falhar.

Uso: instalar-mods.py <Pasta-Do-Pacote>=<arquivo.zip> [...]
"""
import datetime, fcntl, grp, hashlib, json, os, pwd, stat, subprocess, sys, tarfile, time, zipfile
from pathlib import Path
SERVICE = os.environ.get('HEIMDALL_GAME_SERVICE', 'heimdall-valheim')

BASE = Path(os.environ.get('HEIMDALL_DATA_DIR', str(Path(__file__).resolve().parent.parent / 'dados')))
ROOT = Path(os.environ.get('HEIMDALL_VALHEIM_DIR', '/srv/valheim'))
DOCS = {'manifest.json', 'icon.png', 'readme.md', 'changelog.md', 'license.md', 'license.txt'}

def run(*a): return subprocess.run(a, check=True, capture_output=True, text=True).stdout

def estado_do_servico(nome=SERVICE):
    """O estado, sem explodir. 'systemctl is-active' sai com codigo 3 quando o
    servico esta parado, e o nosso run() usa check=True — entao perguntar o
    estado com ele derrubava o script justamente quando o servidor ja estava
    desligado de proposito."""
    return subprocess.run(['systemctl', 'is-active', nome],
                          capture_output=True, text=True).stdout.strip()



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

trava = open('/run/lock/heimdall-maintenance.lock', 'w')
fcntl.flock(trava, fcntl.LOCK_EX | fcntl.LOCK_NB)
# Servidor ja parado nao e erro: e o jeito mais seguro de instalar. O que
# nao se pode fazer e LIGAR um servidor que o operador desligou — por isso
# o 'finally' la embaixo so religa se tiver sido este script a parar.
ativo_antes = estado_do_servico() == 'active'
if not ativo_antes:
    print('servidor ja estava parado; instalo assim e deixo como encontrei')
carimbo = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
backup = ROOT / 'backups' / f'{carimbo}-instalacao.tar.gz'
marca = time.time() - 2
parado, escritos = False, []
try:
    if ativo_antes:
        run('systemctl', 'stop', SERVICE); parado = True
    assert subprocess.run(['systemctl', 'is-active', '--quiet', SERVICE]).returncode != 0
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
        tar.add(f'/etc/systemd/system/{SERVICE}.service', arcname=f'service/{SERVICE}.service')
        if (release / 'BepInEx/LogOutput.log').is_file():
            tar.add(release / 'BepInEx/LogOutput.log', arcname='antes-da-instalacao.log')
    os.chmod(backup, 0o600)
    with tarfile.open(backup) as tar: nomes = tar.getnames()
    assert 'release/mods.lock.json' in nomes and 'server.env' in nomes
    print(f'backup verificado: {backup} ({backup.stat().st_size/1048576:.1f} MB, {len(nomes)} itens)')

    uid, gid = pwd.getpwnam('valheim').pw_uid, grp.getgrnam('valheim').gr_gid
    for destino, dados in carga.items():
        destino.parent.mkdir(parents=True, exist_ok=True)
        os.chown(destino.parent, uid, gid); os.chmod(destino.parent, 0o755)
        destino.write_bytes(dados); os.chown(destino, uid, gid); os.chmod(destino, 0o644)
        escritos.append(destino)
    for pasta, reg in registros.items():
        reg['dlls'] = sorted(d.name for d in escritos
                             if d.suffix == '.dll' and d.parent.name == pasta)
        lock['packages'][pasta] = reg
    lock_rel.write_text(json.dumps(lock, indent=2, sort_keys=True) + '\n')
    os.chown(lock_rel, uid, gid)
    print(f'instalado; mods.lock.json agora com {len(lock["packages"])} pacotes')
except BaseException as e:
    for d in escritos:
        d.unlink(missing_ok=True)
        if d.parent.is_dir() and not any(d.parent.iterdir()): d.parent.rmdir()
    print(f'\nFALHOU, arquivos revertidos: {e!r}'); raise
finally:
    if parado:
        run('systemctl', 'start', SERVICE); print('servidor religado')
