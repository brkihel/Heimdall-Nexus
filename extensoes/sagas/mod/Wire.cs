using Newtonsoft.Json;

namespace Heimdall.Sagas.Mod
{
    // Packets go through the game's own Newtonsoft.Json. Unity's JsonUtility
    // silently drops arrays of plugin classes (gear, hotbar, vitals).
    internal static class Wire
    {
        private static readonly JsonSerializerSettings Settings = new JsonSerializerSettings {
            MaxDepth = 8, TypeNameHandling = TypeNameHandling.None,
            MissingMemberHandling = MissingMemberHandling.Ignore
        };

        internal static string Write(WirePacket packet) => JsonConvert.SerializeObject(packet, Settings);

        internal static WirePacket Read(string json)
        {
            try { return JsonConvert.DeserializeObject<WirePacket>(json, Settings); }
            catch (JsonException) { return null; }
        }
    }
}
