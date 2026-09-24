#!/usr/bin/env bash
set -Eeuo pipefail

# Progress and error codes for Jarl > Sobre e atualizações (codigos.py).
STEP_CODE=HN-UPD-100
TOTAL_STEPS=7
step() { STEP_CODE="$3"; echo "::heimdall step $1/$TOTAL_STEPS $3 $2"; }
fail() { echo "::heimdall fail $1 $2" >&2; exit 1; }
trap 'echo "::heimdall fail $STEP_CODE line $LINENO" >&2' ERR

# Update an installed Heimdall Nexus from this Git checkout:
#   cd ~/Heimdall-Nexus && git pull --ff-only && sudo ./deploy/update.sh
#
# It replaces the service code in /opt/heimdall-nexus, refreshes the site's
# helper scripts, republishes the site and restarts the panel. The game, its
# worlds, mods and settings, and your site content (pages, identity, colors)
# are not touched. The Valheim server is not restarted.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
RUNTIME=/opt/heimdall-nexus
ENV_FILE=/etc/heimdall-nexus/heimdall.env

if ((EUID != 0)); then echo "Run with sudo." >&2; fail HN-UPD-100 not-root; fi
if [[ ! -f /var/lib/heimdall-nexus/installed.json || ! -f "$RUNTIME/.heimdall-nexus-runtime" ]]; then
  echo "No finished Heimdall Nexus installation here. Use ./deploy/install.sh instead." >&2
  fail HN-UPD-100 not-installed
fi
if [[ "$(realpath "$ROOT")" == "$(realpath "$RUNTIME")" ]]; then
  echo "Run this from your Git checkout, not from $RUNTIME." >&2
  fail HN-UPD-100 runtime-dir
fi
PANEL_OS_USER="$(head -n1 /etc/heimdall-nexus/panel-os-user)"
SITE_DIR="$(sed -n 's/^HEIMDALL_SITE_DIR=//p' "$ENV_FILE" | tail -n1)"
WEB_ROOT="$(sed -n 's/^HEIMDALL_WEB_DIR=//p' "$ENV_FILE" | tail -n1)"
SITE_DIR="${SITE_DIR:-/var/lib/heimdall-nexus/site}"
WEB_ROOT="${WEB_ROOT:-/srv/heimdall-web}"

step 1 code HN-UPD-101
echo "Updating service code in $RUNTIME…"
for part in deploy servicos/painel ferramentas site/web; do
  mkdir -p "$RUNTIME/$part"
  rsync -a --delete --chown=root:root --exclude='.git/' --exclude='.venv/' --exclude='__pycache__/' \
    --exclude='*.pyc' --exclude='*.bak*' --exclude='assets/mods/' "$ROOT/$part/" "$RUNTIME/$part/"
done
find "$RUNTIME/deploy" "$RUNTIME/ferramentas" "$RUNTIME/site" -type d -exec chmod 0755 {} +

step 2 libraries HN-UPD-102
echo "Updating panel libraries…"
"$RUNTIME/servicos/painel/.venv/bin/pip" install --quiet -r "$RUNTIME/deploy/requirements-panel.txt"
chown -R root:"$PANEL_OS_USER" "$RUNTIME/servicos/painel"
chmod -R g+rX,g-w,o-rwx "$RUNTIME/servicos/painel"

step 3 sagas-services HN-UPD-103
if systemctl is-enabled --quiet heimdall-sagas-ingest.timer 2>/dev/null; then
  python3 - "$RUNTIME" "$PANEL_OS_USER" <<'PY'
from pathlib import Path
import sys
root, panel = sys.argv[1:]
for name in ('heimdall-sagas-ingest.service', 'heimdall-sagas-ingest.timer',
             'heimdall-sagas-story.service', 'heimdall-sagas-story.timer'):
    text = (Path(root) / 'deploy/systemd' / name).read_text()
    text = text.replace('@ROOT@', root).replace('@PANEL_OS_USER@', panel)
    target = Path('/etc/systemd/system') / name
    target.write_text(text)
    target.chmod(0o644)
PY
  systemctl daemon-reload
  systemctl restart heimdall-sagas-ingest.timer
  systemctl enable --now heimdall-sagas-story.timer
fi

step 4 site-helpers HN-UPD-104
echo "Updating site helpers (your pages and identity stay as they are)…"
for helper in publicar.py values.py sync_modpack.py identidade.py; do
  install -D -m 0640 -o root -g "$PANEL_OS_USER" "$RUNTIME/site/web/$helper" "$SITE_DIR/$helper"
done
for asset in vivo.js modpack.js mod-placeholder.svg; do
  install -D -m 0640 -o root -g "$PANEL_OS_USER" "$RUNTIME/site/web/assets/$asset" "$SITE_DIR/assets/$asset"
done
for font in "$RUNTIME"/site/web/assets/fontes/*; do
  install -D -m 0640 -o root -g "$PANEL_OS_USER" "$font" "$SITE_DIR/assets/fontes/$(basename "$font")"
done
for template in "$RUNTIME"/site/web/modelos-pagina/*.html; do
  target="$SITE_DIR/modelos-pagina/$(basename "$template")"
  [[ -e "$target" ]] || install -D -m 0640 -o root -g "$PANEL_OS_USER" "$template" "$target"
done
[[ -e "$SITE_DIR/marca/favicon.svg" ]] || \
  install -D -m 0640 -o root -g "$PANEL_OS_USER" "$RUNTIME/site/web/marca/favicon.svg" "$SITE_DIR/marca/favicon.svg"
[[ -e "$SITE_DIR/identidade.json" ]] || \
  install -D -m 0640 -o root -g "$PANEL_OS_USER" "$RUNTIME/site/web/identidade.json" "$SITE_DIR/identidade.json"
install -D -m 0640 -o root -g "$PANEL_OS_USER" "$RUNTIME/site/web/cronicas.html" "$SITE_DIR/cronicas.html"

step 5 publish HN-UPD-105
echo "Publishing the site…"
HEIMDALL_WEB_DIR="$WEB_ROOT" HEIMDALL_WEB_USER=www-data HEIMDALL_WEB_BACKUP_DIR=/var/backups/heimdall-web \
  HEIMDALL_SITE_DIR="$SITE_DIR" python3 "$SITE_DIR/publicar.py" vivo modpack-ui fontes cronicas tema marca sitemap robots

step 6 bridge-and-version HN-UPD-106
GAME_DIR="$(sed -n 's/^HEIMDALL_VALHEIM_DIR=//p' "$ENV_FILE" | tail -n1)"
GAME_DIR="${GAME_DIR:-/srv/valheim}"
BRIDGE="$GAME_DIR/current/BepInEx/plugins/HeimdallSagas/HeimdallSagas.Bridge.dll"
BRIDGE_UPDATED=false
if [[ -f "$BRIDGE" && ! -L "$BRIDGE" && -f "$ROOT/dist/sagas/HeimdallSagas.Bridge.dll" ]] && \
    ! cmp -s "$ROOT/dist/sagas/HeimdallSagas.Bridge.dll" "$BRIDGE"; then
  echo "Updating the Heimdall Sagas bridge (restart Valheim to load it)…"
  install -m 0644 -o root -g "$(stat -c %G "$BRIDGE")" "$ROOT/dist/sagas/HeimdallSagas.Bridge.dll" "$BRIDGE.new"
  mv -f "$BRIDGE.new" "$BRIDGE"
  BRIDGE_UPDATED=true
fi

STEP_CODE=HN-UPD-107
# Record what is installed, for Jarl > Sobre.
python3 - "$ROOT" "$RUNTIME" "$BRIDGE_UPDATED" "${HEIMDALL_UPDATE_BRANCH:-}" <<'PY'
import json, os, subprocess, sys, time
from pathlib import Path
root, runtime, bridge, branch = sys.argv[1:]
def git(*args):
    try:
        return subprocess.run(['git', '-c', f'safe.directory={root}', '-C', root, *args],
                              capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        return ''
commit = git('rev-parse', 'HEAD')
branch = branch or git('rev-parse', '--abbrev-ref', 'HEAD')
info = {'commit': commit, 'short': commit[:7], 'subject': git('log', '-1', '--format=%s')[:200],
        'date': int(git('log', '-1', '--format=%ct') or 0), 'branch': '' if branch == 'HEAD' else branch,
        'updated_at': int(time.time()), 'bridge_updated': bridge == 'true',
        'from_panel': root == '/var/lib/heimdall-nexus/source'}
target = Path(runtime) / '.heimdall-version.json'
target.write_text(json.dumps(info, ensure_ascii=False) + '\n')
os.chmod(target, 0o644)
PY

step 7 restart-panel HN-UPD-108
echo "Restarting the panel…"
systemctl restart heimdall-executor.service heimdall-panel.service
for _ in $(seq 1 20); do
  if systemctl is-active --quiet heimdall-panel.service; then break; fi
  sleep 1
done
systemctl is-active --quiet heimdall-executor.service heimdall-panel.service
echo "Heimdall Nexus updated to $(git -c safe.directory="$ROOT" -C "$ROOT" log -1 --format='%h %s' 2>/dev/null || echo 'this checkout')."
echo "The Valheim server was not restarted."
echo "::heimdall done"
