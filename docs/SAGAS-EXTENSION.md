# Heimdall Sagas extension

Status: **0.1.5 development preview** (bridge 0.1.5, client 0.1.4). The extension is opt-in and separate
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
   renders pages with the site's appearance tokens. A separate one-shot worker
   makes OpenRouter requests only after an administrator queues a chapter.

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
prunes SQLite to the 100,000 most recent events and 1,000 stories each hour and commits each
five-second import batch in one transaction. The client sends presence every
30 seconds while connected.

The admin can show all kills, only bosses plus named elite creature types and
creatures with at least three stars, or bosses only. Deaths remain visible in
every mode. The client and bridge apply the filter before storage; the Nexus
also filters pending packets and existing history. Older events without boss
or elite classification remain visible in the all-kills mode.
When map sharing is enabled, new kill and death events also carry the game's
biome name. Turning map sharing off clears stored biome names along with event
coordinates. The public Crônicas page marks bosses, elites, and high-star
kills, offers matching filters, and builds a recent-feats panel from visible
events. The panel only summarizes the latest events returned by the API.

Stories require a separate `ShareStories` client consent, off by default.
Only players who also share their profile can be included in Viking or server
chapters. The admin enables stories in Jarl, saves an OpenRouter key there,
and requests a chapter for a Viking or the server. The key is stored outside
the game process and outside SQLite, with mode 0600, and is never returned to
the browser or written to the audit log. The worker sends only selected event
facts, dates and public Viking names to OpenRouter and its selected model
provider; it excludes coordinates, opaque IDs,
equipment and map data. It reserves one of the daily attempts before each
request, including failed attempts. `openrouter/free` is the default; a paid
model requires an explicit admin opt-in. Stories are labeled as AI fiction and
retain visible event references. Opting out of `ShareStories` deletes chapters
that reference that Viking while keeping ordinary shared events.

## Discoveries and world map

The bridge records a `discover` event, server-side, when a consenting Viking
comes within reach of a boss altar, Haldor, Hildir or the Bog Witch, or reads a
Vegvisir (the game's own discovery request, checked against the player's
position). Vegvisir boss targets are learned at runtime, so modded boss
locations are included. At startup the bridge logs which built-in landmark
names exist in the loaded world.

After each server start the bridge derives a 512x512 biome grid from the world
seed (`WorldGenerator.GetBiome`, a few rows per frame) and drops it in the
inbox. The importer keeps it in `atlas/`. The admin picks the public map mode:
no map, known lands (terrain revealed 700 m around consented shared locations;
default) or the whole world. The overview API returns the image only when its
content key changes. Player exploration fog from the client is not captured.

## Story providers and automatic chapters

Stories can use OpenRouter free models, paid OpenRouter models, the OpenAI API
or the Anthropic API. ChatGPT and Claude subscriptions do not include API
access; each provider needs its own API key and billing. Keys are stored per
provider (`openrouter.key`, `openai.key`, `anthropic.key`, mode 0600).

With automatic chapters on, the story worker (every 30 s) writes one chapter
around each boss kill or discovery that happens after automation was enabled,
within the daily limit. Nearby moments of the same Viking are context. Triggers
cited in a chapter do not start their own. Automatic chapters are labeled on
the public page.

## Feature inventory

| Capability | State | Completion requirement |
|---|---|---|
| Online presence and world day | Implemented in preview | Dedicated server playtest; pause/time-skip behavior |
| Last equipped items | Implemented in preview | Verify modded inventory slots and item localization |
| Kill and death events with local retry, admin kill filter, biome, and recent feats | Implemented in preview | One-client combat/reconnect and consent-revocation playtest |
| Advanced boss credit, drops, rarity, bounty | Planned | Server-authoritative provenance and deduplication tests |
| Seed biome map with known-lands fog and discovery pins | Implemented in preview | Real-world orientation check |
| Client exploration fog, custom pins, activity layers | Planned | Consent-preserving capture, bounded transport, large-map tests |
| Portraits, icons, effects, resistances | Planned | Frame-budgeted capture and media validation |
| Rankings, comparisons, trophy hall | Planned | Credited fact ledger and time-window rules |
| SLS, Epic Loot, Jewelcrafting | Planned | Independent soft adapters and absent-mod tests |
| Personal login and player settings | Planned | One-time challenge, owner verification, revocation |
| Viking/server stories: on demand and automatic on boss kills and discoveries; OpenRouter, OpenAI or Anthropic | Implemented in preview | One-client consent and live provider playtest |
| Multi-scene journey replay and automatic milestones | Planned | Fact-ledger sequencing, budgets, provider key custody |
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
2. **Build a credited fact ledger.** Extend basic kill tracking with boss, item and
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
5. **Extend optional stories.** Add scene-by-scene replay, character
   biographies and automatic milestones after the on-demand worker passes a
   real provider test. No model call runs in the game process.
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
