# Heimdall Nexus

**Valheim Server Management Platform**
Created by **BRKiHeL**. [Leia em português](README.pt-BR.md).

Heimdall Nexus installs and runs a Valheim dedicated server and gives it a browser panel and a public website you edit visually. From the panel you manage the game, mods, schedules and backups. The site ships with a neutral Heimdall identity: set your name, logo, favicon, colors, background and footer in **Aparência**, create pages from the wiki or blank templates, and edit their text in the visual editor. No page generators or spreadsheets.

## Prepare the VM

Use a fresh Ubuntu or Debian x86-64 host with systemd, Python 3.10 or newer, sudo, internet access, and space for the game, worlds, mods and backups. Install the operating system packages first:

~~~bash
sudo apt update
sudo apt install -y git ca-certificates curl tar unzip libc6-i386 lib32gcc-s1 \
  libatomic1 libpulse0 libpulse-dev nginx python3 python3-venv python3-pip rsync
~~~

If you plan to enable automatic HTTPS, also run `sudo apt install -y certbot python3-certbot-nginx`. The wizard installs these packages again if needed, but preparing them now exposes package or repository problems before you enter your settings. SteamCMD, the Valheim server, optional BepInEx and modpack files are downloaded by the wizard. You do not need Node.js, Docker or a local Steam client. See the [full preparation checklist](docs/wiki/Installation.md#1-prepare-a-host).

## Visual installation

Clone the repository, then run:

~~~bash
git clone https://github.com/brkihel/Heimdall-Nexus.git
cd Heimdall-Nexus
sudo ./deploy/install.sh
~~~

The terminal shows how to open the wizard in your browser. There are three ways:

- **Temporary HTTPS link (default).** The installer creates it with Cloudflare Quick Tunnel and prints it only after checking that it opens. If the link stops working, it creates a new one and prints it. The wizard itself still listens only on 127.0.0.1:8765.
- **Direct link, `--direct`.** For a machine on a network you trust, such as a VM on your LAN. The wizard listens on the machine's IP and prints `http://IP:8765/claim?token=…`. It uses plain HTTP, so avoid it on public networks. Allow TCP 8765 if the firewall blocks it.
- **SSH forwarding, `--local-only`.** No external service and no open port.

~~~bash
sudo ./deploy/install.sh --direct       # VM on your network
sudo ./deploy/install.sh --local-only   # then, on your computer:
ssh -L 8765:127.0.0.1:8765 user@your-server
~~~

Every link carries a one-time token; keep it private. Open the printed URL in your local browser. Choose the domain or IP, game name/world/port, optional BepInEx, live data, a Linux service account name, a separate panel login, and whether to start the game. **Starting Valheim defaults to off.** The wizard displays each install step.

It downloads SteamCMD from Valve and installs Valheim Dedicated Server (Steam App 896660), a systemd game service, persistent saves, Nginx, the site, and the panel. Service code is copied to `/opt/heimdall-nexus`, so the panel works even when the repository was cloned under a private home directory. BepInExPack Valheim is optional. A Hexium modpack selection fills the **site listing** and can install its server-compatible packages and dependencies in one batch. When dependency versions conflict, the highest required version is used. Explicit client-only packages are skipped. Review mod-specific configuration after installation.

After installation, open https://YOUR-DOMAIN/jarl/entrar or http://YOUR-IP/jarl/entrar without HTTPS. Edit pages under **Site → Full screen editor**. Page saves keep versions and previews. The site's editable copy is in /var/lib/heimdall-nexus/site, separate from the repository checkout.

With Steam networking, open the selected UDP game port and the next one. Nginx uses TCP 80 and, with HTTPS, TCP 443. See the [official Valheim server guide](https://valheim.com/support/a-guide-to-dedicated-servers/).

## Documentation

- [Wiki home](docs/wiki/Home.md) / [Português](docs/wiki/pt-BR/Inicio.md)
- [Installation](docs/wiki/Installation.md) / [Instalação](docs/wiki/pt-BR/Instalacao.md)
- [Configuration](docs/wiki/Configuration.md) / [Configuração](docs/wiki/pt-BR/Configuracao.md)
- [Operations](docs/wiki/Operations.md) / [Operação](docs/wiki/pt-BR/Operacao.md)
- [Visual editor](docs/wiki/Editor.md) / [Editor visual](docs/wiki/pt-BR/Editor.md)

## Checks

~~~bash
python3 -m unittest discover -s tests -v
bash -n deploy/install.sh deploy/install-web.sh deploy/valheim-launch.sh
node --check deploy/setup/app.js
~~~

These checks never start Valheim. A full install still requires an end-to-end run on a fresh host; do not run this wizard on an existing production server.
