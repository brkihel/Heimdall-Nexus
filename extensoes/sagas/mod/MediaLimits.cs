using System;
using System.Linq;
using System.Security.Cryptography;

namespace Heimdall.Sagas.Mod
{
    // Shared by client and bridge: what an item icon or a character portrait may
    // be. Both sides check; the Nexus importer checks again before anything is
    // served.
    internal static class MediaLimits
    {
        internal const int ChunkBytes = 60 * 1024;
        internal const int IconBytes = 48 * 1024;
        internal const int PortraitBytes = 1024 * 1024;
        internal const int IconSide = 128;
        internal const int PortraitWidth = 1024;
        internal const int PortraitHeight = 1536;
        private static readonly byte[] Signature = { 137, 80, 78, 71, 13, 10, 26, 10, 0, 0, 0, 13, 73, 72, 68, 82 };

        internal static bool IsKind(string kind) => kind == "icon" || kind == "portrait";

        internal static int MaximumBytes(string kind) => kind == "portrait" ? PortraitBytes : IconBytes;

        internal static bool IsId(string value) =>
            value != null && value.Length == 64 && value.All(c => c >= '0' && c <= '9' || c >= 'a' && c <= 'f');

        internal static string Hash(byte[] bytes)
        {
            using (var sha = SHA256.Create())
                return BitConverter.ToString(sha.ComputeHash(bytes)).Replace("-", "").ToLowerInvariant();
        }

        internal static bool Valid(string kind, string id, byte[] png)
        {
            if (!IsKind(kind) || !IsId(id) || png == null || png.Length < 33 || png.Length > MaximumBytes(kind))
                return false;
            for (int i = 0; i < Signature.Length; i++) if (png[i] != Signature[i]) return false;
            long width = 0, height = 0;
            for (int i = 16; i < 20; i++) width = width * 256 + png[i];
            for (int i = 20; i < 24; i++) height = height * 256 + png[i];
            var fits = kind == "portrait"
                ? width <= PortraitWidth && height <= PortraitHeight
                : width <= IconSide && height <= IconSide;
            return width >= 1 && height >= 1 && fits && Hash(png) == id;
        }
    }
}
