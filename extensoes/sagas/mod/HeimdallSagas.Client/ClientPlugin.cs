using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Reflection;
using System.Security.Cryptography;
using System.Text;
using BepInEx;
using BepInEx.Configuration;
using HarmonyLib;
using UnityEngine;

namespace Heimdall.Sagas.Mod
{
    [BepInPlugin("gg.heimdall.sagas.client", "Heimdall Sagas Client", "0.1.4")]
    public sealed class ClientPlugin : BaseUnityPlugin
    {
        private const string Rpc = "Heimdall.Sagas.V1";
        private const string Hello = "Heimdall.Sagas.Hello.V1";
        private const string Probe = "Heimdall.Sagas.Probe.V1";
        private const string Ack = "Heimdall.Sagas.Ack.V1";
        private static ClientPlugin current;
        private ConfigEntry<bool> shareProfile;
        private ConfigEntry<bool> shareMap;
        private ConfigEntry<bool> sharePosition;
        private ConfigEntry<bool> shareStories;
        private Harmony harmony;
        private float nextPresence;
        private float bridgeUntil;
        private bool bridgeGear;
        private bool bridgeEvents;
        private string bridgeKillMode = "all";
        private float nextProbe;
        private float nextRetry;
        private bool lastProfile, lastMap, lastPosition, lastStories;
        private int consentRepeats;
        private bool sentPresence;
        private ZRpc registeredServer;
        private string outbox;
        private readonly Dictionary<string, WirePacket> pending = new Dictionary<string, WirePacket>();
        private static readonly FieldInfo lastHit = AccessTools.Field(typeof(Character), "m_lastHit");

        private void Awake()
        {
            current = this;
            shareProfile = Config.Bind("Privacy", "ShareProfile", false,
                "Allow this server's Heimdall site to show your profile and recorded events.");
            shareMap = Config.Bind("Privacy", "ShareMap", false,
                "Allow shared exploration and event locations on the Heimdall atlas.");
            sharePosition = Config.Bind("Privacy", "SharePosition", false,
                "Allow a live marker when Valheim's own map visibility is also enabled.");
            shareStories = Config.Bind("Privacy", "ShareStories", false,
                "Allow your Viking name and selected shared events to be sent to OpenRouter and its selected model provider for public AI stories. Requires ShareProfile.");
            lastProfile = shareProfile.Value;
            lastMap = shareMap.Value;
            lastPosition = sharePosition.Value;
            lastStories = shareStories.Value;
            outbox = Path.Combine(Paths.ConfigPath, "HeimdallSagas", "outbox");
            try {
                Directory.CreateDirectory(outbox);
                foreach (var path in Directory.EnumerateFiles(outbox, "*.json").Take(256)) {
                    try {
                        if (new FileInfo(path).Length > 8192) continue;
                        var packet = JsonUtility.FromJson<WirePacket>(File.ReadAllText(path));
                        if (packet != null && packet.type == "event" &&
                            (Guid.TryParseExact(packet.id, "N", out _) ||
                             packet.id != null && packet.id.Length == 64 &&
                             packet.id.All(c => c >= '0' && c <= '9' || c >= 'a' && c <= 'f')) &&
                            Path.GetFileNameWithoutExtension(path) == packet.id) pending[packet.id] = packet;
                    } catch (Exception error) { Logger.LogWarning("Skipped a damaged Sagas event: " + error.Message); }
                }
            } catch (Exception error) { Logger.LogWarning("Heimdall Sagas outbox unavailable: " + error.Message); }
            harmony = new Harmony("gg.heimdall.sagas.client");
            harmony.PatchAll();
        }

        private void OnDestroy() { harmony?.UnpatchSelf(); if (current == this) current = null; }

        private void Update()
        {
            if (lastProfile != shareProfile.Value || lastMap != shareMap.Value ||
                lastPosition != sharePosition.Value || lastStories != shareStories.Value) {
                nextPresence = 0;
                consentRepeats = 2;
                sentPresence = false;
                lastProfile = shareProfile.Value;
                lastMap = shareMap.Value;
                lastPosition = sharePosition.Value;
                lastStories = shareStories.Value;
            }
            if (!shareProfile.Value && pending.Count != 0) {
                ClearPending();
            }
            if (!shareMap.Value) {
                foreach (var packet in pending.Values.Where(p => p.has_location)) {
                    packet.has_location = false;
                    packet.x = packet.z = 0;
                    packet.biome = "";
                    Save(packet);
                }
            }
            var server = ZNet.instance?.GetServerPeer();
            if (server == null || !server.IsReady()) {
                registeredServer = null; bridgeUntil = 0; bridgeGear = bridgeEvents = false;
                bridgeKillMode = "all";
                sentPresence = false; return;
            }
            if (server.m_rpc != registeredServer) {
                registeredServer = server.m_rpc;
                sentPresence = false;
                bridgeUntil = 0;
                bridgeGear = bridgeEvents = false;
                bridgeKillMode = "all";
                nextProbe = 0;
                registeredServer.Register<string>(Hello, (rpc, version) => {
                    if (rpc == registeredServer && version != null && version.StartsWith("1:",
                        StringComparison.Ordinal)) {
                        bridgeUntil = Time.unscaledTime + 45f;
                        bridgeGear = version.IndexOf('g') >= 0;
                        bridgeEvents = version.IndexOf('e') >= 0;
                        var separator = version.LastIndexOf(':');
                        bridgeKillMode = separator < 0 ? "all" :
                            version.Substring(separator + 1) == "n" ? "notable" :
                            version.Substring(separator + 1) == "b" ? "bosses" : "all";
                        if (!bridgeEvents) ClearPending();
                        else RemoveFilteredPending();
                        nextPresence = 0;
                    }
                });
                registeredServer.Register<string>(Ack, (rpc, id) => {
                    if (rpc != registeredServer || !pending.Remove(id)) return;
                    try { File.Delete(Path.Combine(outbox, id + ".json")); } catch (IOException) { }
                });
            }
            // Send one consent snapshot after joining. Full opt-out removes
            // a previously shared profile instead of leaving it behind.
            var wantsBridge = shareProfile.Value || shareMap.Value || sharePosition.Value ||
                              shareStories.Value ||
                              pending.Count > 0 || !sentPresence;
            if (wantsBridge && Time.unscaledTime >= nextProbe) {
                nextProbe = Time.unscaledTime + 15f;
                registeredServer.Invoke(Probe, "1");
            }
            if (bridgeEvents && Time.unscaledTime < bridgeUntil && Time.unscaledTime >= nextRetry) {
                nextRetry = Time.unscaledTime + 5f;
                var world = WorldId();
                foreach (var packet in pending.Values.Where(p => p.world == world).Take(2)) {
                    Send(packet);
                }
            }
            if (Time.unscaledTime < nextPresence) return;
            nextPresence = Time.unscaledTime + (consentRepeats > 0 ? 5f : 30f);
            var player = Player.m_localPlayer;
            if (player == null || ZNet.instance == null || ZNet.instance.IsServer() ||
                Time.unscaledTime >= bridgeUntil) return;
            var visible = sharePosition.Value && ZNet.instance.IsReferencePositionPublic();
            var optedOut = !shareProfile.Value && !shareMap.Value && !sharePosition.Value;
            Send(new WirePacket {
                type = optedOut ? "withdraw" : "presence",
                name = optedOut ? "" : player.GetPlayerName(), online = !optedOut,
                share_profile = shareProfile.Value, share_map = shareMap.Value,
                share_stories = shareProfile.Value && shareStories.Value,
                share_position = visible, x = visible ? player.transform.position.x : 0,
                z = visible ? player.transform.position.z : 0,
                gear = shareProfile.Value && bridgeGear ? Equipped(player) : Array.Empty<GearItem>()
            });
            if (consentRepeats > 0) consentRepeats--;
            sentPresence = true;
        }

        private static GearItem[] Equipped(Player player)
        {
            try {
                return player.GetInventory().GetAllItems()
                    .Where(item => item != null && item.m_equipped && item.m_shared != null)
                    .Take(32)
                    .Select(item => new GearItem {
                        name = CleanText(Localization.instance == null ? item.m_shared.m_name :
                            Localization.instance.Localize(item.m_shared.m_name), 120),
                        slot = CleanText(item.m_shared.m_itemType.ToString(), 40),
                        quality = Math.Max(1, Math.Min(1000, item.m_quality)),
                        durability = Math.Max(0, Math.Min(10000, item.m_durability))
                    }).ToArray();
            } catch { return Array.Empty<GearItem>(); }
        }

        private static string CleanText(string value, int length) =>
            new string((value ?? "").Where(c => !char.IsControl(c)).Take(length).ToArray());

        internal static void RecordDeath()
        {
            var p = Player.m_localPlayer;
            if (p == null || ZNet.instance == null || ZNet.instance.IsServer() ||
                current == null || !current.shareProfile.Value || !current.bridgeEvents ||
                Time.unscaledTime >= current.bridgeUntil) return;
            if (current.pending.Count >= 256) {
                current.Logger.LogWarning("Heimdall Sagas outbox is full; check the bridge connection.");
                return;
            }
            var packet = new WirePacket { type = "event", id = Guid.NewGuid().ToString("N"),
                kind = "death", name = p.GetPlayerName(),
                world = WorldId(),
                utc = DateTimeOffset.UtcNow.ToUnixTimeSeconds(),
                has_location = current.shareMap.Value,
                biome = current.shareMap.Value ? BiomeTag.At(p.transform.position) : "",
                x = current.shareMap.Value ? p.transform.position.x : 0,
                z = current.shareMap.Value ? p.transform.position.z : 0 };
            if (packet.world == "" || !current.Save(packet)) return;
            current.pending[packet.id] = packet;
            if (Time.unscaledTime < current.bridgeUntil) Send(packet);
        }

        private static void RecordKill(Character victim)
        {
            var plugin = current;
            var player = Player.m_localPlayer;
            if (plugin == null || player == null || victim is Player || !plugin.shareProfile.Value ||
                !plugin.bridgeEvents || Time.unscaledTime >= plugin.bridgeUntil || lastHit == null)
                return;
            var view = victim.GetComponent<ZNetView>();
            if (view == null || !view.IsValid() || !view.IsOwner()) return;
            var hit = lastHit.GetValue(victim) as HitData;
            if (hit?.GetAttacker() != player) return;
            var zdo = view.GetZDO();
            var world = WorldId();
            if (zdo == null || world == "") return;
            var boss = victim.IsBoss();
            var elite = KillFilter.IsElite(view);
            var stars = Math.Max(0, victim.GetLevel() - 1);
            if (!KillFilter.Keep(plugin.bridgeKillMode, boss, elite, stars)) return;
            var id = KillId(world, zdo.m_uid);
            if (plugin.pending.ContainsKey(id) || plugin.pending.Count >= 256) return;
            var position = victim.transform.position;
            var target = Localization.instance == null ? victim.m_name :
                Localization.instance.Localize(victim.m_name);
            var packet = new WirePacket { type = "event", kind = "kill", id = id,
                world = world, name = player.GetPlayerName(), target = CleanText(target, 120),
                stars = stars, boss = boss, elite = elite,
                utc = DateTimeOffset.UtcNow.ToUnixTimeSeconds(),
                has_location = plugin.shareMap.Value,
                biome = plugin.shareMap.Value ? BiomeTag.At(position) : "",
                x = plugin.shareMap.Value ? position.x : 0,
                z = plugin.shareMap.Value ? position.z : 0 };
            if (!plugin.Save(packet)) return;
            plugin.pending[id] = packet;
            Send(packet);
        }

        private static string KillId(string world, ZDOID creature)
        {
            using (var sha = SHA256.Create()) {
                var bytes = sha.ComputeHash(Encoding.UTF8.GetBytes("kill:" + world + ":" + creature));
                return BitConverter.ToString(bytes).Replace("-", "").ToLowerInvariant();
            }
        }

        private bool Save(WirePacket packet)
        {
            var temp = Path.Combine(outbox, "." + packet.id + ".tmp");
            try {
                Directory.CreateDirectory(outbox);
                var target = Path.Combine(outbox, packet.id + ".json");
                using (var stream = new FileStream(temp, FileMode.Create, FileAccess.Write, FileShare.None))
                using (var writer = new StreamWriter(stream, new UTF8Encoding(false))) {
                    writer.Write(JsonUtility.ToJson(packet));
                    writer.Flush();
                    stream.Flush(true);
                }
                if (File.Exists(target)) File.Replace(temp, target, null);
                else File.Move(temp, target);
                return true;
            } catch (Exception error) {
                Logger.LogWarning("Heimdall Sagas could not keep an event for retry: " + error.Message);
                try { File.Delete(temp); } catch { }
                return false;
            }
        }

        private void ClearPending()
        {
            foreach (var id in pending.Keys.ToArray()) {
                try { File.Delete(Path.Combine(outbox, id + ".json")); } catch (IOException) { }
            }
            pending.Clear();
        }

        private void RemoveFilteredPending()
        {
            foreach (var packet in pending.Values.Where(p => p.kind == "kill" &&
                     !KillFilter.Keep(bridgeKillMode, p.boss, p.elite, p.stars)).ToArray()) {
                pending.Remove(packet.id);
                try { File.Delete(Path.Combine(outbox, packet.id + ".json")); }
                catch (IOException) { }
            }
        }

        private static string WorldId()
        {
            var world = ZNet.instance?.GetWorld();
            if (world == null || world.m_uid == 0) return "";
            using (var sha = SHA256.Create()) {
                return BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(world.m_uid.ToString())))
                    .Replace("-", "").ToLowerInvariant();
            }
        }

        private static void Send(WirePacket packet)
        {
            var peer = ZNet.instance?.GetServerPeer();
            if (peer == null || !peer.IsReady()) return;
            peer.m_rpc.Invoke(Rpc, JsonUtility.ToJson(packet));
        }

        [HarmonyPatch(typeof(Player), "OnDeath")]
        private static class DeathPatch
        {
            private static void Prefix(Player __instance)
            {
                if (__instance == Player.m_localPlayer) RecordDeath();
            }
        }

        [HarmonyPatch(typeof(Character), "OnDeath")]
        private static class KillPatch
        {
            private static void Prefix(Character __instance)
            {
                try { RecordKill(__instance); }
                catch (Exception error) { current?.Logger.LogWarning("Heimdall Sagas could not record a kill: " + error.Message); }
            }
        }
    }
}
