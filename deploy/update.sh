#!/usr/bin/env bash
set -euo pipefail

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

if ((EUID != 0)); then echo "Run with sudo." >&2; exit 1; fi
if [[ ! -f /var/lib/heimdall-nexus/installed.json || ! -f "$RUNTIME/.heimdall-nexus-runtime" ]]; then
  echo "No finished Heimdall Nexus installation here. Use ./deploy/install.sh instead." >&2
  exit 1
fi
if [[ "$(realpath "$ROOT")" == "$(realpath "$RUNTIME")" ]]; then
  echo "Run this from your Git checkout, not from $RUNTIME." >&2
  exit 1
fi
PANEL_OS_USER="$(head -n1 /etc/heimdall-nexus/panel-os-user)"
SITE_DIR="$(sed -n 's/^HEIMDALL_SITE_DIR=//p' "$ENV_FILE" | tail -n1)"
WEB_ROOT="$(sed -n 's/^HEIMDALL_WEB_DIR=//p' "$ENV_FILE" | tail -n1)"
SITE_DIR="${SITE_DIR:-/var/lib/heimdall-nexus/site}"
WEB_ROOT="${WEB_ROOT:-/srv/heimdall-web}"

echo "Updating service code in $RUNTIME…"
for part in deploy servicos/painel ferramentas site/web; do
  mkdir -p "$RUNTIME/$part"
  rsync -a --delete --chown=root:root --exclude='.git/' --exclude='.venv/' --exclude='__pycache__/' \
    --exclude='*.pyc' --exclude='*.bak*' --exclude='assets/mods/' "$ROOT/$part/" "$RUNTIME/$part/"
done
find "$RUNTIME/deploy" "$RUNTIME/ferramentas" "$RUNTIME/site" -type d -exec chmod 0755 {} +

echo "Updating panel libraries…"
"$RUNTIME/servicos/painel/.venv/bin/pip" install --quiet -r "$RUNTIME/deploy/requirements-panel.txt"
chown -R root:"$PANEL_OS_USER" "$RUNTIME/servicos/painel"
chmod -R g+rX,g-w,o-rwx "$RUNTIME/servicos/painel"

echo "Updating site helpers (your pages and identity stay as they are)…"
for helper in publicar.py values.py sync_modpack.py identidade.py; do
  install -D -m 0640 -o root -g "$PANEL_OS_USER" "$RUNTIME/site/web/$helper" "$SITE_DIR/$helper"
done
for asset in vivo.js modpack.js mod-placeholder.svg; do
  install -D -m 0640 -o root -g "$PANEL_OS_USER" "$RUNTIME/site/web/assets/$asset" "$SITE_DIR/assets/$asset"
done
for template in "$RUNTIME"/site/web/modelos-pagina/*.html; do
  target="$SITE_DIR/modelos-pagina/$(basename "$template")"
  [[ -e "$target" ]] || install -D -m 0640 -o root -g "$PANEL_OS_USER" "$template" "$target"
done
[[ -e "$SITE_DIR/marca/favicon.svg" ]] || \
  install -D -m 0640 -o root -g "$PANEL_OS_USER" "$RUNTIME/site/web/marca/favicon.svg" "$SITE_DIR/marca/favicon.svg"
[[ -e "$SITE_DIR/identidade.json" ]] || \
  install -D -m 0640 -o root -g "$PANEL_OS_USER" "$RUNTIME/site/web/identidade.json" "$SITE_DIR/identidade.json"

echo "Publishing the site…"
HEIMDALL_WEB_DIR="$WEB_ROOT" HEIMDALL_WEB_USER=www-data HEIMDALL_WEB_BACKUP_DIR=/var/backups/heimdall-web \
  HEIMDALL_SITE_DIR="$SITE_DIR" python3 "$SITE_DIR/publicar.py" vivo modpack-ui tema marca sitemap robots

echo "Restarting the panel…"
systemctl restart heimdall-executor.service heimdall-panel.service
for _ in $(seq 1 20); do
  if systemctl is-active --quiet heimdall-panel.service; then break; fi
  sleep 1
done
systemctl is-active --quiet heimdall-executor.service heimdall-panel.service
echo "Heimdall Nexus updated to $(git -C "$ROOT" log -1 --format='%h %s' 2>/dev/null || echo 'this checkout')."
echo "The Valheim server was not restarted."
