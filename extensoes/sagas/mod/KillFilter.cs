using System;

namespace Heimdall.Sagas.Mod
{
    internal static class KillFilter
    {
        // Stable prefab identities, independent of localized display names.
        private static readonly int[] ElitePrefabs = {
            "Greydwarf_Elite".GetStableHashCode(), // Greydwarf Brute
            "Draugr_Elite".GetStableHashCode(),   // Draugr Elite
            "GoblinBrute".GetStableHashCode(),    // Fuling Berserker
            "SeekerBrute".GetStableHashCode()     // Seeker Soldier
        };

        internal static bool IsElite(ZNetView view)
        {
            var zdo = view?.GetZDO();
            if (zdo == null) return false;
            var prefab = zdo.GetPrefab();
            foreach (var elite in ElitePrefabs)
                if (prefab == elite) return true;
            return false;
        }

        internal static string Normalize(string mode) =>
            mode == "notable" || mode == "bosses" ? mode : "all";

        internal static bool Keep(string mode, bool boss, bool elite, int stars) =>
            mode == "all" || boss || mode == "notable" && (elite || stars >= 3);
    }
}
