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
    [BepInPlugin("gg.heimdall.sagas.client", "Heimdall Sagas Client", "0.2.1")]
    public sealed class ClientPlugin : BaseUnityPlugin
    {
        private const string Rpc = "Heimdall.Sagas.V1";
        private const string Hello = "Heimdall.Sagas.Hello.V1";
        private const string Probe = "Heimdall.Sagas.Probe.V1";
        private const string Ack = "Heimdall.Sagas.Ack.V1";
        private const string MediaRpc = "Heimdall.Sagas.Media.V1";
        private const string MediaAck = "Heimdall.Sagas.MediaAck.V1";
        private static ClientPlugin current;
        private ConfigEntry<bool> shareProfile;
        private ConfigEntry<bool> shareMap;
        private ConfigEntry<bool> sharePosition;
        private ConfigEntry<bool> shareStories;
        private ConfigEntry<bool> portraitEnabled;
        private ConfigEntry<KeyboardShortcut> portraitKey;
        private ConfigEntry<float> portraitAmbient, portraitKeyLight, portraitFill, portraitReflection,
                                   portraitFieldOfView, portraitAngle;
        private RuntimeArt art;
        private bool bridgeMedia;
        private string currentWorld = "";
        private float nextWorldCheck;
        // Item icons and the portrait wait here until the bridge confirms them;
        // only confirmed ids are named in presence packets.
        private readonly Dictionary<string, (string Kind, byte[] Png)> media =
            new Dictionary<string, (string, byte[])>();
        private readonly HashSet<string> mediaStored = new HashSet<string>();
        private string mediaSending = "";
        private int mediaCursor;
        private float mediaWaitUntil, nextMediaPump;
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
                "Allow your Viking name and selected shared events to be sent to the AI provider chosen by the server admin (OpenRouter, OpenAI, Anthropic or Google Gemini) to write public AI stories. Requires ShareProfile.");
            portraitEnabled = Config.Bind("Portrait", "Enabled", true,
                "Show a picture of your Viking and equipment on the profile page. Requires ShareProfile.");
            portraitKey = Config.Bind("Portrait", "RefreshKey", new KeyboardShortcut(KeyCode.F9),
                "Take the portrait again now, for example after changing the values below.");
            portraitAmbient = Config.Bind("Portrait", "Ambient", .62f,
                new ConfigDescription("Soft light over the whole Viking.", new AcceptableValueRange<float>(0f, 1.5f)));
            portraitKeyLight = Config.Bind("Portrait", "KeyLight", .8f,
                new ConfigDescription("Main light from the front and above.", new AcceptableValueRange<float>(0f, 3f)));
            portraitFill = Config.Bind("Portrait", "FillLight", .35f,
                new ConfigDescription("Light from the other side, softening shadows.", new AcceptableValueRange<float>(0f, 3f)));
            portraitReflection = Config.Bind("Portrait", "Reflection", .65f,
                new ConfigDescription("Shine on metal armor.", new AcceptableValueRange<float>(0f, 2f)));
            portraitFieldOfView = Config.Bind("Portrait", "FieldOfView", 12f,
                new ConfigDescription("Camera lens; lower looks flatter.", new AcceptableValueRange<float>(6f, 40f)));
            portraitAngle = Config.Bind("Portrait", "CameraAngle", .2f,
                new ConfigDescription("Turn of the camera around the Viking; 0 is straight ahead.", new AcceptableValueRange<float>(-1f, 1f)));
            art = new RuntimeArt((what, error) => Logger.LogWarning("Heimdall Sagas " + what + ": " + error.Message)) {
                World = () => currentWorld
            };
            ApplyPortraitStyle();
            // Any studio change retakes the portrait at once: no rebuild to see it.
            foreach (var entry in new[] { portraitAmbient, portraitKeyLight, portraitFill, portraitReflection,
                                          portraitFieldOfView, portraitAngle })
                entry.SettingChanged += (_, __) => { ApplyPortraitStyle(); art.ForceRefresh(); };
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
                        var packet = Wire.Read(File.ReadAllText(path));
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

        private void OnDestroy()
        {
            art?.Clear();
            harmony?.UnpatchSelf();
            if (current == this) current = null;
        }

        private void ApplyPortraitStyle()
        {
            art.Style = new PortraitStyle {
                Ambient = portraitAmbient.Value, Key = portraitKeyLight.Value, Fill = portraitFill.Value,
                Reflection = portraitReflection.Value, FieldOfView = portraitFieldOfView.Value,
                SideAngle = portraitAngle.Value
            };
        }

        private bool ArtAllowed => shareProfile.Value && bridgeMedia && Time.unscaledTime < bridgeUntil;

        private void ClearMedia()
        {
            media.Clear();
            mediaStored.Clear();
            mediaSending = "";
            mediaCursor = 0;
            art?.Clear();
        }

        // Returns the id to name in a presence packet: only once the bridge has it.
        private string Queue(RuntimeArt.Image image)
        {
            if (image == null || !MediaLimits.Valid(image.Kind, image.Id, image.Png)) return "";
            if (mediaStored.Contains(image.Id)) return image.Id;
            if (image.Kind == "portrait")
                foreach (var old in media.Where(m => m.Value.Kind == "portrait" && m.Key != image.Id)
                                         .Select(m => m.Key).ToArray()) {
                    media.Remove(old);
                    if (mediaSending == old) mediaSending = "";
                }
            if (!media.ContainsKey(image.Id) && media.Count < 64) media[image.Id] = (image.Kind, image.Png);
            return "";
        }

        private void PumpMedia(ZNetPeer server)
        {
            if (!ArtAllowed || Time.unscaledTime < nextMediaPump) return;
            nextMediaPump = Time.unscaledTime + .1f;
            if (mediaSending == "" || !media.ContainsKey(mediaSending)) {
                // Icons first: they are small and make the page useful quickly.
                mediaSending = media.OrderBy(m => m.Value.Kind == "portrait" ? 1 : 0).Select(m => m.Key)
                                    .FirstOrDefault() ?? "";
                mediaCursor = 0;
                mediaWaitUntil = 0;
            }
            if (mediaSending == "") return;
            var (kind, png) = media[mediaSending];
            var chunks = (png.Length + MediaLimits.ChunkBytes - 1) / MediaLimits.ChunkBytes;
            if (mediaCursor >= chunks) {
                // Everything was sent: wait for the bridge, then start over.
                if (Time.unscaledTime < mediaWaitUntil) return;
                mediaCursor = 0;
            }
            for (int sent = 0; sent < 2 && mediaCursor < chunks; sent++, mediaCursor++) {
                var length = Math.Min(MediaLimits.ChunkBytes, png.Length - mediaCursor * MediaLimits.ChunkBytes);
                var data = new byte[length];
                Array.Copy(png, mediaCursor * MediaLimits.ChunkBytes, data, 0, length);
                var package = new ZPackage();
                package.Write(kind);
                package.Write(mediaSending);
                package.Write(png.Length);
                package.Write(mediaCursor);
                package.Write(data);
                server.m_rpc.Invoke(MediaRpc, package);
            }
            if (mediaCursor >= chunks) mediaWaitUntil = Time.unscaledTime + 20f;
        }

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
            if (!shareProfile.Value && (media.Count != 0 || mediaStored.Count != 0)) ClearMedia();
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
                if (registeredServer != null) ClearMedia();
                registeredServer = null; bridgeUntil = 0; bridgeGear = bridgeEvents = bridgeMedia = false;
                bridgeKillMode = "all";
                sentPresence = false; return;
            }
            if (server.m_rpc != registeredServer) {
                registeredServer = server.m_rpc;
                sentPresence = false;
                bridgeUntil = 0;
                bridgeGear = bridgeEvents = bridgeMedia = false;
                bridgeKillMode = "all";
                nextProbe = 0;
                ClearMedia();
                registeredServer.Register<string>(Hello, (rpc, version) => {
                    if (rpc == registeredServer && version != null && version.StartsWith("1:",
                        StringComparison.Ordinal)) {
                        bridgeUntil = Time.unscaledTime + 45f;
                        bridgeGear = version.IndexOf('g') >= 0;
                        bridgeEvents = version.IndexOf('e') >= 0;
                        bridgeMedia = bridgeGear && version.IndexOf('m') >= 0;
                        var separator = version.LastIndexOf(':');
                        bridgeKillMode = separator < 0 ? "all" :
                            version.Substring(separator + 1) == "n" ? "notable" :
                            version.Substring(separator + 1) == "b" ? "bosses" : "all";
                        if (!bridgeEvents) ClearPending();
                        else RemoveFilteredPending();
                        nextPresence = 0;
                    }
                });
                registeredServer.Register<string>(MediaAck, (rpc, id) => {
                    if (rpc != registeredServer || id == null || !media.TryGetValue(id, out var stored)) return;
                    media.Remove(id);
                    if (mediaStored.Count >= 256) mediaStored.Clear();
                    mediaStored.Add(id);
                    if (mediaSending == id) mediaSending = "";
                    // A new portrait appears on the site without waiting half a minute.
                    if (stored.Kind == "portrait") nextPresence = Math.Min(nextPresence, Time.unscaledTime + 1f);
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
            if (Time.unscaledTime >= nextWorldCheck) {
                nextWorldCheck = Time.unscaledTime + 3f;
                currentWorld = WorldId();
            }
            var local = Player.m_localPlayer;
            art.PumpPortrait(local, ArtAllowed && portraitEnabled.Value, currentWorld);
            art.PumpIcons(ArtAllowed);
            if (local != null && portraitKey.Value.IsDown() && ArtAllowed && portraitEnabled.Value) {
                art.ForceRefresh();
                local.Message(MessageHud.MessageType.TopLeft, "Heimdall: retrato sendo refeito");
            }
            PumpMedia(server);
            if (Time.unscaledTime < nextPresence) return;
            nextPresence = Time.unscaledTime + (consentRepeats > 0 ? 5f : 30f);
            var player = Player.m_localPlayer;
            if (player == null || ZNet.instance == null || ZNet.instance.IsServer() ||
                Time.unscaledTime >= bridgeUntil) return;
            var visible = sharePosition.Value && ZNet.instance.IsReferencePositionPublic();
            var optedOut = !shareProfile.Value && !shareMap.Value && !sharePosition.Value;
            var profile = shareProfile.Value && bridgeGear;
            string Icon(ItemDrop.ItemData item) => ArtAllowed ? Queue(art.TryIcon(item)) : "";
            Send(new WirePacket {
                type = optedOut ? "withdraw" : "presence",
                name = optedOut ? "" : player.GetPlayerName(), online = !optedOut,
                share_profile = shareProfile.Value, share_map = shareMap.Value,
                share_stories = shareProfile.Value && shareStories.Value,
                share_position = visible, x = visible ? player.transform.position.x : 0,
                z = visible ? player.transform.position.z : 0,
                gear = profile ? (bridgeMedia ? Equipped(player, Icon) : Legacy(Equipped(player, Icon)))
                               : Array.Empty<GearItem>(),
                hotbar = profile && bridgeMedia ? Hotbar(player, Icon) : Array.Empty<GearItem>(),
                portrait = profile && ArtAllowed && portraitEnabled.Value
                    ? Queue(art.TryPortrait(player, !media.Values.Any(m => m.Kind == "portrait"))) : "",
                vitals = profile && bridgeMedia ? Vitals(player) : Array.Empty<Stat>()
            });
            if (consentRepeats > 0) consentRepeats--;
            sentPresence = true;
        }

        private GearItem[] Equipped(Player player, Func<ItemDrop.ItemData, string> icon)
        {
            try {
                return JewelcraftingAdapter.Equipped(player).Where(item => item != null && item.m_shared != null)
                    .Take(24).Select(item => GearReader.Read(item, player, icon)).ToArray();
            } catch (Exception error) {
                Logger.LogWarning("Heimdall Sagas could not read equipment: " + error.Message);
                return Array.Empty<GearItem>();
            }
        }

        // Bridges before 0.2.0 drop presence packets over 8 KiB: send them only
        // what they knew (name, slot, quality, durability).
        private static GearItem[] Legacy(GearItem[] items) => items.Select(g => new GearItem {
            name = g.name, slot = g.slot, quality = g.quality, durability = g.durability }).ToArray();

        private GearItem[] Hotbar(Player player, Func<ItemDrop.ItemData, string> icon)
        {
            try { return GearReader.Hotbar(player, icon); }
            catch (Exception error) {
                Logger.LogWarning("Heimdall Sagas could not read the hotbar: " + error.Message);
                return Array.Empty<GearItem>();
            }
        }

        private static Stat[] Vitals(Player player) => new[] {
            new Stat { name = "Health", value = player.GetMaxHealth() },
            new Stat { name = "Stamina", value = player.GetMaxStamina() },
            new Stat { name = "Eitr", value = player.GetMaxEitr() },
            new Stat { name = "Armor", value = player.GetBodyArmor() }
        }.Where(v => !float.IsNaN(v.value) && !float.IsInfinity(v.value)).ToArray();

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
                    writer.Write(Wire.Write(packet));
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
            peer.m_rpc.Invoke(Rpc, Wire.Write(packet));
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
