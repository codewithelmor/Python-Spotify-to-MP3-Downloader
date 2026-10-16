"""
JSON-lines front end for the Electron app. One JSON object per stdout line:
  {"event": "preview", "kind": ..., "name": ..., "tracks": [...]}
  {"event": "start" | "track_start" | "track_done" | "track_error" | "progress" | "log", ...}
  {"event": "done", "ok": [...], "failed": [...], "folder": ..., "cancelled": bool, "error": ...}
  {"event": "error", "message": ...}
A line "cancel" on stdin stops the download (the host can also just kill the process).
"""
import argparse
import json
import sys
import threading

import core

# Only the fields the UI needs for a track list (the full dict has ~40 keys).
PREVIEW_FIELDS = ('spotify_track_id', 'artist', 'title', 'album', 'duration', 'cover_url')


def send(event, **data):
    sys.stdout.write(json.dumps({'event': event, **data}, ensure_ascii=False) + '\n')
    sys.stdout.flush()


def watch_stdin_for_cancel(cancel):
    for line in sys.stdin:
        if line.strip().lower() == 'cancel':
            cancel.set()
            return


def main():
    parser = argparse.ArgumentParser(description='Spotify to MP3 backend (JSON lines on stdout)')
    parser.add_argument('--url', required=True)
    parser.add_argument('--preview', action='store_true', help='list tracks and exit')
    parser.add_argument('--out', default='.')
    parser.add_argument('--bitrate', default='192')
    parser.add_argument('--no-enrich', action='store_true')
    parser.add_argument('--ffmpeg-dir', help='folder containing ffmpeg and ffprobe')
    parser.add_argument('--track-id', action='append', dest='track_ids',
                        help='only download this Spotify track id (repeatable)')
    args = parser.parse_args()

    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8')

    if args.preview:
        try:
            result = core.preview_spotify(args.url)
        except (ValueError, RuntimeError) as e:
            send('error', message=str(e))
            return 1
        tracks = [{k: t.get(k) for k in PREVIEW_FIELDS} for t in result['tracks']]
        send('preview', kind=result['kind'], name=result['name'], tracks=tracks)
        return 0

    if not args.bitrate.isdigit():
        send('error', message='Bitrate must be a number of kbps.')
        return 1

    cancel = threading.Event()
    threading.Thread(target=watch_stdin_for_cancel, args=(cancel,), daemon=True).start()
    core.set_listener(lambda event, data: send(event, **data))

    summary = core.download_spotify(
        args.url, args.bitrate, args.out,
        enrich=not args.no_enrich, ffmpeg_dir=args.ffmpeg_dir,
        cancel=cancel, track_ids=args.track_ids,
    )
    send('done', **summary)
    return 1 if summary['error'] else 0


if __name__ == '__main__':
    sys.exit(main())
