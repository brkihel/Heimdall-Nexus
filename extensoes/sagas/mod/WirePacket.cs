using System;

namespace Heimdall.Sagas.Mod
{
#pragma warning disable CS0649 // Fields are also populated by JsonUtility.
    [Serializable]
    internal sealed class GearItem
    {
        public string name = "";
        public string slot = "";
        public int quality;
        public float durability;
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
        public int quantity = 1;
        public bool online;
        public bool share_profile;
        public bool share_map;
        public bool share_position;
        public bool has_location;
        public float x;
        public float z;
        public int day;
        public float fraction;
        public long utc;
        public GearItem[] gear = Array.Empty<GearItem>();
    }
#pragma warning restore CS0649
}
