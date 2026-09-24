# Heimdall Nexus deployment

install.sh starts the browser wizard on loopback and, by default, creates a temporary public HTTPS link with Cloudflare Quick Tunnel. Use --local-only for SSH forwarding instead. setup_server.py serves the UI; installer.py installs SteamCMD, Valheim Dedicated Server, optional BepInEx and optional Hexium modpack packages, then calls install-web.sh for the site and panel. install-web.sh is an internal phase.

The game service is `heimdall-valheim.service`; the panel, executor, status collectors and schedule timer also use `heimdall-*` systemd names. Files live under /srv/valheim/current, SteamCMD under /srv/valheim/steamcmd, and persistent worlds under /srv/valheim/saves. The game starts only when selected in the wizard.

The wizard copies service code from the checkout to /opt/heimdall-nexus before configuring systemd. Services do not depend on traversing the operator’s home directory. The wizard lets the installer choose a Linux account for the panel separately from its browser login; the game keeps its own `valheim` account. Editable content, settings and saves remain in separate paths.

The editable site lives in /var/lib/heimdall-nexus/site; settings in /etc/heimdall-nexus/heimdall.env; panel credentials in /etc/heimdall-panel/config.json; public pages in /srv/heimdall-web. Optional Hexium sync updates mods.json independently of page publishing.

For a remote host, forward port 8765 to server loopback through SSH. Read the bilingual walkthrough under docs/wiki/.
