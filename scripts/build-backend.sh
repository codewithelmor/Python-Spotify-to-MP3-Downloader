#!/usr/bin/env bash
# Freezes backend/backend.py into build/backend/backend (PyInstaller onedir).
# PyInstaller cannot cross-compile: run this on the OS you are building for.
set -euo pipefail

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

py="${PYTHON:-python3}"
command -v "$py" >/dev/null || { echo "'$py' not found. Install Python 3.10+ (or set PYTHON=...)." >&2; exit 1; }

# A throwaway venv keeps the build independent of system packages (and of PEP 668 "externally managed" Pythons).
venv="$root/build/venv"
if [[ ! -x "$venv/bin/python" ]]; then
  "$py" -m venv "$venv"
fi
python="$venv/bin/python"

"$python" -m pip install --quiet --upgrade pip
"$python" -m pip install --upgrade pyinstaller -r backend/requirements.txt

# yt-dlp loads its extractors dynamically, so collect them all.
"$python" -m PyInstaller backend/backend.py \
  --noconfirm --onedir --console \
  --name backend \
  --distpath build \
  --workpath build/pyi-work \
  --specpath build \
  --paths backend \
  --collect-all yt_dlp \
  --collect-all certifi \
  --hidden-import truststore

echo "Backend built: $root/build/backend/backend"
