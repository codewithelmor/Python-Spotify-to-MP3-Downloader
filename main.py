import os
import re
import ssl
import json
import time
import html as htmllib
import urllib.request

# Use the operating system's trusted certificates (fixes CERTIFICATE_VERIFY_FAILED on
# corporate networks/proxies and on Python installs without root certificates).
try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

import yt_dlp
from mutagen.id3 import (
    ID3, TIT2, TPE1, TALB, TPE2, TRCK, TPOS, TDRC, TSRC, WOAS, APIC
)

# ---------------------------------------------------------------------------
# Spotify -> MP3 downloader
# Spotify streams are DRM-protected, so audio is never taken from Spotify itself.
# No Spotify account or developer credentials are needed: the track list, metadata,
# and album art are read from Spotify's public web pages (the same pages used by
# the "embed" player). yt-dlp is used only as the audio source for each matched
# track, which FFmpeg converts to MP3. All tags and cover art come from Spotify.
# ---------------------------------------------------------------------------

SPOTIFY_URL_PATTERN = re.compile(
    r'(?:open\.spotify\.com/(?:intl-[a-z]{2,}(?:-[a-z]{2,})?/)?|spotify:)'
    r'(track|album|playlist)[/:]([A-Za-z0-9]{22})'
)

# Max allowed difference (seconds) between the Spotify track and an audio source
DURATION_TOLERANCE = 10

def build_ssl_context():
    """SSL context for the script's own web requests (page and cover art downloads)."""
    try:
        import truststore  # noqa: F401 - already injected above; default context uses OS store
        return ssl.create_default_context()
    except ImportError:
        pass
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()

SSL_CONTEXT = build_ssl_context()


# ----------------------------- User prompts --------------------------------

def get_valid_directory():
    """Prompts the user for a download folder and ensures it exists."""
    while True:
        directory = input("\nEnter target directory to save MP3 (Leave blank for current folder): ").strip()

        if not directory:
            return "."  # Current directory

        # Clean up path and expand user home directory symbols like ~
        directory = os.path.abspath(os.path.expanduser(directory))

        try:
            if not os.path.exists(directory):
                os.makedirs(directory)
                print(f"📁 Created folder: {directory}")
            return directory
        except Exception as e:
            print(f"❌ Invalid directory or permission denied. Error: {e}. Please try again.")

def get_valid_bitrate():
    """Prompts the user for a bitrate and validates the input."""
    print("\nSelect your desired MP3 quality (bitrate):")
    print("1. 128 kbps (Standard quality / smaller file)")
    print("2. 192 kbps (High quality - Recommended)")
    print("3. 256 kbps (Very high quality)")
    print("4. 320 kbps (Highest quality / larger file)")
    print("5. Custom bitrate")

    while True:
        choice = input("Enter choice (1-5) or directly enter a value (e.g., 256): ").strip()

        if choice == '1':
            return '128'
        elif choice == '2':
            return '192'
        elif choice == '3':
            return '256'
        elif choice == '4':
            return '320'
        elif choice == '5':
            custom = input("Enter custom bitrate in kbps (e.g., 160): ").strip()
            if custom.isdigit():
                return custom
        elif choice.isdigit():
            return choice

        print("❌ Invalid input. Please enter a number between 1-5 or a valid numeric bitrate.")

def sanitize_folder_name(name):
    """Strips characters that are unsafe for folder/file names across OSes."""
    name = re.sub(r'[\\/:*?"<>|]', '', name).strip()
    return name or "Untitled"


# --------------------- Spotify public pages (no API key) --------------------

USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
              '(KHTML, like Gecko) Chrome/124.0 Safari/537.36')

def http_get(url):
    """Fetches a page as text."""
    req = urllib.request.Request(url, headers={
        'User-Agent': USER_AGENT,
        'Accept-Language': 'en-US,en;q=0.9',
    })
    with urllib.request.urlopen(req, timeout=20, context=SSL_CONTEXT) as resp:
        return resp.read().decode('utf-8', errors='replace')

def parse_spotify_url(url):
    """Returns (kind, id) for Spotify track/album/playlist URLs or URIs, else None."""
    match = SPOTIFY_URL_PATTERN.search(url)
    return (match.group(1), match.group(2)) if match else None

def _find_entity(node, uri):
    """Recursively searches parsed page JSON for the object whose uri matches."""
    if isinstance(node, dict):
        if node.get('uri') == uri:
            return node
        children = node.values()
    elif isinstance(node, list):
        children = node
    else:
        return None
    for child in children:
        found = _find_entity(child, uri)
        if found:
            return found
    return None

def fetch_entity(kind, spotify_id):
    """Loads the embed page for a track/album/playlist and returns its data object."""
    html = http_get(f'https://open.spotify.com/embed/{kind}/{spotify_id}')
    match = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', html, re.S)
    if not match:
        raise RuntimeError("Spotify page format not recognised (no embedded data found)")
    data = json.loads(match.group(1))

    # Known location first, then fall back to searching the whole JSON by URI
    try:
        entity = data['props']['pageProps']['state']['data']['entity']
    except (KeyError, TypeError):
        entity = None
    if not entity:
        entity = _find_entity(data, f'spotify:{kind}:{spotify_id}')
    if not entity:
        raise RuntimeError(f"{kind} not found (is it private or unavailable?)")
    return entity

def best_cover_url(entity):
    """Returns the URL of the largest cover image on a page entity."""
    images = list((entity.get('coverArt') or {}).get('sources') or [])
    images += list((entity.get('visualIdentity') or {}).get('image') or [])
    images = [i for i in images if i.get('url')]
    if not images:
        return None

    def size(i):
        return (i.get('width') or i.get('maxWidth') or 0) * (i.get('height') or i.get('maxHeight') or 0)

    return max(images, key=size)['url']

def meta_content(html, prop):
    """Reads a <meta property="..." content="..."> value from a page."""
    for pattern in (
        rf'<meta[^>]+(?:property|name)="{re.escape(prop)}"[^>]*content="([^"]*)"',
        rf'<meta[^>]+content="([^"]*)"[^>]*(?:property|name)="{re.escape(prop)}"',
    ):
        match = re.search(pattern, html)
        if match:
            return htmllib.unescape(match.group(1))
    return None

_album_name_cache = {}

def lookup_album_name(track_id):
    """Best effort: finds a track's album name via its public track/album pages."""
    try:
        track_html = http_get(f'https://open.spotify.com/track/{track_id}')
        album_url = meta_content(track_html, 'music:album')
        if not album_url:
            return None
        if album_url not in _album_name_cache:
            _album_name_cache[album_url] = meta_content(http_get(album_url), 'og:title')
        return _album_name_cache[album_url]
    except Exception:
        return None

def _split_artists(text):
    return [a.strip() for a in (text or '').split(',') if a.strip()]

def make_track(track_id, title, artists, duration_ms, **extra):
    """Builds the track dict used by the rest of the script (missing fields stay None)."""
    track = {
        'artist': ', '.join(artists) or "Unknown Artist",
        'primary_artist': artists[0] if artists else "",
        'title': title or "Unknown Title",
        'album': None,
        'album_artist': None,
        'track_number': None,
        'total_tracks': None,
        'disc_number': None,
        'release_date': '',
        'isrc': None,
        'spotify_url': f'https://open.spotify.com/track/{track_id}',
        'cover_url': None,
        'duration': (duration_ms or 0) / 1000,
    }
    track.update({k: v for k, v in extra.items() if v})
    return track

def fetch_track(track_id):
    """Full details for one track (title, artists, duration, cover, date, album)."""
    entity = fetch_entity('track', track_id)
    artists = [a['name'] for a in entity.get('artists') or [] if a.get('name')]
    if not artists:
        artists = _split_artists(entity.get('subtitle'))
    return make_track(
        track_id,
        entity.get('name') or entity.get('title'),
        artists,
        entity.get('duration'),
        album=lookup_album_name(track_id),
        release_date=((entity.get('releaseDate') or {}).get('isoString') or '')[:10],
        cover_url=best_cover_url(entity),
    )

def fetch_spotify_tracks(kind, spotify_id):
    """Returns (collection_name_or_None, [track dicts]) for a Spotify track/album/playlist."""
    if kind == 'track':
        return None, [fetch_track(spotify_id)]

    entity = fetch_entity(kind, spotify_id)
    name = entity.get('name') or entity.get('title') or "Untitled"
    items = [i for i in entity.get('trackList') or [] if str(i.get('uri', '')).startswith('spotify:track:')]

    if kind == 'album':
        album_artist = entity.get('subtitle')
        release = ((entity.get('releaseDate') or {}).get('isoString') or '')[:10]
        cover = best_cover_url(entity)
        tracks = []
        for number, item in enumerate(items, start=1):
            tracks.append(make_track(
                item['uri'].split(':')[-1],
                item.get('title'),
                _split_artists(item.get('subtitle')),
                item.get('duration'),
                album=name,
                album_artist=album_artist,
                track_number=number,
                total_tracks=len(items),
                release_date=release,
                cover_url=cover,
            ))
        return name, tracks

    # Playlist: look up each track for its own cover art, album, and release date
    tracks = []
    for number, item in enumerate(items, start=1):
        track_id = item['uri'].split(':')[-1]
        try:
            tracks.append(fetch_track(track_id))
        except Exception:
            # Fall back to the (thinner) data from the playlist listing
            tracks.append(make_track(
                track_id, item.get('title'), _split_artists(item.get('subtitle')), item.get('duration')))
        time.sleep(0.3)  # be polite to Spotify's servers
    return name, tracks


# ------------------------------ Album art ----------------------------------

_cover_cache = {}

def download_cover(url):
    """Downloads cover art bytes (cached so albums only fetch their cover once)."""
    if not url:
        return None
    if url not in _cover_cache:
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req, timeout=20, context=SSL_CONTEXT) as resp:
                _cover_cache[url] = resp.read()
        except Exception as e:
            print(f"   ⚠️ Could not download album art: {e}")
            _cover_cache[url] = None
    return _cover_cache[url]


# ------------------------------ Tagging ------------------------------------

def write_id3_tags(mp3_path, track, cover_bytes):
    """
    Replaces whatever tags the conversion left behind with clean Spotify metadata
    and embeds the album art as the front cover.
    """
    tags = ID3()  # Fresh tag, so no leftover source-video metadata survives

    tags.add(TIT2(encoding=3, text=track['title']))
    tags.add(TPE1(encoding=3, text=track['artist']))
    if track['album']:
        tags.add(TALB(encoding=3, text=track['album']))
    if track['album_artist']:
        tags.add(TPE2(encoding=3, text=track['album_artist']))
    if track['track_number']:
        number = str(track['track_number'])
        if track['total_tracks']:
            number += f"/{track['total_tracks']}"
        tags.add(TRCK(encoding=3, text=number))
    if track['disc_number']:
        tags.add(TPOS(encoding=3, text=str(track['disc_number'])))
    if track['release_date']:
        tags.add(TDRC(encoding=3, text=track['release_date']))
    if track['isrc']:
        tags.add(TSRC(encoding=3, text=track['isrc']))
    if track['spotify_url']:
        tags.add(WOAS(url=track['spotify_url']))
    if cover_bytes:
        mime = 'image/png' if cover_bytes[:8] == b'\x89PNG\r\n\x1a\n' else 'image/jpeg'
        tags.add(APIC(encoding=3, mime=mime, type=3, desc='Cover', data=cover_bytes))

    tags.save(mp3_path, v2_version=3)  # ID3v2.3 for the widest player compatibility


# ------------------------------ Downloading --------------------------------

def build_ydl_opts(bitrate, output_dir):
    """Builds the yt-dlp options dict for a given bitrate/output folder."""
    return {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(output_dir, '%(artist)s - %(title)s.%(ext)s'),
        'postprocessors': [
            {
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': bitrate,
            },
        ],
        'quiet': False,
        'ignoreerrors': True,
    }

def find_audio_source(search_ydl, track):
    """
    Searches for the best audio source for a Spotify track and returns its URL.
    Prefers auto-generated "- Topic" channels (clean album audio) and results whose
    duration is closest to the Spotify track's duration.
    """
    query = f"ytsearch5:{track['primary_artist']} - {track['title']} audio"
    result = search_ydl.extract_info(query, download=False)
    candidates = [e for e in (result or {}).get('entries', []) if e and e.get('duration')]

    if not candidates:
        return None

    def diff(entry):
        return abs(entry['duration'] - track['duration'])

    close = [e for e in candidates if diff(e) <= DURATION_TOLERANCE]
    if close:
        topic = [e for e in close if (e.get('channel') or e.get('uploader') or '').endswith('- Topic')]
        best = min(topic or close, key=diff)
    else:
        best = min(candidates, key=diff)
        print(f"   ⚠️ No result within {DURATION_TOLERANCE}s of the Spotify duration; using closest match.")

    return best.get('url') or f"https://www.youtube.com/watch?v={best['id']}"

def download_track(ydl, search_ydl, track):
    """Downloads one Spotify track as MP3, then tags it and embeds the album art."""
    source_url = find_audio_source(search_ydl, track)
    if not source_url:
        raise RuntimeError("no matching audio source found")

    info = ydl.extract_info(source_url, download=False)
    if info is None:
        raise RuntimeError("could not retrieve the matched audio")

    # Spotify's values drive the filename template: "<artist> - <title>.mp3"
    info['artist'] = track['artist']
    info['title'] = track['title']

    ydl.process_info(info)

    mp3_path = os.path.splitext(ydl.prepare_filename(info))[0] + '.mp3'
    if not os.path.exists(mp3_path):
        raise RuntimeError("MP3 conversion did not produce a file (is FFmpeg installed?)")

    write_id3_tags(mp3_path, track, download_cover(track['cover_url']))

def download_spotify(url, bitrate, output_dir):
    """Handles Spotify track, album, and playlist links."""
    spotify = parse_spotify_url(url)
    if not spotify:
        print("❌ That doesn't look like a Spotify track, album, or playlist link.")
        return

    kind, spotify_id = spotify

    try:
        print(f"\nFetching Spotify {kind} details... Please wait.")
        name, tracks = fetch_spotify_tracks(kind, spotify_id)
    except Exception as e:
        print(f"❌ Could not read that Spotify {kind}: {e}")
        print("   (Check the link and your connection. Playlists must be public.)")
        return

    total = len(tracks)
    if total == 0:
        print("⚠️ No downloadable tracks were found.")
        return

    target_dir = output_dir
    if name:
        target_dir = os.path.join(output_dir, sanitize_folder_name(name))
        os.makedirs(target_dir, exist_ok=True)
        print(f"\n📃 Spotify {kind} detected: \"{name}\" ({total} track(s))")
        print(f"📁 Saving tracks to: {target_dir}")

    ydl_opts = build_ydl_opts(bitrate, target_dir)
    search_opts = {'quiet': True, 'no_warnings': True, 'extract_flat': True, 'ignoreerrors': True}

    success_count = 0
    with yt_dlp.YoutubeDL(ydl_opts) as ydl, yt_dlp.YoutubeDL(search_opts) as search_ydl:
        for index, track in enumerate(tracks, start=1):
            label = f"{track['artist']} - {track['title']}"
            print(f"\n[{index}/{total}] Processing: {label}")
            try:
                download_track(ydl, search_ydl, track)
                success_count += 1
            except Exception as e:
                print(f"❌ Skipped \"{label}\" due to an error: {e}")

    print(f"\n🎉 Download complete! {success_count}/{total} track(s) saved to: {target_dir}")


if __name__ == "__main__":
    url = input("Enter Spotify Track, Album, or Playlist URL: ").strip()
    if url:
        output_folder = get_valid_directory()
        kbps = get_valid_bitrate()
        download_spotify(url, kbps, output_folder)
    else:
        print("❌ URL cannot be empty.")
