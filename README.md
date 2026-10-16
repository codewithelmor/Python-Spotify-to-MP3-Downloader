# Spotify to MP3 Downloader

A simple Python script that takes a **Spotify track, album, or playlist** link and saves each song as a tagged **MP3** with embedded **album art**. **No Spotify account or developer credentials are needed.**

## The Mission: Resisting "You Own Nothing and Be Happy"

Modern media consumption has shifted entirely to subscription-based streaming models. Under this paradigm, you don't own your music—you temporarily rent access to it, leaving your personal library vulnerable to licensing shifts, algorithmic curation, internet outages, and platform de-platforming. 

This script is built to counteract the **"you will own nothing and be happy"** future by giving you back true digital sovereignty over your culture. By **utilizing AI** smart-matching alongside public metadata, this tool automates the process of transforming temporary corporate streams into permanent, localized digital assets that belong completely to you.

## How it works
Spotify audio is DRM-protected and can't be downloaded directly. The script reads the track list, metadata, and cover art from Spotify's public web pages (the same ones used by Spotify's embeddable player), finds matching audio for each song (via `yt-dlp`), converts it to MP3 with FFmpeg, and then writes Spotify's metadata and artwork into the file. Nothing from the audio source's own metadata is kept.

Spotify's public pages are thin, so the script then **enriches** each track from free, key-less public services (Deezer, iTunes, MusicBrainz, LRCLIB). Enrichment only fills gaps: Spotify's title, artist, album, and date are never overwritten.

## Features
* **Tracks, Albums & Playlists**: Paste any Spotify track, album, or playlist link (including `intl-xx` variants and `spotify:` URIs). Albums and playlists are saved into a subfolder named after them, and a track that fails never stops the rest.
* **Album Art**: Spotify's highest-resolution cover is embedded as the front cover. When iTunes finds the *same album*, it is upgraded to a 1400x1400 cover (set `UPGRADE_COVER = False` to keep Spotify's).
* **Full ID3 Metadata** (ID3v2.3, see the table below): title, artist(s), album, album artist, year/full release date, original release year, track number/total, disc number/total, genre, BPM, ISRC, label, copyright, barcode, catalog number, explicit flag, MusicBrainz IDs, Spotify IDs and URLs, plus lyrics (plain and time-synced).
* **Smart Matching**: Picks the audio source whose duration is closest to the Spotify track (within 10 seconds), preferring auto-generated `- Topic` channels for clean album audio. A warning is printed if nothing is close.
* **Standardized Filenames**: `<artist> - <title>.mp3`.
* **Dynamic Bitrate**: 128, 192, 256, 320 kbps, or a custom value.
* **Target Output Folders**: Choose any folder path (created if missing) or default to the current folder.

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

Every source is **best effort**: if a service has no match (or is unreachable), that field is simply left out and the rest are still written. Matches from Deezer, iTunes, and LRCLIB must agree on title, artist, and duration (within 3 seconds), so a wrong song is not tagged by accident. After each track the script prints which fields were written.

When prompted, answer `n` to **"Fetch extra metadata"** to skip enrichment and write only the Spotify fields (faster).

> **MusicBrainz etiquette:** edit `MB_USER_AGENT` near the top of `backend/core.py` and put your own contact email in it, as MusicBrainz requests. Lookups are throttled to 1 per second.

---

## Prerequisites

This project requires **FFmpeg** to convert audio to MP3. It must be installed on your system and added to your system's PATH.

* **macOS**: `brew install ffmpeg`
* **Linux (Ubuntu/Debian)**: `sudo apt update && sudo apt install ffmpeg`
* **Windows**: Download the binaries from the official [FFmpeg site](https://ffmpeg.org) and add the `bin` folder to your System Environment Variables (PATH).

---

## Supported Links

`https://open.spotify.com/track/...`, `/album/...`, `/playlist/...` (including `intl-xx` variants) and `spotify:track:...` URIs. Shortened `spotify.link` URLs are not supported; open them in a browser and copy the full URL.

---

## Setup Instructions

Follow these steps to set up a virtual environment and run the script.

### 1. Clone or Create the Project
Navigate to your project directory:
```bash
cd path/to/your/project
```

### 2. Create a Virtual Environment
Create an isolated environment to prevent library conflicts.

* **macOS / Linux:**
  ```bash
  python3 -m venv venv
  ```
* **Windows:**
  ```cmd
  python -m venv venv
  ```

### 3. Activate the Virtual Environment
You must activate the environment before installing dependencies or running the script.

* **macOS / Linux:**
  ```bash
  source venv/bin/activate
  ```
* **Windows (Command Prompt):**
  ```cmd
  venv\Scripts\activate.bat
  ```
* **Windows (PowerShell):**
  ```powershell
  venv\Scripts\Activate.ps1
  ```
  *(Note: If you get a script execution error in PowerShell, run `Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process` first).*

### 4. Install Dependencies
Install the required packages from the `requirements.txt` file:
```bash
pip install -r backend/requirements.txt
```

---

## Usage

1. Run the Python script:
   ```bash
   python backend/cli.py
   ```
2. Paste a **Spotify track, album, or playlist URL** when prompted.
3. Provide a **Target Directory** (e.g., `downloads`, `~/Music/Spotify`, or leave blank for the current folder).
4. Choose your desired **audio quality/bitrate** (128, 192, 256, 320 kbps, or custom).
5. Choose whether to **fetch extra metadata** (default: yes).
6. Progress is printed per track (e.g. `[3/12] Processing: ...`). Each finished MP3 is saved as `<artist> - <title>.mp3` with Spotify's tags and album art.

---

## Desktop app (Electron)

`app/` is an Electron + TypeScript UI that runs the Python backend (`backend/backend.py`) and bundles FFmpeg, so end users need neither Python nor FFmpeg installed.

**Develop:** `cd app && npm install && npm start` (uses `python3`/`python` and the FFmpeg on your PATH).

**Package** (PyInstaller cannot cross-compile, so build on the OS you are targeting):

| OS | Command | Output in `app/dist/` |
|----|---------|-----------------------|
| Windows | `powershell -ExecutionPolicy Bypass -File scripts\build-all.ps1` | `*Setup*.exe` |
| Linux | `scripts/build-all.sh` | `*.AppImage`, `*.deb` |
| macOS | `scripts/build-all.sh` | `*.dmg` (matches your CPU: Apple Silicon or Intel) |

Add `-Clean` (PowerShell) or `--clean` (bash) for a fully fresh build. The scripts need Python 3.10+, Node.js and internet access (FFmpeg and the Electron binary are downloaded). On Debian/Ubuntu also install `python3-venv` and `xz-utils`. `.github/workflows/build.yml` builds all three on GitHub Actions.

Builds are unsigned: Windows SmartScreen and macOS Gatekeeper will warn users (on macOS, right-click the app and choose Open the first time).

---

## Troubleshooting

* **"FFmpeg not found" Error:** Ensure FFmpeg is properly installed and that your terminal can run the `ffmpeg` command globally. Restart your terminal/IDE after installing FFmpeg.
* **Download Fails / HTTP Errors:** Audio sources change their layout frequently. If downloads stop working, update `yt-dlp` to the latest version inside your activated virtual environment:
  ```bash
  pip install --upgrade yt-dlp
  ```

* **`CERTIFICATE_VERIFY_FAILED` / SSL errors:** Python can't verify HTTPS certificates. Run `pip install -r backend/requirements.txt` again (this installs `truststore` and `certifi`, so the script uses your OS certificate store; Python 3.10+ is needed for `truststore`). On macOS with a python.org install, you can also run `/Applications/Python 3.x/Install Certificates.command`. On a corporate network with a proxy, make sure your company's root certificate is installed in the OS store.
* **"Could not read that Spotify ...":** Check the link and your internet connection. Playlists must be public. If this suddenly fails for every link, Spotify has probably changed its page format (see the note below); update the script or `yt-dlp`.
* **Large playlists are cut short:** Spotify's embed pages may list only the first ~100 tracks of a playlist. For bigger playlists, split them into smaller playlists in Spotify.
* **Playlist tracks have no album name / cover:** For playlists the script looks up each track individually (slower, about a second per track). If that lookup fails for a track, it falls back to the basic title/artist from the playlist listing and the tags are thinner.
* **Some fields are missing (genre, BPM, label, lyrics...):** The track wasn't found on Deezer/iTunes/MusicBrainz/LRCLIB, or the match was rejected for not agreeing on title, artist, and duration. MusicBrainz needs an ISRC, which usually comes from Deezer. Obscure tracks will have thinner tags. Lyrics only exist for songs LRCLIB has.
* **Genre looks too broad:** iTunes only gives one broad genre; MusicBrainz and Deezer are more specific and are listed first when available.
* **Multi-disc albums:** The track number is the number within its disc (e.g. `3` on disc 2), taken from Deezer/iTunes. If neither finds the album, Spotify's continuous album position is used.
* **Enrichment is slow:** MusicBrainz is limited to 1 request/second. Answer `n` to the extra-metadata prompt for fast, Spotify-only tags.
* **No album art / wrong tags in your player:** Some players cache old tags. Re-import the file or refresh the library. Tags are written as ID3v2.3 for broad compatibility.
* **Wrong song downloaded:** Matching is automatic. Tracks are matched by search and duration, so rare tracks, remixes, or live versions may match a different upload. A warning is printed when no result is within 10 seconds of the Spotify duration.

## Note on reliability
Because no official API is used, the script depends on the layout of Spotify's public pages, which Spotify can change without notice. Spotify's public pages don't provide genre, BPM, label, copyright, or disc number, which is why those come from Deezer, iTunes, and MusicBrainz instead. Those services are also unofficial for this purpose and can change or rate-limit without notice; a failure in any of them only removes that service's fields.

## Deactivation
When you are done working on the project, you can exit the virtual environment by typing:
```bash
deactivate
```
