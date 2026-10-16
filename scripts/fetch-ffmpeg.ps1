# Downloads a Windows FFmpeg build and copies ffmpeg.exe, ffprobe.exe and the license into build\bin.
# Source: gyan.dev "release essentials" (GPL build). Keep the license files with the installer.
$ErrorActionPreference = 'Stop'

$root = Split-Path -Parent $PSScriptRoot
$bin = Join-Path $root 'build\bin'
$work = Join-Path $root 'build\_ffmpeg_dl'
$url = 'https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip'

if ((Test-Path (Join-Path $bin 'ffmpeg.exe')) -and (Test-Path (Join-Path $bin 'ffprobe.exe'))) {
    Write-Host "FFmpeg already present in $bin"
    return
}

New-Item -ItemType Directory -Force $bin, $work | Out-Null
$zip = Join-Path $work 'ffmpeg.zip'
Write-Host "Downloading $url"
Invoke-WebRequest -Uri $url -OutFile $zip

$extract = Join-Path $work 'x'
if (Test-Path $extract) { Remove-Item -Recurse -Force $extract }
Expand-Archive -Path $zip -DestinationPath $extract

$src = Get-ChildItem $extract -Directory | Select-Object -First 1
Copy-Item (Join-Path $src.FullName 'bin\ffmpeg.exe') $bin
Copy-Item (Join-Path $src.FullName 'bin\ffprobe.exe') $bin
Copy-Item (Join-Path $src.FullName 'LICENSE') (Join-Path $bin 'FFMPEG-LICENSE.txt')

Remove-Item -Recurse -Force $work
Write-Host "FFmpeg ready in $bin"
