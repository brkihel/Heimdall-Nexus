using System;

namespace Heimdall.Sagas.Mod
{
#pragma warning disable CS0649 // Fields are also populated by JsonUtility.
    [Serializable]
    internal sealed class Stat
    {
        public string name = "";
        public float value;
    }

    [Serializable]
    internal sealed class GemSocket
    {
        public string name = "";
        public string icon = "";
        public string[] effects = Array.Empty<string>();
    }

    [Serializable]
    internal sealed class GearItem
    {
        public string name = "";
        public string slot = "";
        public int quality;
        public float durability;
        // Profile page details (protocol 1 readers ignore missing fields).
        public string prefab = "";
        public string type = "";
        public float max_durability;
        public bool equipped;
        public bool active;
        public int hotbar;
        public string icon = "";
        public Stat[] stats = Array.Empty<Stat>();
        public string[] effects = Array.Empty<string>();
        public string socket_color = "";
        public GemSocket[] sockets = Array.Empty<GemSocket>();
    }

    // Flat payloads keep Unity's built-in JSON serializer sufficient. The bridge
    // replaces world, actor and player name with values obtained from Valheim.
    [Serializable]
    internal sealed class WirePacket
    {
        public int version = 1;
        public string type = "";
        public string world = "";
        public string world_name = "";
        public string actor = "";
        public string id = "";
        public string kind = "";
        public string name = "";
        public string target = "";
        public int stars;
        public bool boss;
        public bool elite;
        public string biome = "";
        public int quantity = 1;
        public bool online;
        public bool share_profile;
        public bool share_stories;
        public bool share_map;
        public bool share_position;
        public bool has_location;
        public float x;
        public float z;
        public int day;
        public float fraction;
        public long utc;
        public GearItem[] gear = Array.Empty<GearItem>();
        public GearItem[] hotbar = Array.Empty<GearItem>();
        public string portrait = "";
        public Stat[] vitals = Array.Empty<Stat>();
    }
#pragma warning restore CS0649
}
