using System;
using System.Collections.Concurrent;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using System.Threading;
using System.Threading.Tasks;
using BepInEx;
using HarmonyLib;
using UnityEngine;

namespace Heimdall.Sagas.Mod
{
    [BepInPlugin("gg.heimdall.sagas.bridge", "Heimdall Sagas Bridge", "0.2.1")]
    public sealed class BridgePlugin : BaseUnityPlugin
    {
        private const string Rpc = "Heimdall.Sagas.V1";
        private const string Hello = "Heimdall.Sagas.Hello.V1";
        private const string Probe = "Heimdall.Sagas.Probe.V1";
        private const string Ack = "Heimdall.Sagas.Ack.V1";
        private const string MediaRpc = "Heimdall.Sagas.Media.V1";
        private const string MediaAck = "Heimdall.Sagas.MediaAck.V1";
        // Per player: one image in transit, and at most this much per minute.
        private const int MediaBytesPerMinute = 6 * 1024 * 1024;
        private static readonly FieldInfo lastHit = AccessTools.Field(typeof(Character), "m_lastHit");
        private static BridgePlugin current;
        [Serializable]
        private sealed class BridgeSettings
        {
            public int version = 1;
            public bool enabled = true;
            public bool gear = true;
            public bool events = true;
            public bool clock = true;
            public string kill_mode = "all";
            public string map_mode = "off";
        }
        private sealed class PendingWrite
        {
            internal string Json;
            internal byte[] Media;
            internal string MediaName;
            internal ZRpc ReplyTo;
            internal string EventId;
            internal string AckName = Ack;
        }
        private sealed class MediaTransfer
        {
            internal string Kind, Id;
            internal byte[] Bytes;
            internal bool[] Received;
            internal float Started;
        }
        private readonly Dictionary<ZRpc, MediaTransfer> transfers = new Dictionary<ZRpc, MediaTransfer>();
        private readonly Dictionary<ZRpc, (float Minute, int Bytes)> mediaBudget =
            new Dictionary<ZRpc, (float, int)>();
        private readonly HashSet<ZRpc> registered = new HashSet<ZRpc>();
        private readonly Dictionary<ZRpc, float> nextPacket = new Dictionary<ZRpc, float>();
        private readonly Dictionary<ZRpc, WirePacket> latest = new Dictionary<ZRpc, WirePacket>();
        private readonly HashSet<ZRpc> announced = new HashSet<ZRpc>();
        private BlockingCollection<PendingWrite> queue;
        private readonly ConcurrentQueue<PendingWrite> committed = new ConcurrentQueue<PendingWrite>();
        private Task writer;
        private Harmony harmony;
        private string inbox;
        private string settingsPath;
        private BridgeSettings settings = new BridgeSettings { enabled = false };
        private int writeFailures;
        private float nextTick;
        private float nextClock;
        private float nextSettingsRefresh;
        private long lastSpoolTick;
        private float nextIdentityWarning;
        private float nextLandmarkScan;
        private string atlasWorld = "";
        private bool landmarksLogged;
        private bool externalAtlas;
        private readonly HashSet<string> landmarkSeen = new HashSet<string>();
        // Location prefab names; true marks a boss altar. Vegvisir boss hints
        // add their target names at runtime, so modded bosses are learned too.
        private static readonly Dictionary<string, bool> Landmarks = new Dictionary<string, bool> {
            { "Eikthyrnir", true }, { "GDKing", true }, { "Bonemass", true },
            { "Dragonqueen", true }, { "GoblinKing", true },
            { "Mistlands_DvergrBossEntrance1", true }, { "FaderLocation", true },
            { "Vendor_BlackForest", false }, { "Hildir_camp", false }, { "BogWitch_Camp", false }
        };

        private void Awake()
        {
            inbox = Environment.GetEnvironmentVariable("HEIMDALL_SAGAS_INBOX");
            settingsPath = Environment.GetEnvironmentVariable("HEIMDALL_SAGAS_SETTINGS");
            externalAtlas = Environment.GetEnvironmentVariable("HEIMDALL_SAGAS_EXTERNAL_ATLAS") == "1";
            if (string.IsNullOrWhiteSpace(inbox)) {
                Logger.LogInfo("Heimdall Sagas bridge is idle; no Nexus inbox is configured.");
                return;
            }
            queue = new BlockingCollection<PendingWrite>(512);
            writer = Task.Run(() => WritePackets());
            RefreshSettings();
            current = this;
            harmony = new Harmony("gg.heimdall.sagas.bridge");
            harmony.PatchAll();
        }

        private void OnDestroy()
        {
            harmony?.UnpatchSelf();
            if (current == this) current = null;
            queue?.CompleteAdding();
            try { writer?.Wait(2000); } catch (AggregateException) { }
        }

        private void Update()
        {
            if (queue == null || Time.unscaledTime < nextTick || ZNet.instance == null) return;
            nextTick = Time.unscaledTime + 2f;
            if (!ZNet.instance.IsServer()) return;
            if (Time.unscaledTime >= nextSettingsRefresh) RefreshSettings();
            while (committed.TryDequeue(out var done)) {
                if (done.ReplyTo != null && registered.Contains(done.ReplyTo))
                    done.ReplyTo.Invoke(done.AckName, done.EventId);
            }
            var peers = ZNet.instance.GetPeers().Where(p => p.IsReady()).ToArray();
            var live = new HashSet<ZRpc>(peers.Select(p => p.m_rpc));
            foreach (var peer in peers) {
                if (registered.Add(peer.m_rpc)) {
                    var owner = peer;
                    peer.m_rpc.Register<string>(Rpc, (rpc, data) => Receive(owner, rpc, data));
                    peer.m_rpc.Register<ZPackage>(MediaRpc, (rpc, package) => ReceiveMedia(owner, rpc, package));
                    peer.m_rpc.Register<string>(Probe, (rpc, version) => {
                        if (rpc == owner.m_rpc && owner.IsReady() && version == "1")
                            rpc.Invoke(Hello, "1:" + (settings.gear ? "gm" : "") +
                                                (settings.events ? "e" : "") + ":" +
                                                (settings.kill_mode == "notable" ? "n" :
                                                 settings.kill_mode == "bosses" ? "b" : "a"));
                    });
                }
            }
            foreach (var rpc in latest.Keys.Where(p => !live.Contains(p)).ToArray()) {
                var offline = latest[rpc];
                offline.online = false;
                offline.share_position = false;
                offline.x = offline.z = 0;
                Enqueue(offline);
                latest.Remove(rpc);
                nextPacket.Remove(rpc);
                registered.Remove(rpc);
                announced.Remove(rpc);
            }
            foreach (var rpc in registered.Where(p => !live.Contains(p)).ToArray()) {
                registered.Remove(rpc);
                announced.Remove(rpc);
            }
            foreach (var rpc in transfers.Keys.Where(p => !live.Contains(p) ||
                         Time.unscaledTime - transfers[p].Started > 120f).ToArray()) transfers.Remove(rpc);
            foreach (var rpc in mediaBudget.Keys.Where(p => !live.Contains(p)).ToArray()) mediaBudget.Remove(rpc);
            if (settings.enabled && settings.clock && EnvMan.instance != null &&
                Time.unscaledTime >= nextClock) {
                nextClock = Time.unscaledTime + 30f;
                Enqueue(new WirePacket { type = "clock", world = WorldId(),
                    world_name = SafeName(ZNet.instance.GetWorldName()),
                    day = EnvMan.instance.GetDay(), fraction = EnvMan.instance.GetDayFraction() });
            }
            if (settings.enabled && settings.events && Time.unscaledTime >= nextLandmarkScan) {
                nextLandmarkScan = Time.unscaledTime + 5f;
                ScanLandmarks(peers);
            }
            if (!externalAtlas && settings.enabled &&
                (settings.map_mode == "explored" || settings.map_mode == "full") &&
                atlasWorld != WorldId() && WorldGenerator.instance != null &&
                WorldId() != "") {
                atlasWorld = WorldId();
                ExportCartography(atlasWorld, WorldGenerator.instance);
            }
            var failures = Interlocked.Exchange(ref writeFailures, 0);
            if (failures > 0) Logger.LogWarning("Heimdall Sagas could not store " + failures + " packet(s).");
        }

        private void Receive(ZNetPeer peer, ZRpc rpc, string data)
        {
            if (ZNet.instance == null || !ZNet.instance.IsServer() || peer.m_rpc != rpc ||
                !peer.IsReady() || data == null || data.Length > 32768) return;
            if (nextPacket.TryGetValue(rpc, out var next) && Time.unscaledTime < next) return;
            nextPacket[rpc] = Time.unscaledTime + .2f;
            if (!TryPlayerId(peer, out var playerId)) {
                if (Time.unscaledTime >= nextIdentityWarning) {
                    nextIdentityWarning = Time.unscaledTime + 60f;
                    Logger.LogWarning("Heimdall Sagas received a client packet but could not yet verify the player's character identity.");
                }
                return;
            }
            var packet = Wire.Read(data);
            if (packet == null || packet.version != 1) return;
            if (packet.type != "presence" && packet.type != "withdraw" &&
                !(packet.type == "event" && (packet.kind == "death" || packet.kind == "kill"))) return;
            if (packet.type != "withdraw" && !settings.enabled) return;
            if (packet.type == "event" && !settings.events) return;
            var world = WorldId();
            if (world == "") return;
            if (packet.type == "event" && packet.world != world) return;
            packet.world = world;
            packet.actor = Digest(world + ":" + playerId);
            if (packet.type == "withdraw") {
                latest.Remove(rpc);
                Enqueue(new WirePacket { type = "withdraw", world = world, actor = packet.actor });
                return;
            }
            packet.name = SafeName(peer.m_playerName);
            if (packet.type == "presence") {
                packet.online = true;
                packet.share_stories &= packet.share_profile;
                packet.share_position &= peer.m_publicRefPos;
                if (!packet.share_position) packet.x = packet.z = 0;
                var profile = packet.share_profile && settings.gear;
                packet.gear = profile ? Items(packet.gear, 24) : Array.Empty<GearItem>();
                packet.hotbar = profile ? Items(packet.hotbar, 8) : Array.Empty<GearItem>();
                packet.portrait = profile && MediaLimits.IsId(packet.portrait) ? packet.portrait : "";
                packet.vitals = profile ? Stats(packet.vitals, 8) : Array.Empty<Stat>();
                latest[rpc] = packet;
                if (announced.Add(rpc))
                    Logger.LogInfo("Heimdall Sagas accepted a client sharing snapshot.");
            } else {
                if (!Guid.TryParseExact(packet.id, "N", out _) &&
                    !(packet.id != null && packet.id.Length == 64 &&
                      packet.id.All(c => c >= '0' && c <= '9' || c >= 'a' && c <= 'f')))
                    return;
                if (!latest.TryGetValue(rpc, out var consent) || !consent.share_profile) return;
                packet.has_location &= consent.share_map;
                packet.biome = packet.has_location ? BiomeTag.Safe(packet.biome) : "";
                if (packet.kind == "kill") {
                    packet.target = SafeText(packet.target, 120);
                    packet.stars = Math.Max(0, Math.Min(100, packet.stars));
                    if (!KillFilter.Keep(settings.kill_mode, packet.boss, packet.elite,
                                         packet.stars)) return;
                } else {
                    packet.target = "";
                    packet.stars = 0;
                    packet.boss = packet.elite = false;
                }
                packet.quantity = 1;
                var received = DateTimeOffset.UtcNow.ToUnixTimeSeconds();
                if (packet.utc < received - 7 * 86400 || packet.utc > received + 120)
                    packet.utc = received;
            }
            if (!FiniteCoordinate(packet.x) || !FiniteCoordinate(packet.z)) return;
            Enqueue(packet, packet.type == "event" ? rpc : null);
        }

        // Bounds every profile field; the Nexus importer validates the content again.
        private static GearItem[] Items(GearItem[] items, int maximum) =>
            (items ?? Array.Empty<GearItem>()).Where(g => g != null).Take(maximum).Select(g => new GearItem {
                name = SafeText(g.name, 120), slot = SafeText(g.slot, 40), type = SafeText(g.type, 40),
                prefab = SafeText(g.prefab, 80), quality = Math.Max(1, Math.Min(1000, g.quality)),
                durability = Finite(g.durability), max_durability = Finite(g.max_durability),
                equipped = g.equipped, active = g.active, hotbar = Math.Max(0, Math.Min(8, g.hotbar)),
                icon = MediaLimits.IsId(g.icon) ? g.icon : "", stats = Stats(g.stats, 16),
                effects = (g.effects ?? Array.Empty<string>()).Take(12).Select(e => SafeText(e, 200)).ToArray(),
                socket_color = SafeText(g.socket_color, 9),
                sockets = (g.sockets ?? Array.Empty<GemSocket>()).Where(s => s != null).Take(11).Select(s => new GemSocket {
                    name = SafeText(s.name, 120), icon = MediaLimits.IsId(s.icon) ? s.icon : "",
                    effects = (s.effects ?? Array.Empty<string>()).Take(8).Select(e => SafeText(e, 160)).ToArray()
                }).ToArray()
            }).ToArray();

        private static Stat[] Stats(Stat[] stats, int maximum) =>
            (stats ?? Array.Empty<Stat>()).Where(s => s != null).Take(maximum)
                .Select(s => new Stat { name = SafeText(s.name, 40), value = Finite(s.value) }).ToArray();

        private static float Finite(float value) =>
            float.IsNaN(value) || float.IsInfinity(value) ? 0 : Math.Max(-1000000, Math.Min(1000000, value));

        private void ReceiveMedia(ZNetPeer peer, ZRpc rpc, ZPackage package)
        {
            if (ZNet.instance == null || !ZNet.instance.IsServer() || peer.m_rpc != rpc || !peer.IsReady() ||
                package == null || !settings.enabled || !settings.gear ||
                !latest.TryGetValue(rpc, out var consent) || !consent.share_profile) return;
            string kind, id;
            int total, index;
            byte[] data;
            try {
                kind = package.ReadString();
                id = package.ReadString();
                total = package.ReadInt();
                index = package.ReadInt();
                data = package.ReadByteArray();
            } catch { return; }
            if (!MediaLimits.IsKind(kind) || !MediaLimits.IsId(id) || total < 33 ||
                total > MediaLimits.MaximumBytes(kind) || data == null) return;
            var chunks = (total + MediaLimits.ChunkBytes - 1) / MediaLimits.ChunkBytes;
            if (index < 0 || index >= chunks ||
                data.Length != Math.Min(MediaLimits.ChunkBytes, total - index * MediaLimits.ChunkBytes)) return;
            var minute = Mathf.Floor(Time.unscaledTime / 60f);
            var budget = mediaBudget.TryGetValue(rpc, out var used) && used.Minute == minute ? used.Bytes : 0;
            if (budget + data.Length > MediaBytesPerMinute) return;
            mediaBudget[rpc] = (minute, budget + data.Length);
            if (!transfers.TryGetValue(rpc, out var transfer) || transfer.Id != id || transfer.Kind != kind ||
                transfer.Bytes.Length != total)
                transfers[rpc] = transfer = new MediaTransfer { Kind = kind, Id = id, Bytes = new byte[total],
                    Received = new bool[chunks], Started = Time.unscaledTime };
            Array.Copy(data, 0, transfer.Bytes, index * MediaLimits.ChunkBytes, data.Length);
            transfer.Received[index] = true;
            if (transfer.Received.Any(r => !r)) return;
            transfers.Remove(rpc);
            if (!MediaLimits.Valid(kind, id, transfer.Bytes)) return;
            if (queue == null || !queue.TryAdd(new PendingWrite { Media = transfer.Bytes,
                    MediaName = "media-" + kind + "-" + id + ".png", ReplyTo = rpc, EventId = id,
                    AckName = MediaAck }))
                Interlocked.Increment(ref writeFailures);
        }

        private static bool TryPlayerId(ZNetPeer peer, out long id)
        {
            id = 0;
            if (ZDOMan.instance == null || peer.m_characterID.IsNone()) return false;
            var character = ZDOMan.instance.GetZDO(peer.m_characterID);
            if (character == null || character.GetPrefab() != "Player".GetStableHashCode() ||
                character.GetOwner() != peer.m_uid) return false;
            id = character.GetLong(ZDOVars.s_playerID, 0);
            return id != 0 && (peer.m_playerID == 0 || id == peer.m_playerID);
        }

        private void RefreshSettings()
        {
            nextSettingsRefresh = Time.unscaledTime + 30f;
            if (string.IsNullOrEmpty(settingsPath)) {
                settings = new BridgeSettings { enabled = false };
                return;
            }
            try {
                var info = new FileInfo(settingsPath);
                if (!info.Exists || info.Length > 1024) { settings = new BridgeSettings { enabled = false }; return; }
                var read = JsonUtility.FromJson<BridgeSettings>(File.ReadAllText(settingsPath));
                settings = read != null && read.version == 1
                    ? read : new BridgeSettings { enabled = false };
                settings.kill_mode = KillFilter.Normalize(settings.kill_mode);
            } catch { settings = new BridgeSettings { enabled = false }; }
        }

        private static bool FiniteCoordinate(float value) =>
            !float.IsNaN(value) && !float.IsInfinity(value) && Math.Abs(value) <= 20000;

        private static string SafeName(string value)
        {
            if (string.IsNullOrWhiteSpace(value)) return "Viking";
            var clean = SafeText(value, 64);
            return clean == "" ? "Viking" : clean;
        }

        private static string SafeText(string value, int maximum) =>
            new string((value ?? "").Where(c => !char.IsControl(c)).Take(maximum).ToArray()).Trim();

        private void RecordServerKill(Character victim)
        {
            if (!settings.enabled || !settings.events || victim is Player || lastHit == null) return;
            var view = victim.GetComponent<ZNetView>();
            if (view == null || !view.IsValid() || !view.IsOwner()) return;
            var killer = (lastHit.GetValue(victim) as HitData)?.GetAttacker() as Player;
            if (killer == null || killer.GetPlayerID() == 0) return;
            var world = WorldId();
            if (world == "") return;
            var actor = Digest(world + ":" + killer.GetPlayerID());
            var consent = latest.Values.FirstOrDefault(p => p.actor == actor && p.share_profile);
            if (consent == null) return;
            var zdo = view.GetZDO();
            if (zdo == null) return;
            var boss = victim.IsBoss();
            var elite = KillFilter.IsElite(view);
            var stars = Math.Max(0, Math.Min(100, victim.GetLevel() - 1));
            if (!KillFilter.Keep(settings.kill_mode, boss, elite, stars)) return;
            var location = victim.transform.position;
            var target = Localization.instance == null ? victim.m_name :
                Localization.instance.Localize(victim.m_name);
            Enqueue(new WirePacket { type = "event", kind = "kill",
                id = Digest("kill:" + world + ":" + zdo.m_uid), world = world, actor = actor,
                name = SafeName(killer.GetPlayerName()), target = SafeText(target, 120),
                stars = stars, boss = boss, elite = elite,
                utc = DateTimeOffset.UtcNow.ToUnixTimeSeconds(),
                has_location = consent.share_map,
                biome = consent.share_map ? BiomeTag.At(location) : "",
                x = consent.share_map ? location.x : 0,
                z = consent.share_map ? location.z : 0 });
        }

        private void ScanLandmarks(ZNetPeer[] peers)
        {
            if (ZoneSystem.instance == null || ZDOMan.instance == null) return;
            var world = WorldId();
            if (world == "") return;
            if (!landmarksLogged) {
                landmarksLogged = true;
                var known = new HashSet<string>(ZoneSystem.instance.m_locations
                    .Where(l => l != null).Select(l => l.m_prefabName));
                var missing = Landmarks.Keys.Where(k => !known.Contains(k)).ToArray();
                Logger.LogInfo("Heimdall Sagas landmarks: " + (Landmarks.Count - missing.Length) + "/" +
                               Landmarks.Count + " found" +
                               (missing.Length > 0 ? " (missing: " + string.Join(", ", missing) + ")" : "") + ".");
            }
            foreach (var peer in peers) {
                if (!latest.TryGetValue(peer.m_rpc, out var consent) || !consent.share_profile) continue;
                if (!TryPlayerId(peer, out var playerId)) continue;
                var body = ZDOMan.instance.GetZDO(peer.m_characterID);
                if (body == null) continue;
                var position = body.GetPosition();
                var zone = ZoneSystem.GetZone(position);
                for (var dx = -1; dx <= 1; dx++)
                for (var dy = -1; dy <= 1; dy++) {
                    if (!ZoneSystem.instance.m_locationInstances.TryGetValue(
                            new Vector2s(zone.x + dx, zone.y + dy), out var place)) continue;
                    var name = place.m_location?.m_prefabName;
                    if (name == null || !Landmarks.TryGetValue(name, out var boss)) continue;
                    var reach = Math.Max(40f, place.m_location.m_exteriorRadius + 10f);
                    var offset = new Vector2(position.x - place.m_position.x, position.z - place.m_position.z);
                    if (offset.magnitude > reach) continue;
                    var actor = Digest(world + ":" + playerId);
                    var key = actor + ":" + name + ":" + Mathf.RoundToInt(place.m_position.x) + ":" +
                              Mathf.RoundToInt(place.m_position.z);
                    if (!landmarkSeen.Add(key)) continue;
                    RecordDiscovery(world, actor, SafeName(peer.m_playerName), consent,
                                    "landmark:" + world + ":" + key, name, boss, place.m_position);
                }
            }
        }

        private void RecordDiscovery(string world, string actor, string name, WirePacket consent,
                                     string identity, string target, bool boss, Vector3 location)
        {
            Enqueue(new WirePacket { type = "event", kind = "discover", id = Digest(identity),
                world = world, actor = actor, name = name, target = SafeText(target, 120),
                boss = boss, utc = DateTimeOffset.UtcNow.ToUnixTimeSeconds(),
                has_location = consent.share_map,
                biome = consent.share_map ? BiomeTag.At(location) : "",
                x = consent.share_map ? location.x : 0,
                z = consent.share_map ? location.z : 0 });
        }

        private void RecordVegvisir(long sender, string location, Vector3 point, int pinType)
        {
            var boss = pinType == (int)Minimap.PinType.Boss;
            if (string.IsNullOrEmpty(location) || location.Length > 80) return;
            if (boss && !Landmarks.ContainsKey(location)) Landmarks[location] = true;
            if (!settings.enabled || !settings.events || ZNet.instance == null) return;
            var peer = ZNet.instance.GetPeer(sender);
            if (peer == null || !latest.TryGetValue(peer.m_rpc, out var consent) ||
                !consent.share_profile || !TryPlayerId(peer, out var playerId)) return;
            var body = ZDOMan.instance.GetZDO(peer.m_characterID);
            // The request carries the stone position; accept it only next to the player.
            if (body == null || Vector3.Distance(body.GetPosition(), point) > 30f) return;
            var world = WorldId();
            if (world == "") return;
            var actor = Digest(world + ":" + playerId);
            RecordDiscovery(world, actor, SafeName(peer.m_playerName), consent,
                            "vegvisir:" + world + ":" + actor + ":" + location,
                            "vegvisir:" + location, boss, point);
        }

        // Once per world: cartography layers for the Birds Eye map. The Nexus
        // renders and tiles them; a marker in BepInEx/config avoids redoing it.
        private void ExportCartography(string world, WorldGenerator generator)
        {
            // Flat files in the inbox: the importer may rename files there, but not
            // a folder created by the game's user. The .meta file is written last.
            var markers = Path.Combine(Paths.ConfigPath, "HeimdallSagas");
            var marker = Path.Combine(markers, "cartography-" + world + ".done");
            var prefix = Path.Combine(inbox, "cartography-" + world + ".");
            if (File.Exists(marker) || File.Exists(prefix + "meta")) return;
            Task.Run(() => {
                var clock = System.Diagnostics.Stopwatch.StartNew();
                try {
                    Cartography.Export(generator, prefix);
                    var temporary = Path.Combine(inbox, ".cartography-" + world + ".meta.tmp");
                    File.WriteAllText(temporary, "{\"version\":1,\"world\":\"" + world + "\",\"size\":" +
                                      Cartography.Size + ",\"pixelSize\":" + (int)Cartography.PixelSize + "}");
                    File.Move(temporary, prefix + "meta");
                    Directory.CreateDirectory(markers);
                    File.WriteAllText(marker, DateTime.UtcNow.ToString("o"));
                    Logger.LogInfo("Heimdall Sagas exported the world map layers in " +
                                   clock.Elapsed.TotalSeconds.ToString("0") + " s.");
                } catch (Exception error) {
                    foreach (var layer in Cartography.Layers)
                        try { File.Delete(prefix + layer); } catch { }
                    Logger.LogWarning("Heimdall Sagas could not export the world map: " + error.Message);
                }
            });
        }

        [HarmonyPatch(typeof(Game), "RPC_DiscoverClosestLocation")]
        private static class VegvisirPatch
        {
            private static void Postfix(long sender, string name, Vector3 point, int pinType)
            {
                try {
                    if (ZNet.instance != null && ZNet.instance.IsServer())
                        current?.RecordVegvisir(sender, name, point, pinType);
                }
                catch (Exception error) { current?.Logger.LogWarning("Heimdall Sagas could not record a Vegvisir: " + error.Message); }
            }
        }

        [HarmonyPatch(typeof(Character), "OnDeath")]
        private static class KillPatch
        {
            private static void Prefix(Character __instance)
            {
                try { current?.RecordServerKill(__instance); }
                catch (Exception error) { current?.Logger.LogWarning("Heimdall Sagas could not record a kill: " + error.Message); }
            }
        }

        private static string WorldId()
        {
            var world = ZNet.instance?.GetWorld();
            return world == null || world.m_uid == 0 ? "" : Digest(world.m_uid.ToString());
        }

        private static string Digest(string value)
        {
            using (var sha = SHA256.Create()) {
                return BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(value)))
                    .Replace("-", "").ToLowerInvariant();
            }
        }

        private void Enqueue(WirePacket packet, ZRpc replyTo = null)
        {
            if (queue == null || string.IsNullOrEmpty(packet.world)) return;
            if (!queue.TryAdd(new PendingWrite { Json = Wire.Write(packet),
                     ReplyTo = replyTo, EventId = packet.id })) Interlocked.Increment(ref writeFailures);
        }

        private void WritePackets()
        {
            try { Directory.CreateDirectory(inbox); }
            catch { Interlocked.Increment(ref writeFailures); return; }
            var nextCapacityCheck = DateTime.MinValue;
            var full = false;
            foreach (var packet in queue.GetConsumingEnumerable()) {
                if (DateTime.UtcNow >= nextCapacityCheck) {
                    try { full = Directory.EnumerateFiles(inbox, "*.json").Take(10000).Count() >= 10000; }
                    catch { full = true; }
                    nextCapacityCheck = DateTime.UtcNow.AddSeconds(30);
                }
                if (full) { Interlocked.Increment(ref writeFailures); continue; }
                // One writer owns the spool. Lexical order matches accepted packet order,
                // including a later consent withdrawal after earlier event packets.
                if (packet.Media != null) { WriteMedia(packet); continue; }
                var tick = Math.Max(DateTime.UtcNow.Ticks, lastSpoolTick + 1);
                lastSpoolTick = tick;
                var name = tick.ToString("D19") + "-" + Guid.NewGuid().ToString("N");
                var temporary = Path.Combine(inbox, "." + name + ".tmp");
                var complete = Path.Combine(inbox, name + ".json");
                try {
                    using (var stream = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write,
                                                      FileShare.None))
                    using (var writer = new StreamWriter(stream, new UTF8Encoding(false))) {
                        writer.Write(packet.Json);
                        writer.Flush();
                        stream.Flush(true);
                    }
                    File.Move(temporary, complete);
                    if (packet.ReplyTo != null) committed.Enqueue(packet);
                } catch {
                    Interlocked.Increment(ref writeFailures);
                    try { File.Delete(temporary); } catch { }
                }
            }
        }

        // Images are named by their content hash: rewriting one is harmless.
        private void WriteMedia(PendingWrite packet)
        {
            var complete = Path.Combine(inbox, packet.MediaName);
            var temporary = Path.Combine(inbox, "." + packet.MediaName + ".tmp");
            try {
                if (!File.Exists(complete)) {
                    if (Directory.EnumerateFiles(inbox, "media-*.png").Take(512).Count() >= 512) {
                        Interlocked.Increment(ref writeFailures);
                        return;
                    }
                    using (var stream = new FileStream(temporary, FileMode.Create, FileAccess.Write, FileShare.None)) {
                        stream.Write(packet.Media, 0, packet.Media.Length);
                        stream.Flush(true);
                    }
                    File.Move(temporary, complete);
                }
                committed.Enqueue(packet);
            } catch {
                Interlocked.Increment(ref writeFailures);
                try { File.Delete(temporary); } catch { }
            }
        }
    }
}
