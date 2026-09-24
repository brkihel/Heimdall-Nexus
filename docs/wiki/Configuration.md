# Configuration

[Português](pt-BR/Configuracao.md) · [Wiki home](Home.md)

## Game and panel

The installer writes launch settings to /srv/valheim/server.env and creates heimdall-valheim.service. The panel uses that service to start/stop Valheim. The world is stored under /srv/valheim/saves, separately from SteamCMD updates. The host settings for website, panel and collectors are in /etc/heimdall-nexus/heimdall.env. Panel credentials live separately in /etc/heimdall-panel/config.json.

If the server accepts players but does not answer the local UDP status query (A2S), the panel uses `Game server connected` from the current service invocation to mark it ready. The player count then remains unavailable (`—`), and the world clock shows the last save without claiming that nobody is playing. You can view the game password locally with `sudo grep '^VH_PASSWORD=' /srv/valheim/server.env`; do not share its output.

Use the panel for normal operation. If you change a system setting by hand, restart only the affected web service or collector. A future upgrade must preserve the instance data paths.

## Live data

The browser editor offers draggable live values. Basic server, player and world data can be enabled on a vanilla server. Seasons and saga need the matching mod or source. An unavailable value displays a placeholder; select only groups that make sense for your host. The selected groups are recorded in the public /api/features.json.

## Modpack list

The home page reads mods.json. When a Hexium pack is selected, the installer imports its site list. The separate server-install choice downloads the package and its pinned dependencies into BepInEx, skipping packages explicitly labeled client-only. The panel reads the resulting mods.lock.json. Some mods need additional server configuration. To review a later **site list** update before applying it:

~~~bash
sudo python3 /var/lib/heimdall-nexus/site/sync_modpack.py --config /etc/heimdall-nexus/modpack.json
~~~

After reviewing the diff, add --apply and publish the mods data from the panel. Manual descriptions are preserved through the configured overrides file. You may also maintain the list manually.

## Content

A new site starts with placeholder text, the Heimdall favicon and a neutral palette. Set its identity in **Aparência** and its text in the [visual editor](Editor.md). Page publishing does not run page generators.
