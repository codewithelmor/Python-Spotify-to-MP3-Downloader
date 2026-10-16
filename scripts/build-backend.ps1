# Freezes backend\backend.py into build\backend\backend.exe (PyInstaller onedir).
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
Set-Location $root

python -m pip install --upgrade pyinstaller -r backend\requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'pip install failed' }

# yt-dlp loads its extractors dynamically, so collect them all.
python -m PyInstaller backend\backend.py `
    --noconfirm --onedir --console `
    --name backend `
    --distpath build `
    --workpath build\pyi-work `
    --specpath build `
    --paths backend `
    --collect-all yt_dlp `
    --collect-all certifi `
    --hidden-import truststore
if ($LASTEXITCODE -ne 0) { throw 'PyInstaller failed' }

Write-Host "Backend built: $root\build\backend\backend.exe"
