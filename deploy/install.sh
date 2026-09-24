#!/usr/bin/env bash
set -euo pipefail

# Heimdall Nexus visual bootstrap. The browser wizard listens on loopback;
# a temporary HTTPS link is attempted unless --local-only is selected.
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PORT=8765
CHECK_ONLY=0
LOCAL_ONLY=0

usage() {
  cat <<'EOF'
Heimdall Nexus — visual installer for Ubuntu/Debian

  sudo ./deploy/install.sh [--port 8765] [--local-only]
  ./deploy/install.sh --check

The wizard listens on 127.0.0.1 and tries to print a temporary Cloudflare
HTTPS link for your personal browser. No SSH tunnel or inbound firewall port
is needed. The link exists only while this process is running.

To avoid the third-party link, use --local-only and forward the port yourself:

  ssh -L 8765:127.0.0.1:8765 user@your-server

Open the URL printed in the server terminal in your local browser.
The wizard installs SteamCMD, Valheim Dedicated Server, the optional BepInEx
pack, the site and the administration panel.
EOF
}

while (($#)); do
  case "$1" in
    --port) PORT="${2:?port required}"; shift 2 ;;
    --check) CHECK_ONLY=1; shift ;;
    --local-only) LOCAL_ONLY=1; shift ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done
if [[ ! "$PORT" =~ ^[0-9]{4,5}$ ]] || ((10#$PORT < 1024 || 10#$PORT > 65535)); then
  echo "Port must be between 1024 and 65535." >&2; exit 2
fi
if [[ "$(uname -m)" != x86_64 ]]; then
  echo "Valheim's Linux dedicated server requires x86-64." >&2; exit 2
fi
if [[ ! -r /etc/os-release ]]; then echo "Could not identify this Linux distribution." >&2; exit 2; fi
. /etc/os-release
if [[ "${ID:-}" != ubuntu && "${ID:-}" != debian ]]; then
  echo "This installer supports Ubuntu and Debian; found ${PRETTY_NAME:-unknown}." >&2; exit 2
fi
if [[ -e /var/lib/heimdall-nexus/installed.json ]]; then
  echo "Heimdall Nexus is already installed on this host." >&2
  exit 2
fi
if [[ -e /etc/systemd/system/heimdall-valheim.service ]]; then
  echo "An existing unmanaged Valheim game service was found. This wizard will not replace it." >&2
  exit 2
fi
if command -v python3 >/dev/null && ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
  echo "Heimdall Nexus requires Python 3.10 or newer; found $(python3 --version 2>&1)." >&2
  exit 2
fi
if ((CHECK_ONLY)); then
  echo "Ready for visual setup: ${PRETTY_NAME}, x86-64, port $PORT. No changes made."
  exit 0
fi
if ((EUID != 0)); then echo "Run with sudo." >&2; exit 1; fi
BOOTSTRAP_PACKAGES=()
if ! command -v python3 >/dev/null; then BOOTSTRAP_PACKAGES+=(python3); fi
if ! dpkg -s ca-certificates >/dev/null 2>&1; then BOOTSTRAP_PACKAGES+=(ca-certificates); fi
if ((${#BOOTSTRAP_PACKAGES[@]})); then
  apt-get update
  DEBIAN_FRONTEND=noninteractive apt-get install -y "${BOOTSTRAP_PACKAGES[@]}"
fi
if ! python3 -c 'import sys; sys.exit(sys.version_info < (3, 10))'; then
  echo "Heimdall Nexus requires Python 3.10 or newer; found $(python3 --version 2>&1)." >&2
  exit 2
fi
ARGS=(--port "$PORT")
if ((LOCAL_ONLY)); then ARGS+=(--local-only); fi
exec python3 "$ROOT/deploy/setup_server.py" "${ARGS[@]}"
