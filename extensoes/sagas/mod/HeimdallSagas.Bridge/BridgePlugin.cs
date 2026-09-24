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
    [BepInPlugin("gg.heimdall.sagas.bridge", "Heimdall Sagas Bridge", "0.1.3")]
    public sealed class BridgePlugin : BaseUnityPlugin
    {
        private const string Rpc = "Heimdall.Sagas.V1";
        private const string Hello = "Heimdall.Sagas.Hello.V1";
        private const string Probe = "Heimdall.Sagas.Probe.V1";
        private const string Ack = "Heimdall.Sagas.Ack.V1";
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
        }
        private sealed class PendingWrite
        {
            internal string Json;
            internal ZRpc ReplyTo;
            internal string EventId;
        }
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

        private void Awake()
        {
            inbox = Environment.GetEnvironmentVariable("HEIMDALL_SAGAS_INBOX");
            settingsPath = Environment.GetEnvironmentVariable("HEIMDALL_SAGAS_SETTINGS");
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
                    done.ReplyTo.Invoke(Ack, done.EventId);
            }
            var peers = ZNet.instance.GetPeers().Where(p => p.IsReady()).ToArray();
            var live = new HashSet<ZRpc>(peers.Select(p => p.m_rpc));
            foreach (var peer in peers) {
                if (registered.Add(peer.m_rpc)) {
                    var owner = peer;
                    peer.m_rpc.Register<string>(Rpc, (rpc, data) => Receive(owner, rpc, data));
                    peer.m_rpc.Register<string>(Probe, (rpc, version) => {
                        if (rpc == owner.m_rpc && owner.IsReady() && version == "1")
                            rpc.Invoke(Hello, "1:" + (settings.gear ? "g" : "") +
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
            if (settings.enabled && settings.clock && EnvMan.instance != null &&
                Time.unscaledTime >= nextClock) {
                nextClock = Time.unscaledTime + 30f;
                Enqueue(new WirePacket { type = "clock", world = WorldId(),
                    world_name = SafeName(ZNet.instance.GetWorldName()),
                    day = EnvMan.instance.GetDay(), fraction = EnvMan.instance.GetDayFraction() });
            }
            var failures = Interlocked.Exchange(ref writeFailures, 0);
            if (failures > 0) Logger.LogWarning("Heimdall Sagas could not store " + failures + " packet(s).");
        }

        private void Receive(ZNetPeer peer, ZRpc rpc, string data)
        {
            if (ZNet.instance == null || !ZNet.instance.IsServer() || peer.m_rpc != rpc ||
                !peer.IsReady() || data == null || data.Length > 8192) return;
            if (nextPacket.TryGetValue(rpc, out var next) && Time.unscaledTime < next) return;
            nextPacket[rpc] = Time.unscaledTime + .2f;
            if (!TryPlayerId(peer, out var playerId)) {
                if (Time.unscaledTime >= nextIdentityWarning) {
                    nextIdentityWarning = Time.unscaledTime + 60f;
                    Logger.LogWarning("Heimdall Sagas received a client packet but could not yet verify the player's character identity.");
                }
                return;
            }
            WirePacket packet;
            try { packet = JsonUtility.FromJson<WirePacket>(data); }
            catch (ArgumentException) { return; }
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
                packet.share_position &= peer.m_publicRefPos;
                if (!packet.share_position) packet.x = packet.z = 0;
                packet.gear = packet.share_profile && settings.gear
                    ? (packet.gear ?? Array.Empty<GearItem>()).Where(g => g != null).Take(32).ToArray()
                    : Array.Empty<GearItem>();
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
            if (!queue.TryAdd(new PendingWrite { Json = JsonUtility.ToJson(packet),
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
    }
}
