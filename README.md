<div align="center">

<img src=".github/assets/banner.webp" alt="Heimdall Nexus" width="100%">

### The all-seeing guardian for your Valheim server

Install a Valheim dedicated server, a browser admin panel and a website you edit visually —<br>
from one guided wizard, on a fresh Ubuntu or Debian machine.

[**Quick start**](#quick-start) · [**Wiki**](https://github.com/brkihel/Heimdall-Nexus/wiki) · [**Leia em português**](README.pt-BR.md)

[![License](https://img.shields.io/badge/license-PolyForm%20Noncommercial-c8a45c?style=flat-square&labelColor=0d151d)](LICENSE)
[![Valheim](https://img.shields.io/badge/Valheim-dedicated%20server-c8a45c?style=flat-square&labelColor=0d151d)](https://valheim.com/support/a-guide-to-dedicated-servers/)
[![Platform](https://img.shields.io/badge/Ubuntu%20%7C%20Debian-x86--64-c8a45c?style=flat-square&labelColor=0d151d)](#quick-start)
[![Python](https://img.shields.io/badge/Python-3.10%2B-c8a45c?style=flat-square&labelColor=0d151d)](https://www.python.org/)
[![Version](https://img.shields.io/badge/version-1.0.0-c8a45c?style=flat-square&labelColor=0d151d)](CHANGELOG.md)

</div>

---

## Install it from your browser

The installer runs on your server and opens in your own browser. Five screens: site address, world and password, mods and live data, admin account, review. It downloads SteamCMD and Valheim, installs BepInEx and your modpack if you want them, and shows every step as it happens.

<img src=".github/assets/installer.webp" alt="Heimdall Nexus visual installer" width="100%">

## Run the server from one panel

Start, stop and restart the game, watch the live log, edit files and mod configs, install and update mods, wipe or swap worlds, schedule restarts and backups, and restore any backup with one click. Risky actions ask first in the panel's own dialog, and every change is recorded in an audit log.

<img src=".github/assets/panel.webp" alt="Heimdall Nexus admin panel" width="100%">

## Give your community a real website

A fast site with live server status, players online, world time and your mod list. Set your name, logo, favicon and colors in **Aparência**, and edit any page in the **Layout Editor**: click something on the page and only its tools appear, in Content, Style and Block tabs. Add pages from wiki or blank templates, and arrange the site menu by dragging. No code, no spreadsheets.

<img src=".github/assets/site.webp" alt="A community website made with Heimdall Nexus" width="100%">

<img src=".github/assets/editor.webp" alt="The Layout Editor with a text selected and its Style tools open" width="100%">

<sub>Screenshots use sample data.</sub>

## Quick start

On a fresh **Ubuntu or Debian x86-64** machine with Python 3.10+:

```bash
sudo apt update && sudo apt install -y git
git clone https://github.com/brkihel/Heimdall-Nexus.git
cd Heimdall-Nexus
sudo ./deploy/install.sh
```

The terminal prints a private link to the installer. Open it in your browser and follow the five screens.

| How to open the installer | When to use it |
|---|---|
| `install.sh` | Default. A temporary HTTPS link through Cloudflare, checked before it is shown. |
| `install.sh --direct` | A machine on a network you trust, such as a VM on your LAN. Plain HTTP link to its IP. |
| `install.sh --local-only` | No external service. Forward the port with `ssh -L 8765:127.0.0.1:8765 user@server`. |

Then sign in at `https://your-domain/jarl/entrar`. Full walkthrough: [**Installation**](https://github.com/brkihel/Heimdall-Nexus/wiki/Installation).

## Features

<table>
<tr>
<td width="50%" valign="top">

**Game server**
- Valheim Dedicated Server through SteamCMD, as a systemd service
- Optional BepInEx, with modpacks from Thunderstore or Hexium (paste the link)
- Your own `.zip` modpack with private mods
- Server Config: name, world, port, password, world modifiers, admins, allowlist and bans, with the resulting launch options on view
- World wipes with a new name, seed and modifiers, or swap in an uploaded world

</td>
<td width="50%" valign="top">

**Day to day**
- Live console, file manager, mod config editor and chat/admin logs
- Mod Manager: install, update and remove mods, with a verified backup before each change
- Update Heimdall from Jarl, with progress, error codes and stable or development channels
- Tarefas: cron schedules for restarts, starts, stops and backups
- Backups you can download, restore, lock and delete

</td>
</tr>
<tr>
<td width="50%" valign="top">

**Website**
- Live status, players, world clock and a mod list you refresh from Hexium in **Modpack**
- Layout Editor with versions, undo and shareable previews
- Name, logo, favicon, background and a global color table
- A shared menu with submenus, edited by dragging, with live preview
- Pages for map, stories, armory and rankings, plus pages from wiki or blank templates
- Signed-in admins get **Jarl** and **Layout Editor** shortcuts on every page

</td>
<td width="50%" valign="top">

**Safe by default**
- Game password required; removable only with a passwordless-server mod
- Separate Linux accounts for the game and the panel
- One-time setup links; privileged actions go through an audited executor
- No core telemetry; optional AI stories send consented facts to the chosen provider

</td>
</tr>
</table>

## Optional Sagas extension

Sagas adds a Birds Eye map, Viking moments, an **Armory** with each Viking's
profile (a portrait rendered by the game, equipment with icons, hotbar and
item details), rankings and AI-assisted chapters to the site. The admin
enables each feature in Jarl; players choose separately whether to share their
profile, map, position and story facts. Provider keys stay on the server. The
[Sagas guide](https://github.com/brkihel/Heimdall-Nexus/wiki/Sagas) explains
installation, consent and what is still on the roadmap.

<img src=".github/assets/stories.webp" alt="Sample Viking story with the campfire background and boss battle art" width="100%">

See the [release notes](CHANGELOG.md).

## Documentation

Everything lives in the [**wiki**](https://github.com/brkihel/Heimdall-Nexus/wiki), in English and Portuguese:
[Installation](https://github.com/brkihel/Heimdall-Nexus/wiki/Installation) ·
[Configuration](https://github.com/brkihel/Heimdall-Nexus/wiki/Configuration) ·
[Operations](https://github.com/brkihel/Heimdall-Nexus/wiki/Operations) ·
[Visual Editor](https://github.com/brkihel/Heimdall-Nexus/wiki/Visual-Editor) ·
[Sagas](https://github.com/brkihel/Heimdall-Nexus/wiki/Sagas)

## Updating

From the panel: **Jarl → Sobre e atualizações → Procurar atualizações**. Review the changes, approve the exact version, and the panel updates and comes back on its own.

<img src=".github/assets/updates.webp" alt="Jarl showing Heimdall Nexus 1.0.0 on the stable update channel" width="100%">

Screenshots use illustrative data; they do not show a real server.

From a terminal on an installed server:

```bash
cd ~/Heimdall-Nexus && git pull --ff-only && sudo ./deploy/update.sh
```

It updates the panel and tools without touching worlds, mods or site content, and does not restart Valheim. If the Sagas bridge changed, restart the game when convenient.

## License

Heimdall Nexus is **source-available** under the [PolyForm Noncommercial License 1.0.0](LICENSE). You may use, study, modify and share it for any **noncommercial** purpose: running your own or your community's server, hobby projects, learning, and nonprofit or public organizations. **Selling it or using it commercially is not allowed.** For commercial use, contact the author.

Valheim is a trademark of Iron Gate AB. The default site backgrounds are original artwork made for Heimdall Nexus (drawn by `.github/art/landscapes.html`) and are covered by this license. Heimdall Nexus is not affiliated with Iron Gate AB or Coffee Stain.

<div align="center">
<br>
<sub>Made by <a href="https://github.com/brkihel">BRKiHeL</a> for the Valheim community.</sub>
</div>
