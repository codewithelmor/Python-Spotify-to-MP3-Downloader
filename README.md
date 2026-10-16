# Spotify to MP3 Downloader

Turn a **Spotify track, album, or playlist link** into fully tagged **MP3** files with embedded cover art. No Spotify account or developer credentials required.

Use it from the **command line** or the **Electron desktop app**; both share the same Python core.

## Table of Contents

- [How it works](#how-it-works)
- [Features](#features)
- [Quick start](#quick-start)
- [Installation](#installation)
- [Usage](#usage)
  - [Command line (interactive)](#command-line-interactive)
  - [Desktop app](#desktop-app)
  - [JSON-lines backend](#json-lines-backend)
  - [Supported links](#supported-links)
- [Metadata written to each MP3](#metadata-written-to-each-mp3)
- [Building installers](#building-installers)
- [Project structure](#project-structure)
- [Troubleshooting](#troubleshooting)
- [Limitations and reliability](#limitations-and-reliability)
- [Legal notice](#legal-notice)
- [Contributing](#contributing)
- [License](#license)

## How it works

Spotify audio is DRM-protected and cannot be downloaded directly. Instead, the tool:

1. Reads the track list, metadata, and cover art from Spotify's public embed pages (the ones used by the embeddable player).
2. Finds matching audio for each song on YouTube via [`yt-dlp`](https://github.com/yt-dlp/yt-dlp), choosing the result whose duration is closest, preferring auto-generated "- Topic" channels.
3. Converts it to MP3 with [FFmpeg](https://ffmpeg.org).
4. **Enriches** the track from free, key-less services (Deezer, iTunes, MusicBrainz, LRCLIB). Enrichment only fills gaps; Spotify's title, artist, album, and date are never overwritten.
5. Writes the tags and artwork into the file. Nothing from the audio source's own metadata is kept.

## Features

- **Tracks, albums, and playlists**: albums and playlists are saved into a subfolder named after them; a track that fails never stops the rest.
- **Album art**: Spotify's highest-resolution cover is embedded as the front cover, upgraded to 1400x1400 when iTunes finds the same album (set `UPGRADE_COVER = False` in `backend/core.py` to keep Spotify's).
- **Full ID3v2.3 metadata**: see the [table below](#metadata-written-to-each-mp3), including plain and time-synced lyrics.
- **Smart matching**: duration-based matching (within 10 seconds) with a warning when nothing is close.
- **Standardized filenames**: `<artist> - <title>.mp3`.
- **Selectable quality**: 128, 192, 256, 320 kbps, or a custom bitrate.
- **Cross-platform**: Windows, macOS, and Linux.

## Quick Start

```bash
git clone <this-repo-url>
cd Python-Spotify-to-MP3-Downloader

python -m venv venv
source venv/bin/activate            # Windows: venv\Scripts\activate
pip install -r backend/requirements.txt

python backend/cli.py
```

You also need FFmpeg on your `PATH` (see below).

## Installation

### Prerequisites

| Requirement | Notes |
|---|---|
| Python 3.10+ | Required by `truststore` |
| FFmpeg (with FFprobe) | Must be on your `PATH` for CLI use |
| Node.js | Only for developing or packaging the desktop app |

Install FFmpeg:

- **macOS**: `brew install ffmpeg`
- **Debian/Ubuntu**: `sudo apt update && sudo apt install ffmpeg`
- **Windows**: `winget install Gyan.FFmpeg`, or download binaries from [ffmpeg.org](https://ffmpeg.org) and add the `bin` folder to your `PATH`.

### Python Environment

Create and activate a virtual environment, then install dependencies:

| Platform | Create | Activate |
|---|---|---|
| macOS / Linux | `python3 -m venv venv` | `source venv/bin/activate` |
| Windows (cmd) | `python -m venv venv` | `venv\Scripts\activate.bat` |
| Windows (PowerShell) | `python -m venv venv` | `venv\Scripts\Activate.ps1` |

```bash
pip install -r backend/requirements.txt
```

> In PowerShell, if activation is blocked, run `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process` first. Run `deactivate` when you are done.

## Usage

### Command Line (Interactive)

```bash
python backend/cli.py
```

You will be prompted for:

1. **Spotify URL**: a track, album, or playlist link.
2. **Target directory**: e.g. `downloads` or `~/Music/Spotify`. Created if missing; leave blank for the current folder.
3. **Bitrate**: choose 1-5 (128 / 192 / 256 / 320 / custom) or type a value such as `256`.
4. **Fetch extra metadata** (default yes): genre, BPM, label, ISRC, lyrics, MusicBrainz IDs, and more. Takes roughly 5-10 seconds per track; answer `n` for fast, Spotify-only tags.

Progress is printed per track (e.g. `[3/12] Processing: ...`).

Example session:

```text
Enter Spotify Track, Album, or Playlist URL: https://open.spotify.com/album/...
Enter target directory to save MP3 (Leave blank for current folder): ~/Music/Spotify
Enter choice (1-5) or directly enter a value (e.g., 256): 2
Fetch extra metadata ...? [Y/n]:
```

### Desktop App

`app/` contains an Electron + TypeScript UI that runs the Python backend. The packaged installers bundle FFmpeg and the backend, so end users need neither Python nor FFmpeg.

For development (needs `python`/`python3` and FFmpeg on your `PATH`):

```bash
cd app
npm install
npm start          # compiles TypeScript and launches Electron
npm run typecheck  # static type check
```

Paste a link, preview the track list, pick the tracks you want, choose a folder and bitrate, then download. Cancel stops the download mid-track.

### JSON-lines Backend

The desktop app drives `backend/backend.py`, which emits one JSON event per line on stdout. You can use it directly for scripting:

```bash
# List the tracks in a link and exit
python -X utf8 -u backend/backend.py --url <spotify-url> --preview

# Download
python -X utf8 -u backend/backend.py --url <spotify-url> --out ./music --bitrate 192
```

| Flag | Description |
|---|---|
| `--url` | Spotify link (required) |
| `--preview` | List tracks and exit |
| `--out` | Output directory (default `.`) |
| `--bitrate` | MP3 bitrate in kbps (default `192`) |
| `--no-enrich` | Skip Deezer/iTunes/MusicBrainz/LRCLIB enrichment |
| `--track-id` | Download only this Spotify track ID; repeatable |
| `--ffmpeg-dir` | Folder containing `ffmpeg` and `ffprobe` |

Events: `preview`, `start`, `track_start`, `progress`, `track_done`, `track_error`, `log`, `done`, `error`. Writing `cancel` to stdin cancels the run. Always use `-X utf8 -u` (UTF-8 output, unbuffered).

### Supported Links

`https://open.spotify.com/track/...`, `/album/...`, `/playlist/...` (including `intl-xx` variants) and `spotify:track:...` URIs. Shortened `spotify.link` URLs are not supported; open them in a browser and copy the full URL. Playlists must be public.

## Metadata written to each MP3

| Field | ID3 frame | Main source |
|---|---|---|
| Title | `TIT2` | Spotify |
| Artist(s) | `TPE1` (+ `ARTISTS` list for multi-artist tracks) | Spotify |
| Album | `TALB` | Spotify |
| Album artist | `TPE2` (+ `TCMP` compilation flag for "Various Artists") | Spotify |
| Year / release date | `TDRC` | Spotify (fallback: Deezer) |
| Original release year | `TDOR` | MusicBrainz |
| Track number / total | `TRCK` | Spotify (per-disc number on multi-disc albums) |
| Disc number / total | `TPOS` | Deezer, iTunes |
| Genre (up to 5) | `TCON` | MusicBrainz, Deezer, iTunes |
| BPM | `TBPM` | Deezer |
| ISRC | `TSRC` | Spotify page if exposed, else Deezer |
| Label | `TPUB` | Deezer, MusicBrainz |
| Copyright | `TCOP` | iTunes |
| Barcode / catalog number / release country | `TXXX` | Deezer, MusicBrainz |
| Explicit flag | `TXXX` `EXPLICIT` | Spotify, Deezer, iTunes |
| MusicBrainz recording, release, release-group, track, artist IDs | `UFID` + `TXXX` | MusicBrainz |
| Spotify track / album / artist IDs; Deezer / iTunes track IDs | `TXXX` | Spotify, Deezer, iTunes |
| Spotify track and artist URLs | `WOAS`, `WOAR` | Spotify |
| Lyrics (plain) | `USLT` | LRCLIB |
| Lyrics (synced, millisecond timestamps) | `SYLT` | LRCLIB |
| Sources used | `COMM` | script |
| Cover art | `APIC` (front cover) | Spotify / iTunes |

Every source is best effort: if a service has no match or is unreachable, that field is left out and the rest are still written. Matches from Deezer, iTunes, and LRCLIB must agree on title, artist, and duration (within 3 seconds), so a wrong song is not tagged by accident.

> **MusicBrainz etiquette:** edit `MB_USER_AGENT` near the top of `backend/core.py` and put your own contact email in it, as MusicBrainz requests. Lookups are throttled to 1 per second.

## Building Installers

PyInstaller cannot cross-compile, so build on the OS you are targeting. The scripts download FFmpeg and the Electron binary, build the frozen backend, and run electron-builder. They need Python 3.10+, Node.js, and internet access. On Debian/Ubuntu also install `python3-venv` and `xz-utils`.

| OS | Command | Output in `app/dist/` |
|----|---------|-----------------------|
| Windows | `powershell -ExecutionPolicy Bypass -File scripts\build-all.ps1` | `*Setup*.exe` |
| Linux | `scripts/build-all.sh` | `*.AppImage`, `*.deb` |
| macOS | `scripts/build-all.sh` | `*.dmg` (matches your CPU) |

Add `-Clean` (PowerShell) or `--clean` (bash) for a fresh build. `.github/workflows/build.yml` builds all three on GitHub Actions when you push a `v*` tag or run it manually.

Builds are unsigned: Windows SmartScreen and macOS Gatekeeper will warn users (on macOS, right-click the app and choose Open the first time). Only the Windows build has been verified so far.

## Project Structure

```text
Spotify-to-MP3-Downloader-App/
├── .claude
│   ├── commands
│   │   └── commit.md
│   └── settings.json
├── .github
│   └── workflows
│       └── build.yml
├── app
│   ├── assets
│   │   ├── icons
│   │   │   ├── 128x128.png
│   │   │   ├── 16x16.png
│   │   │   ├── 256x256.png
│   │   │   ├── 32x32.png
│   │   │   ├── 48x48.png
│   │   │   ├── 512x512.png
│   │   │   └── 64x64.png
│   │   ├── icon.ico
│   │   └── icon.png
│   ├── scripts
│   │   └── copy-static.js
│   ├── src
│   │   ├── renderer
│   │   │   ├── index.html
│   │   │   ├── renderer.ts
│   │   │   └── style.css
│   │   ├── main.ts
│   │   ├── preload.ts
│   │   └── types.d.ts
│   ├── package-lock.json
│   ├── package.json
│   └── tsconfig.json
├── backend
│   ├── backend.py
│   ├── cli.py
│   ├── core.py
│   └── requirements.txt
├── scripts
│   ├── build-all.ps1
│   ├── build-all.sh
│   ├── build-backend.ps1
│   ├── build-backend.sh
│   ├── fetch-ffmpeg.ps1
│   ├── fetch-ffmpeg.sh
│   └── update_readme_tree.py
├── .gitattributes
├── .gitignore
├── CLAUDE.md
└── README.md
```

`core.py` is UI-agnostic: it reports through `log()` and `emit()` and never prints or prompts, so both front ends can share it.

## Troubleshooting

- **"FFmpeg not found":** ensure `ffmpeg` and `ffprobe` run from your terminal, then restart the terminal/IDE.
- **Download fails / HTTP errors:** YouTube changes often. Update yt-dlp: `pip install --upgrade yt-dlp`. A packaged app needs a rebuild to pick up a newer yt-dlp.
- **`CERTIFICATE_VERIFY_FAILED` / SSL errors:** re-run `pip install -r backend/requirements.txt` (installs `truststore` and `certifi`; Python 3.10+). On macOS with a python.org install, run `/Applications/Python 3.x/Install Certificates.command`. Behind a corporate proxy, make sure your root certificate is in the OS store.
- **"Could not read that Spotify ...":** check the link and your connection; playlists must be public. If every link suddenly fails, Spotify probably changed its page format.
- **Large playlists are cut short:** embed pages may list only the first ~100 tracks. Split bigger playlists in Spotify.
- **Playlist tracks lack album name / cover:** the tool looks up each playlist track individually (about a second each). If that fails, it falls back to the basic title/artist and the tags are thinner.
- **Missing genre, BPM, label, or lyrics:** the track was not found on Deezer/iTunes/MusicBrainz/LRCLIB, or the match was rejected. MusicBrainz needs an ISRC, which usually comes from Deezer.
- **Multi-disc albums:** the track number is the number within its disc, from Deezer/iTunes; otherwise Spotify's continuous position is used.
- **Enrichment is slow:** MusicBrainz is limited to 1 request/second; skip extra metadata for speed.
- **Wrong tags or no art in your player:** some players cache old tags; re-import the file. Tags are ID3v2.3 for broad compatibility.
- **Wrong song downloaded:** matching is by search and duration, so rare tracks, remixes, or live versions may match a different upload. A warning is printed when no result is within 10 seconds.
- **Electron binary missing after `npm install` (Windows, Node 26):** the postinstall can silently fail. `build-all.*` repairs it; for `npm start`, extract the zip from `%LOCALAPPDATA%\electron\Cache` into `node_modules/electron/dist` and write `electron.exe` to `node_modules/electron/path.txt`.

## Limitations and Reliability

No official API is used, so the tool depends on the layout of Spotify's public pages, which can change without notice. Spotify's pages do not provide genre, BPM, label, copyright, or disc number, which is why those come from Deezer, iTunes, and MusicBrainz. Those services are unofficial for this purpose and may change or rate-limit; a failure in one only removes that service's fields. There are no automated tests.

## Legal Notice

This project is intended for personal use, such as making backups or offline copies of music you have the right to use. Downloading copyrighted material may violate Spotify's and YouTube's terms of service or the law in your jurisdiction. You are responsible for how you use this tool. It is not affiliated with or endorsed by Spotify, YouTube, Deezer, Apple, or MusicBrainz.

## Contributing

Issues and pull requests are welcome.

1. Fork the repository and create a branch.
2. Keep `backend/core.py` UI-agnostic (no `print()`/`input()`; use `log()` and `emit()`).
3. If you change a backend event, update `backend/backend.py`, `app/src/types.d.ts`, `app/src/main.ts`, and `app/src/renderer/renderer.ts` together.
4. Run `cd app && npm run typecheck` before submitting.
5. Use [Conventional Commits](https://www.conventionalcommits.org) for commit messages.

## License

No license file has been added yet. Until one is, all rights are reserved by the author. Add a `LICENSE` file (for example MIT) and update this section to state the terms.
