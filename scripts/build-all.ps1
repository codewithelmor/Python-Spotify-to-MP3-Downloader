# Builds the whole app: FFmpeg + frozen Python backend + Electron installer.
# Run from anywhere:  powershell -ExecutionPolicy Bypass -File scripts\build-all.ps1
# Options:
#   -Clean   delete build\ and app\dist\ first (forces a fresh FFmpeg download and backend freeze)
param([switch]$Clean)
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$app = Join-Path $root 'app'

function Step($text) { Write-Host "`n==> $text" -ForegroundColor Cyan }

function Require($name, $hint) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        throw "'$name' was not found on PATH. $hint"
    }
}

function Run($label, [scriptblock]$command) {
    & $command
    if ($LASTEXITCODE -ne 0) { throw "$label failed (exit code $LASTEXITCODE)" }
}

Step 'Checking prerequisites'
Require 'python' 'Install Python 3.10+ from python.org and tick "Add to PATH".'
Require 'node'   'Install Node.js (LTS recommended) from nodejs.org.'
Require 'npm'    'Install Node.js (LTS recommended) from nodejs.org.'
$pyVersion = [version](python -c "import sys; print('%d.%d' % sys.version_info[:2])")
if ($pyVersion -lt [version]'3.10') { throw "Python 3.10+ is required (found $pyVersion)." }
Write-Host "python $pyVersion, node $(node -v), npm $(npm -v)"

if ($Clean) {
    Step 'Cleaning previous build output'
    foreach ($dir in @((Join-Path $root 'build'), (Join-Path $app 'dist'), (Join-Path $app 'out'))) {
        # Antivirus or a still-open window can briefly lock files, so retry a few times.
        for ($try = 1; (Test-Path $dir); $try++) {
            try { Remove-Item -Recurse -Force $dir -ErrorAction Stop }
            catch {
                if ($try -ge 4) { throw "Could not delete $dir - close the app or any window using it. $($_.Exception.Message)" }
                Start-Sleep -Seconds 2
            }
        }
    }
}

Step 'Fetching FFmpeg (skipped if already in build\bin)'
& (Join-Path $PSScriptRoot 'fetch-ffmpeg.ps1')

Step 'Freezing the Python backend with PyInstaller'
& (Join-Path $PSScriptRoot 'build-backend.ps1')

Step 'Installing Electron app dependencies'
Push-Location $app
try {
    Run 'npm install' { npm install }

    # Some npm/Node combinations skip Electron's postinstall (binary download), or its
    # unzip step silently does nothing. Repair that so electron-builder can find the binary.
    $electronDir = Join-Path $app 'node_modules\electron'
    $electronExe = Join-Path $electronDir 'dist\electron.exe'
    if (-not (Test-Path $electronExe)) {
        Step 'Electron binary missing - downloading it'
        node (Join-Path $electronDir 'install.js')
    }
    if (-not (Test-Path $electronExe)) {
        $version = (Get-Content (Join-Path $electronDir 'package.json') -Raw | ConvertFrom-Json).version
        $zip = Get-ChildItem "$env:LOCALAPPDATA\electron\Cache" -Recurse -Filter "electron-v$version-win32-x64.zip" -ErrorAction SilentlyContinue |
            Select-Object -First 1
        if (-not $zip) { throw "Could not download Electron $version. Check your internet connection and rerun." }
        Write-Host "Extracting $($zip.Name)"
        $dist = Join-Path $electronDir 'dist'
        if (Test-Path $dist) { Remove-Item -Recurse -Force $dist }
        Expand-Archive -Path $zip.FullName -DestinationPath $dist
        [IO.File]::WriteAllText((Join-Path $electronDir 'path.txt'), 'electron.exe')
    }
    if (-not (Test-Path $electronExe)) { throw 'Electron binary is still missing after repair.' }

    Step 'Compiling TypeScript and building the installer'
    Run 'npm run dist' { npm run dist }
}
finally {
    Pop-Location
}

Step 'Verifying output'
$installer = Get-ChildItem (Join-Path $app 'dist') -Filter '*Setup*.exe' | Select-Object -First 1
$unpacked = Join-Path $app 'dist\win-unpacked'
$required = @(
    (Join-Path $unpacked 'Spotify to MP3.exe'),
    (Join-Path $unpacked 'resources\backend\backend.exe'),
    (Join-Path $unpacked 'resources\bin\ffmpeg.exe'),
    (Join-Path $unpacked 'resources\bin\ffprobe.exe')
)
foreach ($file in $required) {
    if (-not (Test-Path $file)) { throw "Missing from the packaged app: $file" }
}
if (-not $installer) { throw 'The installer .exe was not produced.' }

# Smoke test the frozen backend that was packaged (no network needed for a bad link).
$probe = & (Join-Path $unpacked 'resources\backend\backend.exe') --url 'not-a-link' --preview
if ($probe -notmatch '"event": "error"') { throw "Packaged backend gave unexpected output: $probe" }

Write-Host "`nBuild succeeded." -ForegroundColor Green
Write-Host ("Installer: {0} ({1:N0} MB)" -f $installer.FullName, ($installer.Length / 1MB))
Write-Host "Portable:  $unpacked\Spotify to MP3.exe"
