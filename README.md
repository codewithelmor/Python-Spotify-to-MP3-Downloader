# Spotify to MP3 Downloader

A simple Python script that takes a **Spotify track, album, or playlist** link and saves each song as a tagged **MP3** with embedded **album art**. **No Spotify account or developer credentials are needed.**

## How it works
Spotify audio is DRM-protected and can't be downloaded directly. The script reads the track list, metadata, and cover art from Spotify's public web pages (the same ones used by Spotify's embeddable player), finds matching audio for each song (via `yt-dlp`), converts it to MP3 with FFmpeg, and then writes Spotify's metadata and artwork into the file. Nothing from the audio source's own metadata is kept.

## Features
* **Tracks, Albums & Playlists**: Paste any Spotify track, album, or playlist link (including `intl-xx` variants and `spotify:` URIs). Albums and playlists are saved into a subfolder named after them, and a track that fails never stops the rest.
* **Album Art**: The highest-resolution Spotify cover is embedded in every MP3 as the front cover.
* **ID3 Metadata**: Title, artist(s), album, release date, and the Spotify track URL on every file. Albums also get album artist and track number (`n/total`).
* **Smart Matching**: Picks the audio source whose duration is closest to the Spotify track (within 10 seconds), preferring auto-generated `- Topic` channels for clean album audio. A warning is printed if nothing is close.
* **Standardized Filenames**: `<artist> - <title>.mp3`.
* **Dynamic Bitrate**: 128, 192, 256, 320 kbps, or a custom value.
* **Target Output Folders**: Choose any folder path (created if missing) or default to the current folder.

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
pip install -r requirements.txt
```

---

## Usage

1. Run the Python script:
   ```bash
   python main.py
   ```
2. Paste a **Spotify track, album, or playlist URL** when prompted.
3. Provide a **Target Directory** (e.g., `downloads`, `~/Music/Spotify`, or leave blank for the current folder).
4. Choose your desired **audio quality/bitrate** (128, 192, 256, 320 kbps, or custom).
5. Progress is printed per track (e.g. `[3/12] Processing: ...`). Each finished MP3 is saved as `<artist> - <title>.mp3` with Spotify's tags and album art.

---

## Troubleshooting

* **"FFmpeg not found" Error:** Ensure FFmpeg is properly installed and that your terminal can run the `ffmpeg` command globally. Restart your terminal/IDE after installing FFmpeg.
* **Download Fails / HTTP Errors:** Audio sources change their layout frequently. If downloads stop working, update `yt-dlp` to the latest version inside your activated virtual environment:
  ```bash
  pip install --upgrade yt-dlp
  ```

* **`CERTIFICATE_VERIFY_FAILED` / SSL errors:** Python can't verify HTTPS certificates. Run `pip install -r requirements.txt` again (this installs `truststore` and `certifi`, so the script uses your OS certificate store; Python 3.10+ is needed for `truststore`). On macOS with a python.org install, you can also run `/Applications/Python 3.x/Install Certificates.command`. On a corporate network with a proxy, make sure your company's root certificate is installed in the OS store.
* **"Could not read that Spotify ...":** Check the link and your internet connection. Playlists must be public. If this suddenly fails for every link, Spotify has probably changed its page format (see the note below); update the script or `yt-dlp`.
* **Large playlists are cut short:** Spotify's embed pages may list only the first ~100 tracks of a playlist. For bigger playlists, split them into smaller playlists in Spotify.
* **Playlist tracks have no album name / cover:** For playlists the script looks up each track individually (slower, about a second per track). If that lookup fails for a track, it falls back to the basic title/artist from the playlist listing and the tags are thinner.
* **No album art / wrong tags in your player:** Some players cache old tags. Re-import the file or refresh the library. Tags are written as ID3v2.3 for broad compatibility.
* **Wrong song downloaded:** Matching is automatic. Tracks are matched by search and duration, so rare tracks, remixes, or live versions may match a different upload. A warning is printed when no result is within 10 seconds of the Spotify duration.

## Note on reliability
Because no official API is used, the script depends on the layout of Spotify's public pages, which Spotify can change without notice. Metadata is also thinner than the official API provides (no ISRC or disc number; album name and cover come from page lookups).

## Deactivation
When you are done working on the project, you can exit the virtual environment by typing:
```bash
deactivate
```
