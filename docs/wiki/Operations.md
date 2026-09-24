# Server operations

## Server Config

Open **Server Config** to review startup arguments and edit the server name, world, port, public listing, crossplay, description and game password. The current password is never displayed. Leave the field empty to keep it. A password is required: it can be removed only when a passwordless-server mod (for example `serverblankpassword`) is installed, which shows the **Servidor sem senha** option. Valheim also rejects a password contained in the server name. The description goes into the site's status feed; Valheim has no dedicated description startup flag.

Changes to game arguments require a game restart. The panel offers **Restart to apply** when the game is running. Changing the world name can create a new world at next startup. **Reinstall server** requires the panel administrator password, stops the game if it is running, then verifies official files through SteamCMD. Saves, configurations and mods live separately. Make a backup first. The game remains stopped after reinstalling.

## Mod Config

**Mod Config** is the former mod settings editor. Files remain under `BepInEx/config`. Many mods read their settings only at startup, so restart the game after saving when appropriate.

## Tasks (Tarefas)

In the **Tarefas** tab, a routine has a name and five cron fields. Use **Adicionar tarefa** to add its ordered tasks; each task can wait a few seconds before running. Allowed actions are start, stop, restart and create backup; arbitrary shell commands are unavailable. Times use the operating system's timezone. `0 4 * * *` runs daily at 04:00. **Only when server is online** skips an occurrence when the game is stopped; **Routine enabled** pauses it without deleting. `heimdall-schedule.timer` checks schedules once per minute.

## Backups

**Create backup now** archives saves, configuration and launch settings. If the game is running, it stops for a consistent copy and starts again afterward. You can download, restore, lock and delete backups. Locked archives cannot be deleted by the panel. A restore first makes a safety backup of the current state. Mod maintenance archives are available for download, but only world archives can be restored from this page.

## Update Heimdall Nexus

To bring a new version from GitHub to an installed server:

```bash
cd ~/Heimdall-Nexus
git pull --ff-only
sudo ./deploy/update.sh
```

`update.sh` replaces the panel and tool code in `/opt/heimdall-nexus`, refreshes the site's helper scripts, republishes the site and restarts the panel. Worlds, mods, game settings, site pages and identity stay as they are, and the Valheim server is not restarted.

## Repeat installation on a test VM

These commands **erase that installation's worlds, backups, site and settings**. Run them only on your test VM. The Git checkout and APT packages remain:

```bash
cd ~/Heimdall-Nexus
sudo ./deploy/reset-vm.sh --check
sudo ./deploy/reset-vm.sh --purge
sudo ./deploy/install.sh
```

The reset works on a complete installation or on one that stopped midway, and asks you to type `RESET HEIMDALL VM`. It removes the dedicated panel Linux account so you can choose the same name again, while keeping the `valheim` account.

## Custom modpack (.zip)

A server with unpublished mods can use a `.zip` modpack in the Hexium/Thunderstore package layout:

```
manifest.json          author, name, version_number, description, dependencies
plugins/<Mod>/...      DLLs of private or modified mods
patchers/<Mod>/...     BepInEx patchers, if any
config/...             configuration (optional)
```

`dependencies` lists public mods as `Owner-Name-Version`; they are downloaded from Hexium or Thunderstore during installation. Each bundled mod keeps its own folder under `BepInEx/plugins`.

To build one from an existing server:

```bash
sudo python3 ferramentas/criar-modpack.py /var/lib/heimdall-nexus/modpacks/MyServer-1.0.0.zip \
  --author MyTeam --name MyServer --version 1.0.0
```

The generator compares each installed mod with the official package of the same version. When every DLL is identical, the mod becomes a dependency; unpublished or modified mods are bundled. Configuration is included only with `--with-config`, and the AzuAntiCheat folder and files named like webhook, token or password are always left out.

To install, upload the `.zip` to the server and enter its full path (for example `/root/MyServer-1.0.0.zip`) in the wizard's Modpack field. The progress log lists the SHA-256 of each bundled DLL. A `.zip` runs code on the server: only use packs from a trusted source. Mods that are also needed on clients must still reach players another way.
