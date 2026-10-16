#!/usr/bin/env bash
# Downloads static ffmpeg + ffprobe for this OS/CPU into build/bin.
#   Linux: johnvansickle.com static builds (GPL)   macOS: osxexperts.net builds (GPL)
# Keep the license files with anything you distribute.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
bin="$root/build/bin"
work="$root/build/_ffmpeg_dl"

if [[ -x "$bin/ffmpeg" && -x "$bin/ffprobe" ]]; then
  echo "FFmpeg already present in $bin"
  exit 0
fi

mkdir -p "$bin"
rm -rf "$work"
mkdir -p "$work"
trap 'rm -rf "$work"' EXIT

arch="$(uname -m)"
case "$(uname -s)" in
  Linux)
    case "$arch" in
      x86_64)         pkg=amd64 ;;
      aarch64|arm64)  pkg=arm64 ;;
      *) echo "Unsupported Linux CPU: $arch" >&2; exit 1 ;;
    esac
    url="https://johnvansickle.com/ffmpeg/releases/ffmpeg-release-${pkg}-static.tar.xz"
    echo "Downloading $url"
    curl -fL --retry 3 -o "$work/ffmpeg.tar.xz" "$url"
    tar -xf "$work/ffmpeg.tar.xz" -C "$work"
    dir="$(find "$work" -maxdepth 1 -type d -name 'ffmpeg-*-static' | head -n 1)"
    [[ -n "$dir" ]] || { echo "Unexpected archive layout" >&2; exit 1; }
    cp "$dir/ffmpeg" "$dir/ffprobe" "$bin/"
    cp "$dir/GPLv3.txt" "$bin/FFMPEG-LICENSE.txt" 2>/dev/null || true
    ;;
  Darwin)
    case "$arch" in
      arm64)  variant=arm ;;
      x86_64) variant=intel ;;
      *) echo "Unsupported macOS CPU: $arch" >&2; exit 1 ;;
    esac
    for tool in ffmpeg ffprobe; do
      url="https://www.osxexperts.net/${tool}7${variant}.zip"
      echo "Downloading $url"
      curl -fL --retry 3 -o "$work/$tool.zip" "$url"
      unzip -q -o "$work/$tool.zip" -d "$work/$tool"
      cp "$work/$tool/$tool" "$bin/$tool"
    done
    printf 'FFmpeg builds from osxexperts.net (GPL). See https://ffmpeg.org/legal.html\n' > "$bin/FFMPEG-LICENSE.txt"
    # Downloaded binaries carry a quarantine flag that would make Gatekeeper block them
    xattr -dr com.apple.quarantine "$bin" 2>/dev/null || true
    ;;
  *)
    echo "Unsupported OS: $(uname -s)" >&2
    exit 1
    ;;
esac

chmod +x "$bin/ffmpeg" "$bin/ffprobe"
"$bin/ffmpeg" -version | head -n 1
echo "FFmpeg ready in $bin"
