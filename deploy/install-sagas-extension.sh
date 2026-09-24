#!/usr/bin/env bash
set -euo pipefail

# Installs a reviewed bridge build on an existing Heimdall Nexus host. This is
# deliberately separate from the default installer: the extension is opt-in.
if ((EUID != 0)) || [[ $# != 1 || ! -f "$1" ]]; then
  echo "Use: sudo deploy/install-sagas-extension.sh /path/to/HeimdallSagas.Bridge.dll" >&2
  exit 2
fi
bridge_dll="$(realpath "$1")"
if [[ "$(basename "$bridge_dll")" != HeimdallSagas.Bridge.dll || "$(head -c2 "$bridge_dll")" != MZ ]]; then
  echo "Expected a built HeimdallSagas.Bridge.dll." >&2
  exit 2
fi
config=/etc/heimdall-nexus/heimdall.env
if [[ ! -f "$config" || ! -f /var/lib/heimdall-nexus/installed.json ]]; then
  echo "Install Heimdall Nexus first." >&2
  exit 2
fi
getent group heimdall-sagas >/dev/null || groupadd --system heimdall-sagas
usermod -a -G heimdall-sagas valheim

python3 - "$config" "$bridge_dll" <<'PY'
import grp
import json
import os
import pathlib
import pwd
import shutil
import sys
import tempfile

env = {}
for line in pathlib.Path(sys.argv[1]).read_text().splitlines():
    if '=' in line and not line.lstrip().startswith('#'):
        key, value = line.split('=', 1)
        env[key] = value
root = pathlib.Path(env.get('HEIMDALL_ROOT', '/opt/heimdall-nexus'))
game = pathlib.Path(env.get('HEIMDALL_VALHEIM_DIR', '/srv/valheim'))
panel = env.get('HEIMDALL_PANEL_OS_USER', 'heimdall')
if not (game / 'current/BepInEx/core/BepInEx.dll').is_file():
    raise SystemExit('BepInEx must be installed on the game server first.')
if not (root / 'servicos/painel/sagas.py').is_file():
    raise SystemExit('Update the Nexus runtime before installing this extension.')
panel_id = pwd.getpwnam(panel).pw_uid
panel_group = pwd.getpwnam(panel).pw_gid
game_id = pwd.getpwnam('valheim').pw_uid
game_group = pwd.getpwnam('valheim').pw_gid
sagas_group = grp.getgrnam('heimdall-sagas').gr_gid
state = pathlib.Path('/var/lib/heimdall-nexus/sagas')
for path, owner, group, mode in (
    (state, panel_id, sagas_group, 0o710),
    (state / 'inbox', panel_id, sagas_group, 0o2770),
    (state / 'rejected', panel_id, panel_group, 0o700),
):
    path.mkdir(parents=True, exist_ok=True)
    os.chown(path, owner, group)
    os.chmod(path, mode)
settings = state / 'settings.json'
if not settings.exists():
    settings.write_text(json.dumps({'version': 1, 'enabled': True, 'gear': True,
                                    'events': True, 'clock': True,
                                    'kill_mode': 'all'}) + '\n')
os.chown(settings, panel_id, sagas_group)
os.chmod(settings, 0o640)
target = game / 'current/BepInEx/plugins/HeimdallSagas/HeimdallSagas.Bridge.dll'
for part in (game / 'current', game / 'current/BepInEx', game / 'current/BepInEx/plugins'):
    if part.is_symlink() or not part.is_dir():
        raise SystemExit(f'Unsafe game plugin directory: {part}')
if target.parent.is_symlink():
    raise SystemExit(f'Unsafe bridge directory: {target.parent}')
target.parent.mkdir(exist_ok=True, mode=0o755)
if target.is_symlink():
    raise SystemExit(f'Unsafe bridge target: {target}')
descriptor, temporary = tempfile.mkstemp(prefix='.bridge-', dir=target.parent)
try:
    with os.fdopen(descriptor, 'wb') as output, open(sys.argv[2], 'rb') as source:
        shutil.copyfileobj(source, output)
        output.flush()
        os.fsync(output.fileno())
    os.chown(temporary, 0, game_group)
    os.chmod(temporary, 0o644)
    os.replace(temporary, target)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
server_env = game / 'server.env'
if server_env.is_symlink() or not server_env.is_file():
    raise SystemExit(f'Unsafe game environment file: {server_env}')
lines = server_env.read_text().splitlines()
lines = [line for line in lines if not line.startswith(('HEIMDALL_SAGAS_INBOX=',
                                                       'HEIMDALL_SAGAS_SETTINGS='))]
lines.append('HEIMDALL_SAGAS_INBOX=/var/lib/heimdall-nexus/sagas/inbox')
lines.append('HEIMDALL_SAGAS_SETTINGS=/var/lib/heimdall-nexus/sagas/settings.json')
original = server_env.stat()
descriptor, temporary = tempfile.mkstemp(prefix='.server-env-', dir=game)
try:
    with os.fdopen(descriptor, 'w') as output:
        output.write('\n'.join(lines) + '\n')
        output.flush()
        os.fsync(output.fileno())
    os.chown(temporary, original.st_uid, original.st_gid)
    os.chmod(temporary, original.st_mode & 0o777)
    os.replace(temporary, server_env)
finally:
    if os.path.exists(temporary):
        os.unlink(temporary)
for name in ('heimdall-sagas-ingest.service', 'heimdall-sagas-ingest.timer',
             'heimdall-sagas-story.service', 'heimdall-sagas-story.timer',
             'heimdall-sagas-atlas.service', 'heimdall-sagas-atlas.timer'):
    content = (root / 'deploy/systemd' / name).read_text()
    content = content.replace('@ROOT@', str(root)).replace('@PANEL_OS_USER@', panel)
    destination = pathlib.Path('/etc/systemd/system') / name
    destination.write_text(content)
    destination.chmod(0o644)
PY

# Older installs keep their Nginx file. Add only the extension's public GET route.
nginx -t >/dev/null
python3 - <<'PY'
from pathlib import Path
path = Path('/etc/nginx/sites-available/heimdall-nexus')
text = path.read_text()
atlas_route = '''    location ^~ /api/sagas/v1/atlas/ {
        limit_except GET { deny all; }
        proxy_pass http://127.0.0.1:8791;
        proxy_set_header Host $host;
        add_header Cache-Control "no-store" always;
    }

'''
if 'location = /api/sagas/v1/overview' not in text:
    marker = '    location / {\n'
    if marker not in text:
        raise SystemExit('The Nexus Nginx configuration has an unexpected layout.')
    route = '''    location = /api/sagas/v1/overview {
        limit_except GET { deny all; }
        proxy_pass http://127.0.0.1:8791;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-Proto $scheme;
        add_header Cache-Control "no-store" always;
    }

'''
    backup = path.with_suffix('.pre-sagas')
    backup.write_text(text)
    path.write_text(text.replace(marker, route + marker, 1))
    text = path.read_text()
if 'location ^~ /api/sagas/v1/atlas/' not in text:
    marker = '    location = /api/sagas/v1/overview {'
    if marker not in text:
        raise SystemExit('The Nexus Nginx configuration has an unexpected layout.')
    backup = path.with_suffix('.pre-sagas')
    if not backup.exists():
        backup.write_text(text)
    path.write_text(text.replace(marker, atlas_route + marker, 1))
PY
if ! nginx -t; then
  if [[ -f /etc/nginx/sites-available/heimdall-nexus.pre-sagas ]]; then
    cp /etc/nginx/sites-available/heimdall-nexus.pre-sagas /etc/nginx/sites-available/heimdall-nexus
  fi
  echo "Nginx rejected the new route; restored the prior configuration." >&2
  exit 1
fi
systemctl reload nginx
systemctl daemon-reload
systemctl enable --now heimdall-sagas-ingest.timer
systemctl enable --now heimdall-sagas-story.timer heimdall-sagas-atlas.timer
echo "Heimdall Sagas extension installed. Restart Valheim when convenient to load the bridge."
