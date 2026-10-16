// Ambient types shared by main, preload and renderer (no imports/exports on purpose,
// so the renderer stays a plain browser script).

/** One track as listed by `backend.py --preview`. */
interface TrackPreview {
  spotify_track_id: string;
  artist: string;
  title: string;
  album: string | null;
  duration: number;
  cover_url: string | null;
}

interface PreviewData {
  error?: undefined;
  kind: string;
  name: string;
  tracks: TrackPreview[];
}

type PreviewResult = PreviewData | { error: string };

/** Events the Python backend writes as JSON lines (see backend/backend.py). */
type BackendEvent =
  | { event: 'preview'; kind: string; name: string; tracks: TrackPreview[] }
  | { event: 'error'; message: string }
  | { event: 'log'; message: string }
  | { event: 'start'; kind: string; name: string; total: number; folder: string }
  | { event: 'track_start'; index: number; total: number; label: string }
  | { event: 'progress'; percent: number; converting?: boolean }
  | { event: 'track_done'; index: number; label: string }
  | { event: 'track_error'; index: number; label: string; error: string }
  | DoneEvent;

interface DoneEvent {
  event: 'done';
  ok: string[];
  failed: { track: string; error: string }[];
  folder?: string;
  cancelled?: boolean;
  error: string | null;
}

interface Settings {
  folder: string;
  bitrate: string;
  enrich: boolean;
}

interface DownloadOptions {
  url: string;
  folder: string;
  bitrate: string;
  enrich: boolean;
  trackIds: string[];
}

/** What preload.ts exposes to the renderer as `window.api`. */
interface Api {
  getSettings(): Promise<Settings>;
  saveSettings(settings: Settings): Promise<void>;
  pickFolder(current: string): Promise<string | null>;
  openFolder(folder: string): Promise<string>;
  preview(url: string): Promise<PreviewResult>;
  startDownload(opts: DownloadOptions): Promise<{ started: true } | { error: string }>;
  cancelDownload(): Promise<void>;
  onEvent(handler: (ev: BackendEvent) => void): () => void;
}

interface Window {
  api: Api;
}
