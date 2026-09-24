# Installation

[Português](pt-BR/Instalacao.md) · [Wiki home](Home.md)

## 1. Prepare a host

Use a fresh Ubuntu or Debian x86-64 machine with systemd and sudo. Give it internet access and space for the Valheim download, worlds, mods and backups. Check the architecture, operating system and free disk space before starting:

~~~bash
uname -m
. /etc/os-release && echo "$PRETTY_NAME"
df -h /
~~~

`uname -m` must print `x86_64`. The installer currently accepts Ubuntu and Debian and needs Python 3.10 or newer; run the commands as root if the VM has no `sudo` account. On the VM, install **all operating system packages used by the base installation** before opening the wizard:

~~~bash
sudo apt update
sudo apt install -y git ca-certificates curl tar unzip libc6-i386 lib32gcc-s1 \
  libatomic1 libpulse0 libpulse-dev nginx python3 python3-venv python3-pip rsync
python3 --version
~~~

If you will select automatic HTTPS in the wizard, also install `sudo apt install -y certbot python3-certbot-nginx`. These commands use the same package names as the installer. The installer checks and installs missing packages too, so repeating the command is safe. Doing it now lets you resolve APT repository errors before entering the form. The [Valheim server guide](https://valheim.com/support/a-guide-to-dedicated-servers/) specifically lists `libatomic1`, `libpulse-dev` and `libpulse0` as Linux requirements.

SteamCMD, Valheim Dedicated Server, optional BepInEx and modpack archives are **downloaded by the visual installer**. Its panel libraries are installed into a Python virtual environment from `deploy/requirements-panel.txt`. Do not install Steam, Node.js, Docker or Python packages globally for this setup.

Keep outbound DNS, HTTPS, APT repository access and Steam downloads available. The temporary browser link also needs outbound access to Cloudflare; the wizard itself opens no inbound setup port. For a public website, point a DNS name to the VM and allow TCP 80 and 443. Automatic HTTPS needs the name to resolve publicly and TCP 80 to be reachable for the certificate request.

For the game, plan a UDP port (default 2456). With the Steam backend, allow that port and the following one through the host firewall and router. See the [official Valheim dedicated server guide](https://valheim.com/support/a-guide-to-dedicated-servers/). Crossplay uses PlayFab relay as described there.

## 2. Clone the repository


~~~bash
git clone https://github.com/brkihel/Heimdall-Nexus.git
cd Heimdall-Nexus
./deploy/install.sh --check
~~~

`--check` verifies the OS, architecture and existing installation/service conflict without changing the VM. It does not verify network access or run the full installation. You may clone into your home directory: during installation, the wizard copies service code to `/opt/heimdall-nexus`. The service account does not need access to your home directory. Do not put game passwords, panel credentials, saves or local environment files in Git.

## 3. Start the visual wizard

~~~bash
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

Every link carries a one-time token; keep it private. Open the printed URL, including its token, in that computer's browser. The token is not written to access logs. Keep both terminal and browser open until completion.

## 4. Fill in the five screens

1. **Site:** DNS name or IP and the address players use. Turn on HTTPS only when using a public DNS name and give a certificate email.
2. **Server:** server name, world name, UDP port, optional game password, public listing and crossplay.
3. **Features:** choose BepInEx for a modded server or leave it off for vanilla. A Hexium modpack fills the site list. The separate server-install checkbox downloads its pinned dependencies in one batch and skips packages labeled client-only. Enable only live data groups this server supports.
4. **Administrator:** choose two separate names: the Linux account that runs the panel (default `heimdall`) and the browser login (default `jarl`). Then set the panel password, which is stored as a hash. The game continues to use a separate `valheim` Linux account.
5. **Review:** decide whether Valheim should start automatically when installation finishes and at boot. This option is off by default.

The progress screen shows package installation, SteamCMD download, Valheim App 896660 installation, optional BepInEx, website/panel setup, and HTTPS. A failed step can be retried after fixing its cause; the installer recognizes its own partially created service.

## 5. Use the result

Open the site and panel links shown at the end. Log in to the panel and use **Site → Full screen editor** for layout and content. If game startup was left off, start it from the panel when ready.

Paths: /opt/heimdall-nexus for installed service code; /srv/valheim/current for game files; /srv/valheim/saves for worlds; /var/lib/heimdall-nexus/site for editable pages; /etc/heimdall-nexus/heimdall.env for host settings; /etc/heimdall-panel/config.json for panel credentials. Do not delete the saves directory during a game update.

## Common issues

- **Wizard cannot open:** check that the installer is still running. If the Cloudflare link fails, the installer tries again and prints a new one; on a VM in your network, rerun with `--direct`. Otherwise use `--local-only` with SSH forwarding.
- **Nginx welcome page or `/jarl/entrar` returns 404 after setup:** on the VM, run `sudo nginx -t && sudo systemctl reload nginx`. Nginx may still be using the configuration it loaded before the installer added the site. Confirm the panel with `sudo systemctl status heimdall-panel --no-pager`. New installations reload Nginx and check both routes before reporting success.
- **`/jarl/entrar` returns 502 and the panel log shows `status=200/CHDIR`:** an older installation may run code from a private home directory that the service cannot traverse. The current installer uses `/opt/heimdall-nexus` and avoids this. To repair an older installation without reinstalling, change into the repository directory and run `sudo apt install -y acl`, `sudo setfacl -m u:painel:--x "$HOME" "$PWD" "$PWD/servicos"`, then `sudo systemctl restart heimdall-panel`. This grants path traversal only, without allowing directory listing.
- **HTTPS fails:** verify DNS and inbound TCP 80. After correction, retry in the same wizard.
- **Game does not appear:** check the UDP ports and whether the game was started. Review its service logs with sudo journalctl -u heimdall-valheim -n 100.
- **Server stays vanilla:** BepInEx and the modpack server-install option must be selected. Inspect the progress log for skipped client-only packages and configure server mods as needed.
- **Existing game service rejected:** the wizard will not overwrite an unmanaged service. Use a fresh host or migrate that service manually first.

A full fresh-host run has not yet been verified by this project's automated tests. Development checks verify syntax and installer logic without changing the running game.
