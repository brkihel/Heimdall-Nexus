#!/usr/bin/python3
"""Consistent local backup; immutable release referenced by absolute path."""
import datetime,fcntl,hashlib,json,os,pathlib,subprocess,tarfile,time
root=pathlib.Path(os.environ.get('HEIMDALL_VALHEIM_DIR','/srv/valheim'))
service_name=os.environ.get('HEIMDALL_GAME_SERVICE') or 'heimdall-valheim'
service_file=pathlib.Path(os.environ.get('HEIMDALL_GAME_SERVICE_FILE',f'/etc/systemd/system/{service_name}.service'))
lock=open(os.environ.get('HEIMDALL_MAINTENANCE_LOCK','/run/lock/heimdall-maintenance.lock'),'w');fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
def run(*args): return subprocess.run(args,check=True,text=True,capture_output=True).stdout.strip()
active=subprocess.run(['systemctl','is-active','--quiet',service_name]).returncode==0
if active:
 mark=time.time()-5
 subprocess.run(['systemctl','stop',service_name],check=False,capture_output=True)
 if subprocess.run(['systemctl','is-active','--quiet',service_name]).returncode==0:
  raise SystemExit('Service still running after stop; refusing backup.')
 # O que importa nao e o Result do systemd (o plugin ServerRestart encerra o
 # processo a forca depois de salvar, o que reporta Result=signal), e sim se o
 # mundo foi gravado. O marcador .ok so aparece quando a escrita conclui.
 worlds=root/'saves'/'worlds_local'
 oks=[f for f in worlds.rglob('*.ok') if f.stat().st_mtime>=mark] if worlds.is_dir() else []
 if not oks:
  raise SystemExit('World not saved on shutdown (no fresh .ok marker); refusing backup.')
 print('mundo salvo:',', '.join(sorted(f.name for f in oks)))
try:
 release=(root/'current').resolve(strict=True)
 stamp=datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
 metadata={'release':str(release),'created_utc':stamp,'service_was_active':active}
 out=root/'backups'/f'{stamp}.tar.gz';tmp=out.with_suffix('.partial')
 metadata_path=root/'backup-metadata.json';metadata_path.write_text(json.dumps(metadata,indent=2))
 with tarfile.open(tmp,'w:gz') as tar:
  for name in ['saves','config','backup-metadata.json']:
   tar.add(root/name,arcname=name)
  tar.add(release/'mods.lock.json',arcname='mods.lock.json')
  tar.add(release/'steamapps/appmanifest_896660.acf',arcname='appmanifest_896660.acf')
  if service_file.is_file(): tar.add(service_file,arcname=f'service/{service_name}.service')
  for item in ('run.sh','server.env'):
   if (root/item).is_file(): tar.add(root/item,arcname=f'service/{item}')
 with tarfile.open(tmp) as tar:
  for item in tar:
   if item.isfile():
    f=tar.extractfile(item)
    while f.read(1024*1024): pass
 tmp.replace(out);os.chmod(out,0o600)
 digest=hashlib.file_digest(out.open('rb'),'sha256').hexdigest()
 out.with_suffix(out.suffix+'.sha256').write_text(f'{digest}  {out.name}\n')
 print(out)
finally:
 print('servidor permanece parado; inicie-o pelo painel quando quiser')
