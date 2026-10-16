#!/usr/bin/env bash
# Builds the whole app for the OS you are on: FFmpeg + frozen Python backend + Electron package.
#   Linux  -> app/dist/*.AppImage and *.deb
#   macOS  -> app/dist/*.dmg   (for the CPU you are on: Apple Silicon or Intel)
#   Windows (Git Bash) -> use scripts/build-all.ps1 instead.
# Usage: scripts/build-all.sh [--clean]
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
app="$root/app"
here="$root/scripts"

step() { printf '\n\033[36m==> %s\033[0m\n' "$1"; }
die() { echo "Error: $1" >&2; exit 1; }

clean=0
for arg in "$@"; do
  case "$arg" in
    --clean) clean=1 ;;
    *) die "unknown option: $arg" ;;
  esac
done

os="$(uname -s)"
case "$os" in
  Linux|Darwin) ;;
  *) die "this script is for Linux and macOS; on Windows run scripts/build-all.ps1" ;;
esac

step "Checking prerequisites"
py="${PYTHON:-python3}"
command -v "$py"  >/dev/null || die "python3 not found. Install Python 3.10+ (or set PYTHON=...)."
command -v node   >/dev/null || die "node not found. Install Node.js (LTS recommended)."
command -v npm    >/dev/null || die "npm not found. Install Node.js (LTS recommended)."
command -v curl   >/dev/null || die "curl not found."
"$py" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' || die "Python 3.10+ is required."
"$py" -c 'import venv, ensurepip' 2>/dev/null || die "python venv support is missing (Debian/Ubuntu: sudo apt install python3-venv)."
if [[ "$os" == Linux ]]; then
  command -v xz >/dev/null || die "xz not found (Debian/Ubuntu: sudo apt install xz-utils)."
else
  command -v unzip >/dev/null || die "unzip not found."
fi
echo "python $("$py" -V 2>&1 | cut -d' ' -f2), node $(node -v), npm $(npm -v)"

if (( clean )); then
  step "Cleaning previous build output"
  rm -rf "$root/build" "$app/dist" "$app/out"
fi

step "Fetching FFmpeg (skipped if already in build/bin)"
bash "$here/fetch-ffmpeg.sh"

step "Freezing the Python backend with PyInstaller"
bash "$here/build-backend.sh"

step "Installing Electron app dependencies"
cd "$app"
npm install

# Some npm/Node combinations skip Electron's postinstall (binary download). Repair that.
if ! node -e "require('electron')" 2>/dev/null; then
  step "Electron binary missing - downloading it"
  node node_modules/electron/install.js || true
fi
if ! node -e "require('electron')" 2>/dev/null; then
  version="$(node -p "require('./node_modules/electron/package.json').version")"
  cache="${XDG_CACHE_HOME:-$HOME/.cache}/electron"
  [[ "$os" == Darwin ]] && cache="$HOME/Library/Caches/electron"
  zip="$(find "$cache" -name "electron-v${version}-*.zip" 2>/dev/null | head -n 1)"
  [[ -n "$zip" ]] || die "could not download Electron $version. Check your internet connection and rerun."
  echo "Extracting $zip"
  rm -rf node_modules/electron/dist
  if [[ "$os" == Darwin ]]; then
    ditto -x -k "$zip" node_modules/electron/dist
    printf 'Electron.app/Contents/MacOS/Electron' > node_modules/electron/path.txt
  else
    unzip -q "$zip" -d node_modules/electron/dist
    chmod +x node_modules/electron/dist/electron
    printf 'electron' > node_modules/electron/path.txt
  fi
fi
node -e "require('electron')" >/dev/null || die "Electron binary is still missing after repair."

step "Compiling TypeScript and building the package"
npm run "dist:$([[ "$os" == Darwin ]] && echo mac || echo linux)"

step "Verifying output"
if [[ "$os" == Darwin ]]; then
  resources="$(find "$app/dist" -maxdepth 4 -type d -path '*.app/Contents/Resources' | head -n 1)"
  artifacts=("$app"/dist/*.dmg)
else
  resources="$app/dist/linux-unpacked/resources"
  artifacts=("$app"/dist/*.AppImage "$app"/dist/*.deb)
fi
[[ -n "${resources:-}" && -d "$resources" ]] || die "packaged resources folder not found"
for f in backend/backend bin/ffmpeg bin/ffprobe; do
  [[ -x "$resources/$f" ]] || die "missing or not executable in the package: $resources/$f"
done
for a in "${artifacts[@]}"; do
  [[ -f "$a" ]] || die "expected build artifact not found: $a"
done

# Smoke test the packaged backend (no network needed for a bad link).
probe="$("$resources/backend/backend" --url 'not-a-link' --preview || true)"
[[ "$probe" == *'"event": "error"'* ]] || die "packaged backend gave unexpected output: $probe"

printf '\n\033[32mBuild succeeded.\033[0m\n'
for a in "${artifacts[@]}"; do
  echo "Artifact: $a ($(du -h "$a" | cut -f1))"
done
