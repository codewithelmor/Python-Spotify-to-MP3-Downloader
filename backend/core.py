import os
import re
import ssl
import json
import time
import difflib
import unicodedata
import html as htmllib
import urllib.error
import urllib.parse
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
    ID3, TIT2, TPE1, TALB, TPE2, TRCK, TPOS, TDRC, TDOR, TSRC, TCON, TBPM,
    TPUB, TCOP, TCMP, TSOP, TXXX, UFID, USLT, SYLT, COMM, WOAS, WOAR, APIC,
)

# ---------------------------------------------------------------------------
# Spotify -> MP3 downloader
# Spotify streams are DRM-protected, so audio is never taken from Spotify itself.
# No Spotify account or developer credentials are needed: the track list, metadata,
# and album art are read from Spotify's public web pages (the same pages used by
# the "embed" player). yt-dlp is used only as the audio source for each matched
# track, which FFmpeg converts to MP3.
#
# Metadata comes from Spotify first (title, artists, album, dates, cover) and is then
# enriched from free, key-less public sources (each one optional and best effort):
#   * Deezer       -> ISRC, BPM, genre, label, UPC/barcode, disc number, explicit flag
#   * iTunes       -> genre, disc/track counts, copyright, 1400x1400 cover art
#   * MusicBrainz  -> MusicBrainz IDs, label, catalog number, genres, original year
#   * LRCLIB       -> plain and time-synced lyrics
# Enrichment only FILLS GAPS: it never overwrites what Spotify provided.
# ---------------------------------------------------------------------------

SPOTIFY_URL_PATTERN = re.compile(
    r'(?:open\.spotify\.com/(?:intl-[a-z]{2,}(?:-[a-z]{2,})?/)?|spotify:)'
    r'(track|album|playlist)[/:]([A-Za-z0-9]{22})'
)

# Max allowed difference (seconds) between the Spotify track and an audio source
DURATION_TOLERANCE = 10
# Max allowed difference (seconds) when matching a track on Deezer / iTunes / LRCLIB
META_DURATION_TOLERANCE = 3
# Minimum title/artist similarity (0-1) to accept a match from another service
MATCH_THRESHOLD = 0.8
# Replace Spotify's 640px cover with iTunes' 1400px cover when it is the same album
UPGRADE_COVER = True
ITUNES_COVER_SIZE = 1400

# MusicBrainz asks every client to identify itself. Put your own contact here.
MB_USER_AGENT = 'SpotifyToMP3/2.0 ( your-email@example.com )'


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




# ------------------------------ Events -------------------------------------
# The CLI leaves the listener unset and gets plain console output. A host program
# (the Electron app, via backend.py) installs a listener to receive structured events.

_listener = None
_cancel_event = None


class Cancelled(Exception):
    """Raised inside a download when the host asked to stop."""


def set_listener(fn):
    """Install fn(event_name, data_dict) to receive events, or None for console output."""
    global _listener
    _listener = fn

def emit(event, **data):
    if _listener:
        _listener(event, data)

def log(message):
    """Human-readable status line: printed by the CLI, sent as a 'log' event to a host."""
    if _listener:
        _listener('log', {'message': message.strip()})
    else:
        print(message)

def _check_cancel():
    if _cancel_event is not None and _cancel_event.is_set():
        raise Cancelled()


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

def http_get_json(url, headers=None, allow_404=False):
    """Fetches a JSON document. Returns None on HTTP 404 when allow_404 is set."""
    req_headers = {'User-Agent': USER_AGENT, 'Accept': 'application/json'}
    req_headers.update(headers or {})
    req = urllib.request.Request(url, headers=req_headers)
    try:
        with urllib.request.urlopen(req, timeout=20, context=SSL_CONTEXT) as resp:
            return json.loads(resp.read().decode('utf-8', errors='replace'))
    except urllib.error.HTTPError as e:
        if allow_404 and e.code == 404:
            return None
        raise

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

def _split_artists(text):
    return [a.strip() for a in (text or '').split(',') if a.strip()]

def _iso_date(entity):
    """Pulls a YYYY-MM-DD date out of an embed page's releaseDate object."""
    return ((entity.get('releaseDate') or {}).get('isoString') or '')[:10]

def _spotify_id_from_uri(uri):
    return str(uri).split(':')[-1] if uri else None


# ------------------------- Spotify album context ----------------------------

_album_cache = {}

def _album_context_from_entity(album_id, entity):
    """Collects everything an album page can tell us about its tracks."""
    items = [i for i in entity.get('trackList') or [] if str(i.get('uri', '')).startswith('spotify:track:')]
    context = {
        'album': entity.get('name') or entity.get('title'),
        'album_artist': entity.get('subtitle'),
        'release_date': _iso_date(entity),
        'cover_url': best_cover_url(entity),
        'total_tracks': len(items),
        'positions': {i['uri'].split(':')[-1]: n for n, i in enumerate(items, start=1)},
        'spotify_album_id': album_id,
        'items': items,
    }
    _album_cache[album_id] = context
    return context

def fetch_album_context(album_id):
    """Album-level data (cached so an album's page is only fetched once)."""
    if album_id not in _album_cache:
        _album_context_from_entity(album_id, fetch_entity('album', album_id))
    return _album_cache[album_id]

def _find_album_in_entity(entity):
    """Searches a track's embed JSON for any album reference (uri spotify:album:ID)."""
    stack = [entity]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            uri = str(node.get('uri', ''))
            if uri.startswith('spotify:album:'):
                return {'spotify_album_id': uri.split(':')[-1],
                        'album': node.get('name') or node.get('title')}
            stack.extend(node.values())
        elif isinstance(node, list):
            stack.extend(node)
    return {}

def lookup_album_info(track_id):
    """
    Best effort: finds the album a track belongs to via its public track page, then
    reads that album's page for album artist, track position, total tracks, date, cover.
    """
    info = {}
    try:
        track_html = http_get(f'https://open.spotify.com/track/{track_id}')
    except Exception:
        return info

    album_url = meta_content(track_html, 'music:album')

    # og:description looks like "Artist · Album · Song · 1975" - a handy last-resort source
    parts = [p.strip() for p in (meta_content(track_html, 'og:description') or '').split('\u00b7')]
    if len(parts) >= 4 and parts[2].lower() == 'song' and parts[1]:
        info['album'] = parts[1]
        if re.fullmatch(r'\d{4}', parts[3]):
            info['release_date'] = parts[3]

    info['release_date'] = (meta_content(track_html, 'music:release_date') or '')[:10] \
        or info.get('release_date', '')
    info['cover_url'] = meta_content(track_html, 'og:image')
    fallback_number = meta_content(track_html, 'music:album:track')
    if fallback_number and fallback_number.isdigit():
        info['track_number'] = int(fallback_number)

    match = re.search(r'/album/([A-Za-z0-9]{22})', album_url or '')
    if not match:
        return info
    album_id = match.group(1)
    info['spotify_album_id'] = album_id

    try:
        context = fetch_album_context(album_id)
        info.update({k: v for k, v in {
            'album': context['album'],
            'album_artist': context['album_artist'],
            'release_date': context['release_date'] or info['release_date'],
            'cover_url': context['cover_url'] or info['cover_url'],
            'total_tracks': context['total_tracks'],
            'track_number': context['positions'].get(track_id) or info.get('track_number'),
        }.items() if v})
    except Exception:
        # Last resort: at least get the album title from the album page's meta tags
        try:
            info['album'] = meta_content(http_get(album_url), 'og:title')
        except Exception:
            pass
    return info


# ------------------------------ Track objects -------------------------------

def make_track(track_id, title, artists, duration_ms, **extra):
    """Builds the track dict used by the rest of the script (missing fields stay empty)."""
    track = {
        # --- core Spotify fields ---
        'artist': ', '.join(artists) or "Unknown Artist",
        'artists': list(artists),
        'primary_artist': artists[0] if artists else "",
        'title': title or "Unknown Title",
        'album': None,
        'album_artist': None,
        'track_number': None,
        'total_tracks': None,
        'disc_number': None,
        'disc_total': None,
        'disc_track_number': None,   # position within its own disc (multi-disc albums)
        'release_date': '',
        'isrc': None,
        'explicit': None,
        'spotify_track_id': track_id,
        'spotify_album_id': None,
        'spotify_artist_ids': [],
        'spotify_url': f'https://open.spotify.com/track/{track_id}',
        'cover_url': None,
        'duration': (duration_ms or 0) / 1000,
        # --- filled by enrichment ---
        'genres': [],
        'bpm': None,
        'label': None,
        'copyright': None,
        'barcode': None,
        'catalog_number': None,
        'original_date': None,
        'artist_sort': None,
        'release_country': None,
        'hires_cover_url': None,
        'lyrics': None,
        'synced_lyrics': None,
        'mb_recording_id': None,
        'mb_release_id': None,
        'mb_release_group_id': None,
        'mb_release_track_id': None,
        'mb_artist_ids': [],
        'deezer_track_id': None,
        'itunes_track_id': None,
        'sources': ['Spotify'],
    }
    track.update({k: v for k, v in extra.items() if v})
    return track

def fetch_track(track_id, album_context=None):
    """
    Full details for one track from Spotify's public pages: title, artists (with IDs),
    duration, explicit flag, ISRC (when the page exposes it), album, album artist,
    track number / total, release date, and cover art.
    """
    entity = fetch_entity('track', track_id)
    artist_objs = [a for a in entity.get('artists') or [] if a.get('name')]
    artists = [a['name'] for a in artist_objs] or _split_artists(entity.get('subtitle'))
    artist_ids = [_spotify_id_from_uri(a.get('uri')) for a in artist_objs if a.get('uri')]

    if album_context:
        album = {
            'album': album_context['album'],
            'album_artist': album_context['album_artist'],
            'release_date': album_context['release_date'],
            'cover_url': album_context['cover_url'],
            'total_tracks': album_context['total_tracks'],
            'track_number': album_context['positions'].get(track_id),
            'spotify_album_id': album_context['spotify_album_id'],
        }
    else:
        album = lookup_album_info(track_id)

    # Still no album? Look for an album reference inside the track's own page data
    if not album.get('album') or not album.get('spotify_album_id'):
        for key, value in _find_album_in_entity(entity).items():
            if value and not album.get(key):
                album[key] = value
        if album.get('spotify_album_id') and not album.get('total_tracks'):
            try:
                context = fetch_album_context(album['spotify_album_id'])
                for key in ('album', 'album_artist', 'release_date', 'cover_url', 'total_tracks'):
                    if context.get(key) and not album.get(key):
                        album[key] = context[key]
                album.setdefault('track_number', context['positions'].get(track_id))
            except Exception:
                pass

    return make_track(
        track_id,
        entity.get('name') or entity.get('title'),
        artists,
        entity.get('duration'),
        spotify_artist_ids=artist_ids,
        isrc=entity.get('isrc'),
        explicit=entity.get('isExplicit') or None,
        album=album.get('album'),
        album_artist=album.get('album_artist'),
        track_number=album.get('track_number'),
        total_tracks=album.get('total_tracks'),
        spotify_album_id=album.get('spotify_album_id'),
        release_date=_iso_date(entity) or album.get('release_date') or '',
        cover_url=best_cover_url(entity) or album.get('cover_url'),
    )

def fetch_spotify_tracks(kind, spotify_id):
    """Returns (collection_name_or_None, [track dicts]) for a Spotify track/album/playlist."""
    if kind == 'track':
        return None, [fetch_track(spotify_id)]

    entity = fetch_entity(kind, spotify_id)
    name = entity.get('name') or entity.get('title') or "Untitled"
    items = [i for i in entity.get('trackList') or [] if str(i.get('uri', '')).startswith('spotify:track:')]

    if kind == 'album':
        context = _album_context_from_entity(spotify_id, entity)
        tracks = []
        for number, item in enumerate(items, start=1):
            track_id = item['uri'].split(':')[-1]
            try:
                # Per-track page adds artist IDs, explicit flag, and ISRC when available
                tracks.append(fetch_track(track_id, album_context=context))
            except Exception:
                tracks.append(make_track(
                    track_id,
                    item.get('title'),
                    _split_artists(item.get('subtitle')),
                    item.get('duration'),
                    explicit=item.get('isExplicit') or None,
                    album=context['album'],
                    album_artist=context['album_artist'],
                    track_number=number,
                    total_tracks=len(items),
                    release_date=context['release_date'],
                    cover_url=context['cover_url'],
                    spotify_album_id=spotify_id,
                ))
            time.sleep(0.3)  # be polite to Spotify's servers
        return name, tracks

    # Playlist: look up each track for its own cover art, album, and release date
    tracks = []
    for item in items:
        track_id = item['uri'].split(':')[-1]
        try:
            tracks.append(fetch_track(track_id))
        except Exception:
            # Fall back to the (thinner) data from the playlist listing
            tracks.append(make_track(
                track_id, item.get('title'), _split_artists(item.get('subtitle')), item.get('duration'),
                explicit=item.get('isExplicit') or None))
        time.sleep(0.3)  # be polite to Spotify's servers
    return name, tracks


# ------------------------ Matching helpers (enrichment) ---------------------

def _norm(text):
    """Lowercase, accent/punctuation-insensitive form used to compare names."""
    text = unicodedata.normalize('NFKC', text or '').casefold()
    text = re.sub(r'\(.*?\)|\[.*?\]', ' ', text)            # drop (feat. X), [Remastered]
    text = re.sub(r'\b(?:feat|ft|featuring)\b.*$', ' ', text)
    text = re.sub(r'\s[-–—]\s.*$', ' ', text)                # drop " - Remastered 2011" suffixes
    return re.sub(r'[\W_]+', ' ', text).strip()

def _similar(a, b):
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    return difflib.SequenceMatcher(None, a, b).ratio()

def _artist_matches(wanted, found):
    """True if two artist names are close, or one contains the other ('A' in 'A & B')."""
    na, nb = _norm(wanted), _norm(found)
    if not na or not nb:
        return False
    return na in nb or nb in na or _similar(wanted, found) >= MATCH_THRESHOLD

def _duration_ok(track, seconds):
    if not track['duration'] or not seconds:
        return True  # nothing to compare against
    return abs(track['duration'] - seconds) <= META_DURATION_TOLERANCE


# ------------------------------- Deezer -------------------------------------

def deezer_lookup(track):
    """ISRC, BPM, genre, label, UPC, disc number, explicit flag (no key needed)."""
    base = 'https://api.deezer.com'
    data = None

    if track['isrc']:
        data = http_get_json(f"{base}/track/isrc:{track['isrc']}", allow_404=True)
        if data and data.get('error'):
            data = None

    if not data:
        query = f'artist:"{track["primary_artist"]}" track:"{track["title"]}"'
        results = http_get_json(f"{base}/search?q={urllib.parse.quote(query)}&limit=10") or {}
        candidates = []
        for item in results.get('data') or []:
            if _similar(track['title'], item.get('title')) < MATCH_THRESHOLD:
                continue
            if not _artist_matches(track['primary_artist'], (item.get('artist') or {}).get('name')):
                continue
            if not _duration_ok(track, item.get('duration')):
                continue
            album_sim = _similar(track['album'], (item.get('album') or {}).get('title')) if track['album'] else 0
            candidates.append((album_sim, item))
        if not candidates:
            return {}
        best = max(candidates, key=lambda c: c[0])[1]
        data = http_get_json(f"{base}/track/{best['id']}")

    if not data or data.get('error'):
        return {}

    found = {
        'isrc': data.get('isrc'),
        'bpm': data.get('bpm') or None,
        'disc_number': data.get('disk_number') or None,
        'disc_track_number': data.get('track_position') or None,
        'explicit': data.get('explicit_lyrics'),
        'deezer_track_id': data.get('id'),
        'album': (data.get('album') or {}).get('title'),
    }
    album_id = (data.get('album') or {}).get('id')
    if album_id:
        time.sleep(0.2)
        album = http_get_json(f"{base}/album/{album_id}") or {}
        if not album.get('error'):
            found['label'] = album.get('label')
            found['barcode'] = album.get('upc')
            found['genres'] = [g['name'] for g in (album.get('genres') or {}).get('data') or [] if g.get('name')]
            found['release_date'] = album.get('release_date')
            found['album_artist'] = (album.get('artist') or {}).get('name')
            if not track['total_tracks']:
                found['total_tracks'] = album.get('nb_tracks')
    return found


# ------------------------------- iTunes -------------------------------------

def itunes_lookup(track):
    """Genre, disc counts, copyright, and a 1400px cover (no key needed)."""
    term = urllib.parse.quote(f"{track['primary_artist']} {track['title']}")
    results = http_get_json(
        f"https://itunes.apple.com/search?term={term}&media=music&entity=song&limit=15") or {}

    candidates = []
    for item in results.get('results') or []:
        if _similar(track['title'], item.get('trackName')) < MATCH_THRESHOLD:
            continue
        if not _artist_matches(track['primary_artist'], item.get('artistName')):
            continue
        if not _duration_ok(track, (item.get('trackTimeMillis') or 0) / 1000):
            continue
        album_sim = _similar(track['album'], item.get('collectionName')) if track['album'] else 0
        candidates.append((album_sim, item))
    if not candidates:
        return {}

    album_sim, item = max(candidates, key=lambda c: c[0])
    found = {
        'genres': [item['primaryGenreName']] if item.get('primaryGenreName') else [],
        'disc_number': item.get('discNumber'),
        'disc_total': item.get('discCount'),
        'disc_track_number': item.get('trackNumber'),
        'itunes_track_id': item.get('trackId'),
        'album': item.get('collectionName'),
        'album_artist': item.get('collectionArtistName') or item.get('artistName'),
        'total_tracks': item.get('trackCount'),
        'release_date': (item.get('releaseDate') or '')[:10],
        'explicit': (True if item.get('trackExplicitness') == 'explicit'
                     else False if item.get('trackExplicitness') == 'notExplicit' else None),
    }

    # Only swap in the hi-res cover when it is clearly the same album
    artwork = item.get('artworkUrl100')
    same_album = (not track['album']) or album_sim >= MATCH_THRESHOLD
    if UPGRADE_COVER and artwork and same_album:
        size = ITUNES_COVER_SIZE
        found['hires_cover_url'] = re.sub(r'\d+x\d+(bb)?(?=\.\w+$)', f'{size}x{size}bb', artwork)

    # Copyright text only appears on the album lookup
    if item.get('collectionId') and same_album:
        time.sleep(0.2)
        album = http_get_json(f"https://itunes.apple.com/lookup?id={item['collectionId']}") or {}
        for entry in album.get('results') or []:
            if entry.get('wrapperType') == 'collection' and entry.get('copyright'):
                found['copyright'] = entry['copyright']
                break
    return found


# ----------------------------- MusicBrainz ----------------------------------

_last_mb_call = 0.0

def mb_get(path):
    """MusicBrainz request, throttled to its 1 request/second rule."""
    global _last_mb_call
    wait = 1.1 - (time.time() - _last_mb_call)
    if wait > 0:
        time.sleep(wait)
    try:
        return http_get_json(f"https://musicbrainz.org/ws/2/{path}",
                             headers={'User-Agent': MB_USER_AGENT}, allow_404=True)
    finally:
        _last_mb_call = time.time()

def _ranked_names(items):
    """Genre/tag objects -> names, most-voted first."""
    items = sorted(items or [], key=lambda g: g.get('count', 0), reverse=True)
    return [g['name'] for g in items if g.get('name')]

def musicbrainz_lookup(track):
    """MusicBrainz IDs, label, catalog number, barcode, genres, original release date."""
    isrc = track.get('isrc')
    if not isrc:
        return {}

    isrc_result = mb_get(f"isrc/{urllib.parse.quote(isrc)}?fmt=json") or {}
    recordings = isrc_result.get('recordings') or []
    scored = [(_similar(track['title'], r.get('title')), r) for r in recordings]
    scored = [s for s in scored if s[0] >= 0.6]
    if not scored:
        return {}
    recording_stub = max(scored, key=lambda s: s[0])[1]

    recording = mb_get(f"recording/{recording_stub['id']}"
                       f"?inc=artist-credits+releases+release-groups+genres+tags&fmt=json") or {}
    found = {'mb_recording_id': recording_stub['id']}

    credits = [c for c in recording.get('artist-credit') or [] if c.get('artist')]
    found['mb_artist_ids'] = [c['artist']['id'] for c in credits if c['artist'].get('id')]
    if credits:
        found['artist_sort'] = credits[0]['artist'].get('sort-name')
    found['genres'] = _ranked_names(recording.get('genres')) or _ranked_names(recording.get('tags'))

    releases = recording.get('releases') or []
    if not releases:
        return found

    def release_rank(release):
        official = 1 if release.get('status') == 'Official' else 0
        album_sim = _similar(track['album'], release.get('title')) if track['album'] else 0
        date_ok = 1 if track['release_date'] and (release.get('date') or '')[:4] == track['release_date'][:4] else 0
        return (album_sim, official, date_ok)

    release_stub = max(releases, key=release_rank)
    release = mb_get(f"release/{release_stub['id']}"
                     f"?inc=labels+release-groups+genres+recordings+media&fmt=json") or {}

    found['mb_release_id'] = release_stub['id']
    found['album'] = release.get('title') or release_stub.get('title')
    found['barcode'] = release.get('barcode')
    found['release_country'] = release.get('country')
    label_infos = release.get('label-info') or []
    for info in label_infos:
        if (info.get('label') or {}).get('name'):
            found['label'] = info['label']['name']
            found['catalog_number'] = info.get('catalog-number')
            break

    group = release.get('release-group') or {}
    found['mb_release_group_id'] = group.get('id')
    found['original_date'] = group.get('first-release-date')
    if not found['genres']:
        found['genres'] = _ranked_names(release.get('genres')) or _ranked_names(group.get('genres'))

    for medium in release.get('media') or []:
        for entry in medium.get('tracks') or []:
            if (entry.get('recording') or {}).get('id') == recording_stub['id']:
                found['mb_release_track_id'] = entry.get('id')
                break
    return found


# ------------------------------- Lyrics -------------------------------------

LRC_LINE = re.compile(r'\[(\d+):(\d+(?:\.\d+)?)\](.*)')

def parse_synced_lyrics(lrc):
    """'[mm:ss.xx] text' lines -> [(text, milliseconds)] for the SYLT frame."""
    lines = []
    for raw in (lrc or '').splitlines():
        match = LRC_LINE.match(raw.strip())
        if match:
            ms = int((int(match.group(1)) * 60 + float(match.group(2))) * 1000)
            lines.append((match.group(3).strip(), ms))
    return lines

def lrclib_lookup(track):
    """Plain + synced lyrics from LRCLIB (free, no key)."""
    params = {
        'artist_name': track['primary_artist'],
        'track_name': track['title'],
    }
    if track['album']:
        params['album_name'] = track['album']
    if track['duration']:
        params['duration'] = int(round(track['duration']))

    data = http_get_json(f"https://lrclib.net/api/get?{urllib.parse.urlencode(params)}", allow_404=True)

    if not data:  # exact lookup missed; try a looser search
        search = urllib.parse.urlencode({'artist_name': track['primary_artist'], 'track_name': track['title']})
        for item in http_get_json(f"https://lrclib.net/api/search?{search}") or []:
            if _similar(track['title'], item.get('trackName')) >= MATCH_THRESHOLD \
                    and _duration_ok(track, item.get('duration')):
                data = item
                break
    if not data or data.get('instrumental'):
        return {}

    found = {'lyrics': data.get('plainLyrics') or None}
    synced = parse_synced_lyrics(data.get('syncedLyrics'))
    if synced:
        found['synced_lyrics'] = synced
    return found


# ------------------------------ Enrichment ----------------------------------

EMPTY = (None, '', [])

def merge_found(track, found, source):
    """Copies values from an enrichment source into the track, filling gaps only."""
    changed = False
    for key, value in found.items():
        if value in EMPTY:
            continue
        if key == 'genres':
            existing = {g.casefold() for g in track['genres']}
            for genre in value:
                genre = genre.strip()
                if genre and genre.casefold() not in existing:
                    track['genres'].append(genre)
                    existing.add(genre.casefold())
                    changed = True
        elif track.get(key) in EMPTY:
            track[key] = value
            changed = True
    if changed:
        track['sources'].append(source)

def enrich_track(track):
    """Runs every enrichment source; a failing source never stops the others."""
    sources = (
        ('Deezer', deezer_lookup),
        ('iTunes', itunes_lookup),
        ('MusicBrainz', musicbrainz_lookup),   # needs the ISRC, so it runs after Deezer
        ('LRCLIB', lrclib_lookup),
    )
    for name, lookup in sources:
        try:
            found = lookup(track)
        except Exception as e:
            log(f"   ⚠️ {name} lookup skipped: {e}")
            continue
        if found:
            merge_found(track, found, name)
    track['genres'] = track['genres'][:5]
    if not track['track_number'] and track['disc_track_number']:
        track['track_number'] = track['disc_track_number']


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
            log(f"   ⚠️ Could not download album art: {e}")
            _cover_cache[url] = None
    return _cover_cache[url]

def pick_cover(track):
    """Hi-res cover when we have a verified one, otherwise Spotify's own cover."""
    for url in (track['hires_cover_url'], track['cover_url']):
        cover = download_cover(url)
        if cover:
            return cover
    return None


# ------------------------------ Tagging ------------------------------------

def _year(date_text):
    return (date_text or '')[:4] if re.match(r'^\d{4}', date_text or '') else ''

def write_id3_tags(mp3_path, track, cover_bytes):
    """
    Replaces whatever tags the conversion left behind with clean metadata
    and embeds the album art as the front cover. Returns the list of fields written.
    """
    tags = ID3()  # Fresh tag, so no leftover source-video metadata survives
    written = []

    def add(label, frame):
        tags.add(frame)
        written.append(label)

    def custom(description, value):
        """User-defined TXXX frame (read by Picard, foobar2000, MusicBee, Mp3tag, ...)."""
        if value not in EMPTY:
            tags.add(TXXX(encoding=3, desc=description, text=value if isinstance(value, list) else str(value)))

    # --- the essentials ---
    add('title', TIT2(encoding=3, text=track['title']))
    add('artist', TPE1(encoding=3, text=track['artist']))
    if track['album']:
        add('album', TALB(encoding=3, text=track['album']))
    if track['album_artist']:
        add('album artist', TPE2(encoding=3, text=track['album_artist']))
        if _norm(track['album_artist']) == 'various artists':
            add('compilation', TCMP(encoding=3, text='1'))

    # --- dates ---
    if track['release_date']:
        add('year/date', TDRC(encoding=3, text=track['release_date']))
    if track['original_date']:
        add('original year', TDOR(encoding=3, text=track['original_date']))

    # --- numbering ---
    if track['track_number']:
        # Multi-disc albums: use the number within the disc, as players expect
        multi_disc = (track['disc_total'] or 1) > 1 or (track['disc_number'] or 1) > 1
        if multi_disc and track['disc_track_number']:
            number = str(track['disc_track_number'])
        else:
            number = str(track['track_number'])
            if track['total_tracks']:
                number += f"/{track['total_tracks']}"
        add('track number', TRCK(encoding=3, text=number))
    if track['disc_number']:
        disc = str(track['disc_number'])
        if track['disc_total']:
            disc += f"/{track['disc_total']}"
        add('disc number', TPOS(encoding=3, text=disc))

    # --- classification ---
    if track['genres']:
        add('genre', TCON(encoding=3, text=track['genres']))
    if track['bpm']:
        add('BPM', TBPM(encoding=3, text=str(int(round(track['bpm'])))))
    if track['isrc']:
        add('ISRC', TSRC(encoding=3, text=track['isrc']))
    if track['label']:
        add('label', TPUB(encoding=3, text=track['label']))
    if track['copyright']:
        add('copyright', TCOP(encoding=3, text=track['copyright']))
    if track['artist_sort']:
        add('artist sort', TSOP(encoding=3, text=track['artist_sort']))

    # --- custom fields ---
    if len(track['artists']) > 1:
        custom('ARTISTS', track['artists'])
        written.append('artist list')
    custom('BARCODE', track['barcode'])
    custom('CATALOGNUMBER', track['catalog_number'])
    custom('MusicBrainz Album Release Country', track['release_country'])
    custom('MusicBrainz Album Id', track['mb_release_id'])
    custom('MusicBrainz Release Group Id', track['mb_release_group_id'])
    custom('MusicBrainz Release Track Id', track['mb_release_track_id'])
    custom('MusicBrainz Artist Id', track['mb_artist_ids'])
    custom('Spotify Track Id', track['spotify_track_id'])
    custom('Spotify Album Id', track['spotify_album_id'])
    custom('Spotify Artist Id', track['spotify_artist_ids'])
    custom('Deezer Track Id', track['deezer_track_id'])
    custom('iTunes Track Id', track['itunes_track_id'])
    if track['explicit']:
        custom('EXPLICIT', '1')
        written.append('explicit flag')
    if track['mb_recording_id']:
        add('MusicBrainz recording ID',
            UFID(owner='http://musicbrainz.org', data=track['mb_recording_id'].encode('ascii')))
        written.append('MusicBrainz IDs')

    # --- links ---
    if track['spotify_url']:
        add('Spotify URL', WOAS(url=track['spotify_url']))
    if track['spotify_artist_ids']:
        tags.add(WOAR(url=f"https://open.spotify.com/artist/{track['spotify_artist_ids'][0]}"))

    # --- lyrics ---
    if track['lyrics']:
        add('lyrics', USLT(encoding=3, lang='XXX', desc='', text=track['lyrics']))
    if track['synced_lyrics']:
        add('synced lyrics', SYLT(encoding=3, lang='XXX', format=2, type=1, desc='',
                                  text=track['synced_lyrics']))

    # --- comment + cover ---
    add('comment', COMM(encoding=3, lang='eng', desc='',
                        text=f"Metadata from: {', '.join(track['sources'])}"))
    if cover_bytes:
        mime = 'image/png' if cover_bytes[:8] == b'\x89PNG\r\n\x1a\n' else 'image/jpeg'
        add('album art', APIC(encoding=3, mime=mime, type=3, desc='Cover', data=cover_bytes))

    tags.save(mp3_path, v2_version=3)  # ID3v2.3 for the widest player compatibility
    return written



# ------------------------------ Downloading --------------------------------

def _progress_hook(d):
    """yt-dlp progress hook: reports download percent and aborts on cancel."""
    _check_cancel()
    if d.get('status') == 'downloading':
        total = d.get('total_bytes') or d.get('total_bytes_estimate')
        if total:
            emit('progress', percent=round(d.get('downloaded_bytes', 0) / total * 100, 1))
    elif d.get('status') == 'finished':
        emit('progress', percent=100.0, converting=True)

def build_ydl_opts(bitrate, output_dir, ffmpeg_dir=None):
    """Builds the yt-dlp options dict for a given bitrate/output folder."""
    opts = {
        'format': 'bestaudio/best',
        'outtmpl': os.path.join(output_dir, '%(artist)s - %(title)s.%(ext)s'),
        'postprocessors': [
            {
                'key': 'FFmpegExtractAudio',
                'preferredcodec': 'mp3',
                'preferredquality': bitrate,
            },
        ],
        'quiet': _listener is not None,   # a host gets structured progress instead
        'noprogress': _listener is not None,
        'progress_hooks': [_progress_hook],
        'ignoreerrors': True,
    }
    if ffmpeg_dir:
        opts['ffmpeg_location'] = ffmpeg_dir   # folder holding ffmpeg and ffprobe
    return opts

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
        log(f"   ⚠️ No result within {DURATION_TOLERANCE}s of the Spotify duration; using closest match.")

    return best.get('url') or f"https://www.youtube.com/watch?v={best['id']}"

def download_track(ydl, search_ydl, track, enrich=True):
    """Downloads one Spotify track as MP3, then enriches, tags it and embeds the album art."""
    _check_cancel()
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

    if enrich:
        log("   🔎 Gathering extra metadata (Deezer, iTunes, MusicBrainz, lyrics)...")
        enrich_track(track)

    written = write_id3_tags(mp3_path, track, pick_cover(track))
    log(f"   🏷️  Tagged: {', '.join(written)}")
    if track['album']:
        log(f"   💿 Album: {track['album']}")
    else:
        log("   ⚠️ No album found for this track on any source (it may be a single or unreleased).")

def preview_spotify(url):
    """
    Reads a Spotify link without downloading. Returns {'kind', 'name', 'tracks': [...]}.
    Raises ValueError for a bad link and RuntimeError when Spotify can't be read.
    """
    spotify = parse_spotify_url(url)
    if not spotify:
        raise ValueError("That doesn't look like a Spotify track, album, or playlist link.")
    kind, spotify_id = spotify
    try:
        name, tracks = fetch_spotify_tracks(kind, spotify_id)
    except Exception as e:
        raise RuntimeError(f"Could not read that Spotify {kind}: {e} "
                           "(Check the link and your connection. Playlists must be public.)") from e
    return {'kind': kind, 'name': name, 'tracks': tracks}

def download_spotify(url, bitrate, output_dir, enrich=True, ffmpeg_dir=None,
                     cancel=None, track_ids=None):
    """
    Handles Spotify track, album, and playlist links.
    cancel: optional threading.Event; set it to stop after/within the current track.
    track_ids: optional collection of Spotify track ids; only those tracks are downloaded.
    Returns {'ok': [label, ...], 'failed': [{'track': label, 'error': msg}], 'folder': path,
             'cancelled': bool, 'error': msg-or-None}.
    """
    global _cancel_event
    _cancel_event = cancel
    summary = {'ok': [], 'failed': [], 'folder': output_dir, 'cancelled': False, 'error': None}

    try:
        preview = preview_spotify(url)
    except (ValueError, RuntimeError) as e:
        log(f"❌ {e}")
        summary['error'] = str(e)
        return summary

    kind, name, tracks = preview['kind'], preview['name'], preview['tracks']
    if track_ids is not None:
        wanted = set(track_ids)
        tracks = [t for t in tracks if t['spotify_track_id'] in wanted]

    total = len(tracks)
    if total == 0:
        log("⚠️ No downloadable tracks were found.")
        summary['error'] = "No downloadable tracks were found."
        return summary

    target_dir = output_dir
    if name:
        target_dir = os.path.join(output_dir, sanitize_folder_name(name))
        os.makedirs(target_dir, exist_ok=True)
        log(f"\n📃 Spotify {kind} detected: \"{name}\" ({total} track(s))")
        log(f"📁 Saving tracks to: {target_dir}")
    summary['folder'] = target_dir
    emit('start', kind=kind, name=name, total=total, folder=target_dir)

    ydl_opts = build_ydl_opts(bitrate, target_dir, ffmpeg_dir)
    search_opts = {'quiet': True, 'no_warnings': True, 'extract_flat': True, 'ignoreerrors': True}

    with yt_dlp.YoutubeDL(ydl_opts) as ydl, yt_dlp.YoutubeDL(search_opts) as search_ydl:
        for index, track in enumerate(tracks, start=1):
            if cancel is not None and cancel.is_set():
                summary['cancelled'] = True
                break
            label = f"{track['artist']} - {track['title']}"
            log(f"\n[{index}/{total}] Processing: {label}")
            emit('track_start', index=index, total=total, label=label)
            try:
                download_track(ydl, search_ydl, track, enrich=enrich)
                summary['ok'].append(label)
                emit('track_done', index=index, label=label)
            except Cancelled:
                summary['cancelled'] = True
                break
            except Exception as e:
                log(f"❌ Skipped \"{label}\" due to an error: {e}")
                summary['failed'].append({'track': label, 'error': str(e)})
                emit('track_error', index=index, label=label, error=str(e))

    if summary['cancelled']:
        log(f"\n⏹️ Cancelled. {len(summary['ok'])}/{total} track(s) saved to: {target_dir}")
    else:
        log(f"\n🎉 Download complete! {len(summary['ok'])}/{total} track(s) saved to: {target_dir}")
    _cancel_event = None
    return summary
