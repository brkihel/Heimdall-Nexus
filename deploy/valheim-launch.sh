#!/usr/bin/env bash
set -euo pipefail

# Loaded by systemd from /srv/valheim/server.env. Never edit Steam's
# start_server.sh: SteamCMD replaces it on update.
cd "${VH_GAMEDIR:-/srv/valheim/current}"
export SteamAppId=892970
export LD_LIBRARY_PATH="./linux64:${LD_LIBRARY_PATH:-}"

if [[ "${VH_BEPINEX:-0}" == 1 ]]; then
  if [[ ! -f ./BepInEx/core/BepInEx.Preloader.dll ]]; then
    echo 'BepInEx was selected but its preloader is missing.' >&2
    exit 1
  fi
  export DOORSTOP_ENABLED=1
  export DOORSTOP_TARGET_ASSEMBLY=./BepInEx/core/BepInEx.Preloader.dll
  export LD_LIBRARY_PATH="./doorstop_libs:$LD_LIBRARY_PATH"
  export LD_PRELOAD="libdoorstop_x64.so:${LD_PRELOAD:-}"
fi

args=(-name "${VH_NAME:?}" -port "${VH_PORT:?}" -world "${VH_WORLD:?}"
      -savedir "${VH_SAVEDIR:?}" -public "${VH_PUBLIC:-0}" -nographics -batchmode)
if [[ -n "${VH_PASSWORD:-}" ]]; then args+=(-password "$VH_PASSWORD"); fi
if [[ "${VH_CROSSPLAY:-0}" == 1 ]]; then args+=(-crossplay); fi
exec ./valheim_server.x86_64 "${args[@]}"
