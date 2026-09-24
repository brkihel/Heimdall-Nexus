// Cartography layers for the Birds Eye world map, computed on the server once
// per world, with no client and no render target. Palette, ocean, mist and
// forest formulas follow NomapPrinter by shudnal (Unlicense), commit
// b923b15b9fbc23bcee4a0f8c6b76c438c8d28182. Rows run south to north.
using System;
using System.IO;
using System.Reflection;
using System.Threading;
using UnityEngine;

namespace Heimdall.Sagas.Mod
{
    internal static class Cartography
    {
        public const int Size = 4096;
        public const float PixelSize = 6f;
        private const float WorldRadius = 10500f;
        private static readonly Color32 Lava = new Color32(205, 51, 15, 255);
        private static readonly Color32 North = new Color32(170, 173, 194, 255);
        private static readonly Color32 Mist = new Color32(217, 140, 166, 255);
        private static float northOffset, northDistance;

        private static float Constant(string name)
        {
            var field = typeof(WorldGenerator).GetField(name,
                BindingFlags.Static | BindingFlags.NonPublic | BindingFlags.Public);
            if (field == null) throw new MissingFieldException("WorldGenerator", name);
            return Convert.ToSingle(field.GetRawConstantValue());
        }

        public static readonly string[] Layers = { "base.rgb", "height.rg", "abyss.r8", "paper.r8" };

        // Writes base colour, height, outside-the-world and paper-veil layers as
        // "<prefix><layer>" files, each through a temporary name.
        public static void Export(WorldGenerator generator, string prefix)
        {
            northOffset = Constant("deepNorthYOffset");
            northDistance = Constant("deepNorthMinDistance");
            var rgb = new byte[Size * Size * 3];
            var heights = new byte[Size * Size * 2];
            var abyss = new byte[Size * Size];
            var paper = new byte[Size * Size];
            var next = -1;
            Exception error = null;
            var workers = new Thread[Math.Max(1, Math.Min(Environment.ProcessorCount - 1, 4))];
            for (var t = 0; t < workers.Length; t++) {
                workers[t] = new Thread(() => {
                    try {
                        int row;
                        while ((row = Interlocked.Increment(ref next)) < Size)
                            Fill(generator, row, rgb, heights, abyss, paper);
                    } catch (Exception e) { Interlocked.CompareExchange(ref error, e, null); }
                }) { IsBackground = true, Priority = System.Threading.ThreadPriority.BelowNormal };
                workers[t].Start();
            }
            foreach (var worker in workers) worker.Join();
            if (error != null) throw new Exception("cartography export failed", error);
            var data = new[] { rgb, heights, abyss, paper };
            for (var layer = 0; layer < Layers.Length; layer++) {
                var temporary = Path.Combine(Path.GetDirectoryName(prefix),
                    "." + Path.GetFileName(prefix) + Layers[layer] + ".tmp");
                using (var output = new FileStream(temporary, FileMode.Create, FileAccess.Write, FileShare.None)) {
                    output.Write(data[layer], 0, data[layer].Length);
                    output.Flush(true);
                }
                if (File.Exists(prefix + Layers[layer])) File.Delete(prefix + Layers[layer]);
                File.Move(temporary, prefix + Layers[layer]);
            }
        }

        private static Color Palette(Heightmap.Biome biome)
        {
            switch (biome) {
                case Heightmap.Biome.Meadows: return new Color(.573f, .655f, .361f);
                case Heightmap.Biome.AshLands: return new Color(.48f, .125f, .125f);
                case Heightmap.Biome.BlackForest: return new Color(.42f, .455f, .247f);
                case Heightmap.Biome.DeepNorth: return new Color(.85f, .85f, 1f);
                case Heightmap.Biome.Plains: return new Color(.906f, .671f, .47f);
                case Heightmap.Biome.Swamp: return new Color(.639f, .447f, .345f);
                case Heightmap.Biome.Mistlands: return new Color(.3f, .2f, .3f);
                case Heightmap.Biome.Ocean: return Color.blue;
                default: return Color.white;
            }
        }

        private static float MistNoise(float x, float y) =>
            (Mathf.PerlinNoise(x, y) + .5f * Mathf.PerlinNoise(2 * x, 2 * y) +
             .25f * Mathf.PerlinNoise(4 * x, 4 * y) + .125f * Mathf.PerlinNoise(8 * x, 8 * y)) / 1.875f;

        private static void Fill(WorldGenerator gen, int row, byte[] rgb, byte[] heights, byte[] abyss, byte[] paper)
        {
            var z = (row - Size / 2) * PixelSize + PixelSize / 2;
            for (var col = 0; col < Size; col++) {
                var x = (col - Size / 2) * PixelSize + PixelSize / 2;
                var i = row * Size + col;
                // The explored-area veil, drawn at 20 % over the finished map.
                var veil = (Mathf.PerlinNoise(row / 128f, col / 128f) - .5f) / 16f + .5f;
                paper[i] = ((Color32)new Color(veil, veil, veil, .2f)).r;
                if (x * x + z * z > WorldRadius * WorldRadius) { abyss[i] = 1; continue; }
                var biome = gen.GetBiome(x, z);
                var height = gen.GetBiomeHeight(biome, x, z, out _);
                if (height < -100f) { abyss[i] = 1; continue; }
                var h = height - 30f;
                Color32 encoded = h > 0 ? new Color(h / 512f, 0, 0)
                    : new Color(0, 0, -h / (biome == Heightmap.Biome.Swamp ? 512f : 256f));
                heights[2 * i] = encoded.r;
                heights[2 * i + 1] = encoded.b;
                Color32 color = Palette(biome);
                if (encoded.b > 0) {
                    int a = row / 16 - 128, b = col / 16 - 128, c = a * a / 128 + b * b / 512;
                    var alpha = (byte)Math.Min(encoded.b * 16 + 128, 255);
                    var ocean = a < 0 ? new Color32((byte)(10 + c), (byte)(136 - c / 4), 193, alpha)
                                      : new Color32((byte)(10 + c / 2), 136, (byte)(193 - c / 2), alpha);
                    if (biome == Heightmap.Biome.Ocean) ocean = Color32.Lerp(ocean, new Color32(20, 100, 255, 255), .1f);
                    Color noisy = ocean;
                    var sample = (Mathf.PerlinNoise(row / 4f, col / 4f) - .5f) / 64f;
                    noisy.r += sample; noisy.g += sample; noisy.b += sample;
                    ocean = noisy;
                    color = Color.Lerp(color, ocean, ocean.a / 255f);
                }
                color.r = (byte)Math.Max(color.r - 20, 0);
                color.g = (byte)Math.Max(color.g - 20, 0);
                color.b = (byte)Math.Max(color.b - 20, 0);
                if (h <= 0) {
                    var gradient = Mathf.Clamp01(WorldGenerator.GetAshlandsOceanGradient(x, z)) * .25f;
                    if (gradient > 0) color = Color32.Lerp(color, Lava, gradient);
                    else {
                        var angle = WorldGenerator.WorldAngle(x, z + northOffset) * 100.0;
                        var north = (float)((DUtils.Length(x, z + northOffset) - (northDistance + angle)) / 300.0);
                        gradient = Mathf.Clamp01(north) * .5f;
                        if (gradient > 0) color = Color32.Lerp(color, North, gradient);
                    }
                } else {
                    float forest = 0;
                    if (biome == Heightmap.Biome.Meadows) forest = WorldGenerator.InForest(new Vector3(x, 0, z)) ? 1 : 0;
                    if (biome == Heightmap.Biome.Plains) forest = WorldGenerator.GetForestFactor(new Vector3(x, 0, z)) < .8f ? 1 : 0;
                    if (biome == Heightmap.Biome.BlackForest) forest = .75f;
                    if (forest > 0) {
                        var f = 1 - .1f * forest;
                        color.r = (byte)(color.r * f); color.g = (byte)(color.g * f); color.b = (byte)(color.b * f);
                    }
                    if (biome == Heightmap.Biome.Mistlands) {
                        var mask = 1 - Utils.SmoothStep(1.1f, 1.3f, WorldGenerator.GetForestFactor(new Vector3(x, 0, z)));
                        color = Color32.Lerp(color, Mist, mask * MistNoise((col / (float)Size - .5f) * 400,
                                                                           (row / (float)Size - .5f) * 400) * .9f);
                    }
                    if (biome == Heightmap.Biome.AshLands) {
                        gen.GetAshlandsHeight(x, z, out Color ash, cheap: true);
                        color = Color32.Lerp(color, Lava, ash.a);
                    }
                }
                rgb[3 * i] = color.r; rgb[3 * i + 1] = color.g; rgb[3 * i + 2] = color.b;
            }
        }
    }
}
