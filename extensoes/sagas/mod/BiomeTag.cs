using UnityEngine;

namespace Heimdall.Sagas.Mod
{
    internal static class BiomeTag
    {
        internal static string At(Vector3 position)
        {
            try {
                return WorldGenerator.instance == null ? "" :
                    Safe(WorldGenerator.instance.GetBiome(position).ToString());
            } catch { return ""; }
        }

        internal static string Safe(string value)
        {
            if (string.IsNullOrEmpty(value) || value == "None" || value.Length > 40) return "";
            foreach (var character in value)
                if (!(character >= 'A' && character <= 'Z') &&
                    !(character >= 'a' && character <= 'z') &&
                    !(character >= '0' && character <= '9') && character != '_') return "";
            return value;
        }
    }
}
