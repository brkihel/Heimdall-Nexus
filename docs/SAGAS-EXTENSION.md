# Heimdall Sagas extension

Status: **optional preview introduced in Heimdall Nexus 0.2.0** (bridge and
client 0.2.0 add the Armory profile). The extension is opt-in and separate
from the existing `saga.json` skill ranking. It has not been installed on a live
server or published to Hexium.

## Ownership and design

The implementation in this repository was written for Heimdall Nexus.
[ValheimSagas](https://github.com/pendulumgames/ValheimSagas) was used to
inventory desired behavior and study the presentation. One part is adapted from
its MIT-licensed source: the client's item icon and character portrait capture
(`extensoes/sagas/mod/HeimdallSagas.Client/Art/`), credited with its license in
`extensoes/sagas/mod/THIRD-PARTY-NOTICES.md`. No ValheimSagas web asset,
stylesheet, illustration, or binary was copied. Heimdall's
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
coordinates. The public map marks bosses, elites, and high-star kills and
offers matching filters. The home page's Saga section summarizes recent
moments and feats from visible events only.

Stories require a separate `ShareStories` client consent, off by default.
Only players who also share their profile can be included in Viking or server
chapters. The admin enables stories in Jarl, saves a provider key there,
and requests a chapter for a Viking or the server. The key is stored outside
the game process and outside SQLite, with mode 0600, and is never returned to
the browser or written to the audit log. The worker sends only selected event
facts, dates and public Viking names to the selected model provider; it excludes
coordinates, opaque IDs,
equipment and map data. It reserves one of the daily attempts before each
request, including failed attempts. `openrouter/free` is the default; a paid
model requires an explicit admin opt-in. Stories are labeled as AI fiction and
retain visible event references. Opting out of `ShareStories` deletes chapters
that reference that Viking while keeping ordinary shared events.

## Armory profiles

With `ShareProfile` on, client 0.2.0 sends each equipped item's type, quality,
durability, stats, effects and Jewelcrafting sockets, the hotbar (slots 1–8),
and maximum health, stamina, eitr and armor. Item icons and a transparent
portrait are PNG files sent separately in 60 KiB pieces over a dedicated RPC,
only after the bridge announces the `m` capability (tied to the admin's
equipment option). The bridge rebuilds each file, accepts it only if its
SHA-256 matches its name and its size and dimensions fit (icons up to 128 px
and 48 KiB, portraits up to 1024×1536 and 1 MiB, at most 6 MiB per player per
minute), writes it to the spool and confirms. A presence names an image only
after that confirmation.

The importer checks every PNG chunk and checksum, accepts only 8-bit RGB/RGBA
non-interlaced pictures whose data inflates to exactly the promised size, and
keeps a copy with only the picture chunks in private storage. The public
`/api/sagas/v1/vikings/<id>` profile and its `/media/<hash>.png` files are read
with current consent on every request: a picture is served only while the
Viking shares a profile that shows it and the admin keeps equipment on.
Pictures no profile shows are removed after 14 days; at most 4,000 are kept.

The portrait is rendered by the game from a frozen copy of the Viking on an
isolated layer, in a neutral studio, only when the appearance changed and the
Viking is standing, with the work spread over frames. The `[Portrait]` client
section turns it off, sets a refresh key (F9) and tunes light and camera; a
changed value retakes the portrait at once.

## Discoveries and world map

The bridge records a `discover` event, server-side, when a consenting Viking
comes within reach of a boss altar, Haldor, Hildir or the Bog Witch, or reads a
Vegvisir (the game's own discovery request, checked against the player's
position). Vegvisir boss targets are learned at runtime, so modded boss
locations are included. At startup the bridge logs which built-in landmark
names exist in the loaded world.

The bridge derives 4096x4096 cartography layers from the world seed in a
background task and drops them in the Sagas inbox. The importer checks sizes
and metadata, then copies the layers into private storage. A separate,
memory-limited worker renders only the Birds Eye style into private WebP tiles.
The public tile endpoint checks the admin's current map mode on every request.
In known-lands mode (default), it also checks current profile and map consent
and reveals terrain within 700 m of shared locations; the response itself is
masked, so guessing a tile URL cannot reveal the full world. Disabling the map
or revoking consent takes effect on the next request. Full-world mode explicitly
reveals every tile. The old biome grid is discarded. Client exploration fog is
not captured. Exporting layers uses about 117 MB of private storage per world,
plus rendered tiles; the worker runs outside the game with a 2 GB memory cap.

An installation can instead keep an existing map exporter. Set
`HEIMDALL_EXTERNAL_ATLAS_DIR` for the panel and executor to a read-only
directory containing `metadata.json` and `tiles/<revision>/<style>/<z>/<x>/<y>.webp`.
The metadata must identify the current Valheim world UID, a 24,576 m world
span, 8,192 px source, 256 px tiles, zoom 5, and any of `vanilla`,
`topografico`, and `birds-eye`. The public map then offers the available styles
and applies the same admin map mode and current player consent to every tile
request. A stale export from before a wipe is ignored because its world UID
does not match. The raw tile directory **must not be served by Nginx**; only
the consent-filtering `/api/sagas/v1/atlas/` endpoint may expose it. This
integration does not install or change the external exporter.

## Story providers and automatic chapters

Stories can use OpenRouter free or paid models, the OpenAI API, the Anthropic
API, or the Google Gemini API. Gemini defaults to `gemini-3.8-flash` and sends
consented story facts through Google's `generateContent` endpoint with an
authorization key from [Google AI Studio](https://ai.google.dev/aistudio).
Legacy keys may no longer work; the panel does not assume a fixed key prefix.
The [Gemini pricing
page](https://ai.google.dev/gemini-api/docs/pricing) lists free-tier quotas,
possible charges for billed keys, and the data-use terms for each tier. The
Jarl explains these terms next to the provider choice. ChatGPT and Claude
subscriptions do not include API access; each provider needs its own API key.
Keys are stored per provider (`openrouter.key`, `openai.key`, `anthropic.key`,
`gemini.key`, mode 0600). They never go to the browser or audit log.

With automatic chapters on, the story worker (every 30 s) writes one chapter
around each boss kill or discovery that happens after automation was enabled,
within the daily limit. Nearby moments of the same Viking are context. Triggers
cited in a chapter do not start their own. Automatic chapters are labeled on
the public page.

## Feature inventory

The public site has separate `/mapa/`, `/historias/`, `/armaria/`, and
`/rankings/` pages. The old `/cronicas/` address redirects to the map. The
story page uses the project owner's supplied campfire illustration, served
locally as WebP. Armaria displays the latest consented equipment; Rankings is
currently an explicit recency-based preview using at most 100 public events
(5 points per boss, 2 per discovery, 1 per other kill). The complete rankings
feature still requires a credited fact ledger and time-window rules.

Known boss kills and chapters that cite them use the owner's seven battle
illustrations (Eikthyr, Elder, Bonemass, Moder, Yagluth, Queen, and Kall
Fimbulbringer). The shared renderer matches a fixed list of names and requires
the public fact to be a boss **kill**; an altar discovery or an unrelated
chapter never receives battle art. Bosses without a supplied image retain the
normal card. The images are served locally as compressed WebP, with a dark
overlay and a gradient on the text side. Existing editable page sources need
no replacement for this decoration.

The sitewide menu is configured in Jarl → Site → Editor → Menu. Admins can
rename, reorder, hide, and style links; the colors can inherit the site theme
or be set explicitly. Publishing adds the menu without rewriting editable
page sources. An update adds these built-in pages to an existing installation
without replacing its home, Wiki, appearance, or other custom pages.

| Capability | State | Completion requirement |
|---|---|---|
| Online presence and world day | Implemented in preview | Dedicated server playtest; pause/time-skip behavior |
| Last equipped items | Implemented in preview | Verify modded inventory slots and item localization |
| Kill and death events with local retry, admin kill filter, biome, and recent feats | Implemented in preview | One-client combat/reconnect and consent-revocation playtest |
| Advanced boss credit, drops, rarity, bounty | Planned | Server-authoritative provenance and deduplication tests |
| Birds Eye map with consent-filtered known-lands fog and discovery pins | Implemented in preview | Real-world orientation and performance check |
| Client exploration fog, custom pins, activity layers | Planned | Consent-preserving capture, bounded transport, large-map tests |
| Armory profile: item icons, hotbar, portrait, item details, Jewelcrafting sockets | Implemented in preview | One-client portrait playtest; Epic Loot and Nemesis adapters |
| Rankings, comparisons, trophy hall | Planned | Credited fact ledger and time-window rules |
| SLS, Epic Loot, Jewelcrafting | Planned | Independent soft adapters and absent-mod tests |
| Personal login and player settings | Planned | One-time challenge, owner verification, revocation |
| Viking/server stories: on demand and automatic on boss kills and discoveries; OpenRouter, OpenAI, Anthropic or Gemini | Implemented in preview | One-client consent and live provider playtest |
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
