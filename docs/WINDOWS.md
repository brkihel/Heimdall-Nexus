# Heimdall Nexus on Windows: how it works

For maintainers. The user guide is in the wiki:
[Installation on Windows](https://github.com/brkihel/Heimdall-Nexus/wiki/Installation-Windows).

One code base serves both systems. Everything that differs lives in
`servicos/painel/hostos`; the rest of the code never calls systemctl,
journalctl, fcntl, pwd or grp directly. The deployment pieces that only exist
on Windows live in `deploy/windows`.

## The host layer (`servicos/painel/hostos`)

| Function | Linux (`_linux.py`) | Windows (`_windows.py`) |
|---|---|---|
| `env_path`, `DEFAULTS` | `/srv/valheim`, `/var/lib/...`, `/etc/...` | `%ProgramData%\HeimdallNexus\...`, code in `%ProgramFiles%\HeimdallNexus` |
| `service_show/action/is_active` | `systemctl` | Service Control Manager through pywin32; memory and start time through psutil |
| `service_logs`, `service_logged_since_start` | journald, per invocation | Log files; the game launcher starts a new file on every start |
| `timer_is_active` | `<name>.timer` | The job is enabled in `state\jobs.json` and its host service runs |
| `exclusive_lock` | `fcntl.flock` | `msvcrt.locking` on the first byte |
| `chown`, `lchown`, `fchown`, `account_ids` | POSIX owners | No-ops: folder permissions are inherited |
| `copy_access` | No-op (callers chown/chmod) | Copies the DACL of the file being replaced |
| `open_untrusted` | `O_NOFOLLOW` | Opens without following reparse points, then refuses links, directories and extra hard links on the open handle |
| `link_directory` | Symlink | Junction |
| `detached_job_start/running` | `systemd-run` | One-off scheduled task as SYSTEM |
| `ExecutorServer`, `executor_connect` | Unix socket owned by the panel group | 127.0.0.1 with mutual HMAC challenge-response (`_channel.py`) |

Service data keeps systemd's vocabulary (`ActiveState`, `SubState`,
`MemoryCurrent`, `InvocationID`...) on both systems, so the panel reads one
format.

### The executor channel

The executor listens on `127.0.0.1:8792`. Both sides know a random secret in
`etc\executor.key`, readable only by SYSTEM, administrators and
`NT SERVICE\heimdall-panel`. The server sends a nonce; the client answers with
`HMAC(key, client:server_nonce:client_nonce)` and its own nonce; the server
proves itself with `HMAC(key, server:client_nonce:server_nonce)`. The secret
never crosses the connection, and a program that grabs the port first learns
nothing it could replay. `tests/test_hostos.py` covers the impostor and
wrong-key cases on every system.

## Services and accounts

`deploy/windows/services.py` writes one WinSW wrapper (pinned by SHA-256) and
XML per service in `%ProgramFiles%\HeimdallNexus\services`, where service
accounts can read them. Every Python service starts through
`deploy/windows/run.py`, which loads `etc\heimdall.env` like systemd's
`EnvironmentFile`, with `python -X utf8`.

| Service | Account | Writes to |
|---|---|---|
| `heimdall-executor` | LocalSystem | Everything the fixed verbs allow |
| `heimdall-panel` | `NT SERVICE\heimdall-panel` | `etc\panel`, `panel\troca`, its log folder |
| `heimdall-valheim` | `NT SERVICE\heimdall-valheim` | `valheim` (except `server.env`, read-only), `state\sagas\inbox` |
| `heimdall-web` (Caddy) | `NT SERVICE\heimdall-web` | `caddy` (certificates), its log folder |
| `heimdall-jobs` | LocalSystem | Status and saga feeds, scheduled tasks |
| `heimdall-sagas-jobs` | `NT SERVICE\heimdall-sagas-jobs` | `state\sagas` |

`%ProgramData%\HeimdallNexus` has inheritance cut at the top: SYSTEM and
administrators only, then the grants above (`installer_windows.permissions`).
Rewrites through a temporary file call `hostos.copy_access`, otherwise the new
file would inherit its folder's rights; that is what keeps `server.env`
read-only for the game after Jarl saves it.

## The game

`deploy/windows/launcher-windows.py` replaces `valheim-launch.sh`: the same
argument checks (a shared test keeps the modifier lists equal), `server.env`
handed to the game like `EnvironmentFile`, and Doorstop switched by
`--doorstop-enabled` so a leftover `winhttp.dll` never loads mods on a vanilla
server. It writes `valheim\logs\heimdall-valheim.log` (three older runs kept)
and `valheim\run\heimdall-valheim.run.json` (invocation id, start time, pid).
Stopping the service sends Ctrl+C to the console; Valheim saves and exits, and
WinSW waits up to 150 seconds.

## Things Windows does differently

- An open file cannot be deleted or replaced. SQLite connections are closed
  at the end of their block (`sagas.Connection`); `update.py` stops the Python
  services before pip; the Sagas bridge is replaced only while Valheim is stopped.
- Windows Python has no time zone database: `tzdata` is a dependency.
- Tools print in the console code page: every `subprocess` call on Windows
  decodes with `errors='replace'`.
- PowerShell 5 reads BOM-less scripts as ANSI: `install.ps1` and
  `uninstall.ps1` stay pure ASCII (a test checks it).
- The Python installer needs `"TargetDir=..."` quoted; unquoted, a path with a
  space installs to `C:\Program`.

## Testing

The whole suite runs on both systems. Tests that exercise bash, systemd or the
Linux installer are marked Linux-only; Windows has its own
(`tests/test_windows_deploy.py`, the launcher tests in
`tests/test_acesso_modificadores.py`). On Windows, run it with UTF-8 mode:

```powershell
& "$env:ProgramFiles\HeimdallNexus\venv\Scripts\python.exe" -X utf8 -m pytest -q tests
```
