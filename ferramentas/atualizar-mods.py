#!/usr/bin/python3
"""Atualiza pacotes ja instalados, numa unica parada com backup verificado.

Diferente do instalar-mods.py, aqui a pasta antiga do plugin e substituida. Os
arquivos de config existentes NUNCA sao sobrescritos — varios pacotes trazem uma
pasta config/ com os padroes, e ela so serve para a primeira instalacao.
"""
import datetime, fcntl, grp, hashlib, json, os, pwd, shutil, stat, subprocess, sys, tarfile, time, zipfile
from pathlib import Path
SERVICE = os.environ.get('HEIMDALL_GAME_SERVICE', 'heimdall-valheim')

BASE = Path(os.environ.get('HEIMDALL_DATA_DIR', str(Path(__file__).resolve().parent.parent / 'dados')))
ROOT = Path(os.environ.get('HEIMDALL_VALHEIM_DIR', '/srv/valheim'))
DOCS = {'manifest.json','icon.png','readme.md','changelog.md','license.md','license.txt'}
def run(*a): return subprocess.run(a, check=True, capture_output=True, text=True).stdout

def estado_do_servico(nome=SERVICE):
    """O estado, sem explodir. 'systemctl is-active' sai com codigo 3 quando o
    servico esta parado, e o nosso run() usa check=True — entao perguntar o
    estado com ele derrubava o script justamente quando o servidor ja estava
    desligado de proposito."""
    return subprocess.run(['systemctl', 'is-active', nome],
                          capture_output=True, text=True).stdout.strip()



alvos = [a.split('=') for a in sys.argv[1:]]           # Pasta=versao
if not alvos: raise SystemExit(__doc__)

release = (ROOT/'current').resolve(strict=True)
lock_rel = release/'mods.lock.json'; lock = json.loads(lock_rel.read_text())

carga, registros, pulados = {}, {}, []
for pasta, nova in alvos:
    zpath = BASE/'downloads'/f'{pasta}-{nova}.zip'
    atual = lock['packages'].get(pasta, {}).get('version', '?')
    sha = hashlib.sha256(zpath.read_bytes()).hexdigest()
    with zipfile.ZipFile(zpath) as z:
        assert z.testzip() is None, zpath.name
        man = json.loads(z.read('manifest.json'))
        assert man['version_number'] == nova
        for info in z.infolist():
            p = Path(info.filename.replace('\\','/'))
            assert not p.is_absolute() and '..' not in p.parts, p
            assert not stat.S_ISLNK(info.external_attr >> 16), p
            if info.is_dir(): continue
            partes = p.parts
            if partes[0] == 'BepInEx': partes = partes[1:]
            if partes[0] == 'plugins':
                resto = partes[2:] if len(partes) > 2 and partes[1] == pasta else partes[1:]
                destino = release/'BepInEx/plugins'/pasta/Path(*resto)
            elif partes[0] == 'patchers':
                destino = release/'BepInEx/patchers'/pasta/Path(*partes[1:])
            elif partes[0] == 'config':
                destino = release/'BepInEx/config'/Path(*partes[1:])
                if destino.exists(): pulados.append(destino.name); continue
            elif p.name.lower() in DOCS:
                destino = release/'package-docs'/pasta/p.name
            else:
                destino = release/'BepInEx/plugins'/pasta/p.name
            carga[destino] = z.read(info)
    registros[pasta] = {'de': atual, 'version': nova, 'sha256_zip': sha,
                        'deps': man.get('dependencies', []), 'tipo': ['plugin']}
    print(f'  {pasta:34s} {atual:>9s} -> {nova:<9s} sha {sha[:12]}')
if pulados: print(f'  configs preservadas (nao sobrescritas): {sorted(set(pulados))}')

trava = open('/run/lock/heimdall-maintenance.lock','w')
fcntl.flock(trava, fcntl.LOCK_EX | fcntl.LOCK_NB)
# Servidor ja parado nao e erro: e o jeito mais seguro de instalar. O que
# nao se pode fazer e LIGAR um servidor que o operador desligou — por isso
# o 'finally' la embaixo so religa se tiver sido este script a parar.
ativo_antes = estado_do_servico() == 'active'
if not ativo_antes:
    print('servidor ja estava parado; instalo assim e deixo como encontrei')
carimbo = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
backup = ROOT/'backups'/f'{carimbo}-atualizacao.tar.gz'
marca = time.time()-2; parado=False; guardadas={}
try:
    if ativo_antes:
        run('systemctl','stop',SERVICE); parado=True
    assert subprocess.run(['systemctl','is-active','--quiet',SERVICE]).returncode!=0
    # O que precisa ser verdade e que a ultima geracao do mundo esteja COMPLETA,
    # nao que ela seja nova. Com o servidor vazio o relogio do Valheim fica parado
    # (ZNet.UpdateNetTime so anda com jogador conectado), entao nada muda e o
    # desligamento nao escreve save novo; e se o servidor ja estava parado, nem
    # desligamento houve. Exigir marcador novo reprovava um mundo integro.
    # Continuamos recusando save truncado: o .db2 mais recente tem de ter o seu .ok.
    mundos = ROOT/'saves/worlds_local'
    dbs = sorted(mundos.rglob('_main.*.db2'), key=lambda p: p.stat().st_mtime)
    assert dbs, 'nenhum mundo em saves/worlds_local'
    atual = dbs[-1]
    ok = atual.with_suffix('.ok')
    assert ok.exists(), f'save incompleto: {atual.name} sem marcador .ok'
    novos = [p for p in mundos.rglob('*.ok') if p.stat().st_mtime >= marca]
    if novos:
        print(f'\nmundo salvo agora: {[p.name for p in novos]}')
    else:
        idade = (time.time() - ok.stat().st_mtime)/60
        print(f'\nmundo integro em {atual.name} (marcador de {idade:.0f} min atras); '
              f'sem save novo porque nada mudou')
    with tarfile.open(backup,'w:gz') as tar:
        for item in ['saves','config','server.env','run.sh']: tar.add(ROOT/item, arcname=item)
        tar.add(lock_rel, arcname='release/mods.lock.json')
        tar.add(f'/etc/systemd/system/{SERVICE}.service', arcname=f'service/{SERVICE}.service')
        for pasta,_ in alvos:
            for sub in ('BepInEx/plugins','BepInEx/patchers','package-docs'):
                d = release/sub/pasta
                if d.is_dir(): tar.add(d, arcname=f'release/{sub}/{pasta}')
    os.chmod(backup,0o600)
    with tarfile.open(backup) as tar: nomes=tar.getnames()
    assert 'server.env' in nomes and 'release/mods.lock.json' in nomes
    print(f'backup verificado: {backup} ({backup.stat().st_size/1048576:.1f} MB, {len(nomes)} itens)')

    # a pasta antiga sai inteira: versao nova pode ter menos arquivos que a velha
    for pasta,_ in alvos:
        for sub in ('BepInEx/plugins','BepInEx/patchers'):
            d = release/sub/pasta
            if d.is_dir():
                guardadas[d] = Path(str(d)+'.antiga'); shutil.move(str(d), str(guardadas[d]))
    uid,gid = pwd.getpwnam('valheim').pw_uid, grp.getgrnam('valheim').gr_gid
    for destino,dados in carga.items():
        destino.parent.mkdir(parents=True, exist_ok=True)
        os.chown(destino.parent,uid,gid); os.chmod(destino.parent,0o755)
        destino.write_bytes(dados); os.chown(destino,uid,gid); os.chmod(destino,0o644)
    for pasta,_ in alvos:
        reg = registros[pasta]
        reg['dlls'] = sorted(d.name for d in carga if d.suffix=='.dll' and d.parent.name==pasta)
        antiga = lock['packages'].get(pasta, {})
        for k in ('site','origem_versao'):
            if k in antiga: reg[k] = antiga[k]
        lock['packages'][pasta] = reg
    lock_rel.write_text(json.dumps(lock,indent=2,sort_keys=True)+'\n'); os.chown(lock_rel,uid,gid)
    for d in guardadas.values(): shutil.rmtree(d)
    print(f'atualizado; {len(lock["packages"])} pacotes no lock')
except BaseException as e:
    for d,antiga in guardadas.items():
        if d.is_dir(): shutil.rmtree(d)
        if antiga.exists(): shutil.move(str(antiga), str(d))
    print(f'\nFALHOU, revertido: {e!r}'); raise
finally:
    if parado: run('systemctl','start',SERVICE); print('servidor religado')
