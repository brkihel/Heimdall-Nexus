#!/usr/bin/env bash
set -euo pipefail

# Removes an installation created by the visual wizard so it can be repeated.
# It keeps the Git checkout, OS packages and the valheim account. The dedicated
# panel account is removed so the wizard can offer the same name again.
MARKER=/var/lib/heimdall-nexus/installed.json
if [[ ! -f "$MARKER" ]]; then
  echo "Installation marker not found: $MARKER. Refusing to remove anything." >&2
  exit 1
fi
if [[ "${1:-}" != --check && "${1:-}" != --purge ]]; then
  echo "Usage: sudo ./deploy/reset-vm.sh --check | --purge" >&2
  exit 2
fi
UNITS=(heimdall-valheim.service heimdall-panel.service heimdall-executor.service
       heimdall-status.service heimdall-status.timer heimdall-saga.service
       heimdall-saga.timer heimdall-schedule.service heimdall-schedule.timer)
PATHS=(/srv/valheim /srv/heimdall-web /var/lib/heimdall-nexus /var/lib/heimdall-panel
       /var/backups/heimdall-web /var/backups/heimdall-panel
       /var/log/heimdall-panel /etc/heimdall-nexus /etc/heimdall-panel
       /opt/heimdall-nexus /usr/local/lib/heimdall-nexus)
printf 'Services to stop and remove:\n'; printf '  %s\n' "${UNITS[@]}"
printf '\nApplication paths to remove, including worlds and backups:\n'; printf '  %s\n' "${PATHS[@]}"
printf '  /etc/nginx/sites-{available,enabled}/heimdall-nexus\n'
echo 'The Git checkout, apt packages and valheim account remain. The dedicated panel account is removed.'
if [[ "$1" == --check ]]; then exit 0; fi
if (( EUID != 0 )); then echo 'Run with sudo.' >&2; exit 1; fi
read -r -p 'Type RESET HEIMDALL VM to erase this installation: ' answer
if [[ "$answer" != 'RESET HEIMDALL VM' ]]; then echo 'Cancelled.'; exit 1; fi
PANEL_USER="$(python3 - "$MARKER" <<'PY'
import json,sys
print(json.load(open(sys.argv[1])).get('system_user',''))
PY
)"
for unit in "${UNITS[@]}"; do
  systemctl disable --now "$unit" >/dev/null 2>&1 || true
done
for unit in "${UNITS[@]}"; do
  rm -f "/etc/systemd/system/$unit"
done
if [[ -n "$PANEL_USER" ]] && getent passwd "$PANEL_USER" >/dev/null; then
  uid="$(id -u "$PANEL_USER")"
  shell="$(getent passwd "$PANEL_USER" | cut -d: -f7)"
  if (( uid >= 1000 )) || [[ "$shell" != /usr/sbin/nologin ]]; then
    echo "Account $PANEL_USER does not look like the dedicated panel account; refusing to remove it." >&2
    exit 1
  fi
  userdel "$PANEL_USER"
  if getent group "$PANEL_USER" >/dev/null; then groupdel "$PANEL_USER"; fi
fi
rm -f /etc/nginx/sites-enabled/heimdall-nexus /etc/nginx/sites-available/heimdall-nexus
for path in "${PATHS[@]}"; do rm -rf -- "$path"; done
systemctl daemon-reload
systemctl reset-failed >/dev/null 2>&1 || true
nginx -t && systemctl reload nginx
echo 'Application removed. Run sudo ./deploy/install.sh from the Git checkout to install again.'
