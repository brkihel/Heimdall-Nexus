# Heimdall Sagas extension

Status: **0.1.0 development preview**. The extension is opt-in and separate
from the existing `saga.json` skill ranking. It has not been installed on a live
server or published to Hexium.

## Ownership and design

The implementation in this repository was written for Heimdall Nexus. No
ValheimSagas source file, web asset, stylesheet, illustration, or binary was
copied into it. [ValheimSagas](https://github.com/pendulumgames/ValheimSagas)
was used to inventory desired behavior and study the presentation. Heimdall's
site, panel, theme, permissions, and
deployment remain authoritative.

There are three components:

1. **Client BepInEx DLL:** reads a player's own game state only after explicit
   consent, keeps unsent events in a bounded local outbox, and uploads over the
   existing Valheim RPC connection.
2. **Server BepInEx bridge:** verifies the sending peer's owned player identity,
   replaces claimed world/player/name fields, rate limits uploads, and writes
   small envelopes atomically to a bounded local spool. It runs no HTTP server,
   database, AI worker, website, or port listener.
3. **Nexus extension:** imports the spool into SQLite, provides consent-filtered
   read-only APIs through the existing panel process and Nginx domain, and
   renders pages with the site's appearance tokens.

The client and bridge negotiate protocol version 1 before telemetry is sent.
Client events retain an ID across retries; the database has a unique key on
world, actor, and event ID. The bridge acknowledges an event after writing the
file, so reconnects may resend without duplicating the public record. Spool
filenames preserve the bridge's receive order. Profile, map, and position
sharing default to **off**. The public API checks the latest profile/map
consent at read time. Withdrawing profile consent deletes retained events;
withdrawing map consent erases stored event coordinates. Position also requires
Valheim's own public map setting. A missing or invalid settings file disables
the extension until an administrator repairs it.
The bridge checks a 10,000-packet spool limit every 30 seconds. The importer
prunes SQLite to the 100,000 most recent events each hour.

## Feature inventory

| Capability | State | Completion requirement |
|---|---|---|
| Online presence and world day | Implemented in preview | Dedicated server playtest; pause/time-skip behavior |
| Last equipped items | Implemented in preview | Verify modded inventory slots and item localization |
| Death events with local retry | Implemented in preview | One-client death/reconnect playtest and automated retry/dedup tests |
| Kills, boss credit, drops, rarity, bounty | Planned | Server-authoritative provenance and deduplication tests |
| Atlas terrain, fog, pins, activity layers | Planned | Consent-preserving capture, bounded transport, large-map tests |
| Portraits, icons, effects, resistances | Planned | Frame-budgeted capture and media validation |
| Rankings, comparisons, trophy hall | Planned | Credited fact ledger and time-window rules |
| SLS, Epic Loot, Jewelcrafting | Planned | Independent soft adapters and absent-mod tests |
| Personal login and player settings | Planned | One-time challenge, owner verification, revocation |
| Personal/server stories and journey replay | Planned | Fact ledger, budgets, provider key custody, fiction labeling |
| Installer toggle and modpack link | Planned | Versioned release artifacts and staged upgrade flow |

## Delivery sequence

1. **Validate the transport in Valheim.** Run a dedicated server with one
   real client. Exercise death capture, reconnect replay, consent withdrawal,
   and game restart by hand; exercise duplicate packets, queue bounds, invalid
   identities, and disconnected peers in automated protocol tests. Test Steam
   and crossplay sequentially when available, and only claim support for
   transports actually verified. Then publish a versioned client package with
   checksum on Hexium and expose its modpack link in Jarl. The bridge remains
   a separate optional server install.
2. **Build a credited fact ledger.** Add server-observed kill, boss, item and
   bounty facts with stable IDs, actor credit, timestamps, and source adapters.
   Reject facts without verified ownership. Derive rankings and the trophy
   hall from that ledger, with visible rules for ties and time windows.
3. **Build the atlas.** Upload bounded exploration deltas through the same
   game RPC bridge, store map layers outside SQLite as versioned tile files,
   and render only tiles a player or server has authorized. Add pins and
   activity layers after fog withdrawal, reconnect, and large-world tests.
4. **Complete profiles.** Resolve modded item slots and effects through soft
   adapters. Capture portraits and icons within a measured frame budget; allow
   only validated image formats and dimensions before the web server serves
   them. Add verified personal login and self-service revocation before any
   private profile views.
5. **Create optional stories.** Generate from the credited fact ledger in a
   separate Nexus worker with a budget and server-owned provider key. Label
   generated prose as fiction, keep factual event links, and offer a no-AI
   journey replay. No model call runs in the game process.
6. **Polish the Heimdall experience.** Use the existing identity, colors,
   typography, page publication, backups, and Jarl permissions. Keep the
   ValheimSagas sense of spacious maps and editorial cards through original
   HTML/CSS; use no copied code, illustrations, screenshots, or assets.

Each stage has its own server toggle and client consent where player data is
involved. A stage only appears on the public site after it has working data,
privacy controls, and real-game acceptance tests. The existing `/api/saga.json`
ranking keeps its own contract until a verified character identity links it
to this extension.

The preview intentionally does **not** display empty atlas/trophy/ranking
screens as if those features already worked. No historical event is inferred
from old character saves or from a player's current equipment.
The existing skill ranking and new profile use different identifiers; their
records will only be linked after a verified character identity contract is
available. Display names are never used as an identity key.

## Local build and installation

For a one-client setup, including the difference between a BepInEx-only
server and a full Nexus installation, see [the solo test guide](SAGAS-TESTE-SOLO.md).

Build against a legally installed game and BepInEx 5. These assemblies are
compile references and are excluded from both output packages:

```bash
./extensoes/sagas/build.sh /path/to/valheim_Data/Managed /path/to/BepInEx/core
```

The resulting ZIP files under `artifacts/sagas/` contain one DLL each. For an
existing Nexus host, update Nexus first, then use a reviewed Bridge DLL:

```bash
sudo ./deploy/install-sagas-extension.sh /path/to/HeimdallSagas.Bridge.dll
```

The script creates a private spool, installs the bridge and importer timer,
adds the read-only Nginx route if needed, and leaves Valheim running. Restart
the game server separately to load the DLL. Install the matching Client DLL
in each participating player's BepInEx profile. The client package is **not
ready for store publication** until real game tests pass.

## Release gates

- Confirm the runtime player identity on every transport claimed as
  supported; incomplete identity must drop telemetry rather than guess the owner.
- Verify consent withdrawal while an upload is queued and while a browser is
  open. Keep game coordinates out of event storage unless map sharing was
  enabled at capture time.
- Test one real client with disconnect/reconnect, server restart, and a
  Linux dedicated host. Use automated protocol tests for duplicate delivery,
  malformed packets, peer isolation, and busy send queues. Check a game update
  and each claimed client/transport platform before declaring it supported.
  Multiplayer concurrency remains an explicit beta risk until observed in
  community testing; it is not a release blocker for the one-client preview.
- Measure frame time and spool growth with a large modpack. Keep the game
  process independent of SQLite, website rendering, and external AI calls.
- Verify current and older Nexus installs, including Nginx upgrade, theme
  changes, backups, and clean disable/uninstall before offering an installer
  checkbox or publishing the client package.
