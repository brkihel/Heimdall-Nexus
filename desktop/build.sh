#!/usr/bin/env bash
# Builds the Windows desktop app and the source package it installs.
#
#   desktop/build.sh [tag]        (default: v$(cat deploy/VERSION))
#
# Writes to dist/windows/:
#   HeimdallNexus-<version>-source.zip   git archive of the tag (deploy/COMMIT holds its commit)
#   HeimdallNexus-<version>.exe          the app, which downloads that zip from the tag's release
#                                        and checks it against the SHA-256 built into it
# Upload both to the GitHub release of the tag.
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TAG="${1:-v$(tr -d '[:space:]' < "$ROOT/deploy/VERSION")}"
VERSION="${TAG#v}"
OUT="$ROOT/dist/windows"
mkdir -p "$OUT"
git -C "$ROOT" rev-parse -q --verify "$TAG^{commit}" >/dev/null || { echo "Tag $TAG does not exist." >&2; exit 2; }

SOURCE="$OUT/HeimdallNexus-$VERSION-source.zip"
git -C "$ROOT" archive --format=zip --prefix="HeimdallNexus-$VERSION/" -o "$SOURCE" "$TAG"
SHA="$(sha256sum "$SOURCE" | cut -d' ' -f1)"
URL="https://github.com/brkihel/Heimdall-Nexus/releases/download/$TAG/HeimdallNexus-$VERSION-source.zip"

BUILD="$(mktemp -d)"
trap 'rm -rf "$BUILD"' EXIT
cp -r "$ROOT/desktop/HeimdallNexus.Desktop/." "$BUILD/"
rm -rf "$BUILD/bin" "$BUILD/obj"
cat > "$BUILD/BuildInfo.cs" <<CS
namespace HeimdallNexus.Desktop
{
    static class BuildInfo
    {
        public const string Version = "$VERSION";
        public const string SourceUrl = "$URL";
        public const string SourceSha256 = "$SHA";
    }
}
CS
NUMERIC="$(sed -E 's/^([0-9]+\.[0-9]+\.[0-9]+).*/\1/' <<< "$VERSION")"
dotnet build "$BUILD/HeimdallNexus.Desktop.csproj" -c Release -nologo -v quiet \
  -p:Version="$NUMERIC" -p:InformationalVersion="$VERSION" -o "$BUILD/out"
cp "$BUILD/out/HeimdallNexus.exe" "$OUT/HeimdallNexus-$VERSION.exe"
echo "source: $SOURCE ($SHA)"
echo "app:    $OUT/HeimdallNexus-$VERSION.exe"
