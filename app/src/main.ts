import { app, BrowserWindow, ipcMain, dialog, shell } from 'electron';
import { spawn, ChildProcessWithoutNullStreams } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';

let win: BrowserWindow | null = null;
let job: ChildProcessWithoutNullStreams | null = null; // the running download process, if any

// ---- locating the Python backend and FFmpeg -------------------------------

function backendCommand(args: string[]): { cmd: string; args: string[] } {
  const isWindows = process.platform === 'win32';
  if (app.isPackaged) {
    const exe = isWindows ? 'backend.exe' : 'backend';
    return { cmd: path.join(process.resourcesPath, 'backend', exe), args };
  }
  // out/main.js -> app/out -> repo root
  const script = path.join(__dirname, '..', '..', 'backend', 'backend.py');
  const python = process.env.PYTHON || (isWindows ? 'python' : 'python3');
  return { cmd: python, args: ['-X', 'utf8', '-u', script, ...args] };
}

// Packaged builds ship ffmpeg/ffprobe; in dev the system install on PATH is used.
function ffmpegArgs(): string[] {
  if (!app.isPackaged) return [];
  return ['--ffmpeg-dir', path.join(process.resourcesPath, 'bin')];
}

function run(args: string[]): ChildProcessWithoutNullStreams {
  const { cmd, args: fullArgs } = backendCommand(args);
  return spawn(cmd, fullArgs, {
    windowsHide: true,
    env: { ...process.env, PYTHONIOENCODING: 'utf-8' },
  });
}

// Calls onEvent for each complete JSON line on stdout.
function readEvents(proc: ChildProcessWithoutNullStreams, onEvent: (ev: BackendEvent) => void): void {
  let buffer = '';
  proc.stdout.setEncoding('utf8');
  proc.stdout.on('data', (chunk: string) => {
    buffer += chunk;
    let nl: number;
    while ((nl = buffer.indexOf('\n')) >= 0) {
      const line = buffer.slice(0, nl).trim();
      buffer = buffer.slice(nl + 1);
      if (!line) continue;
      try {
        onEvent(JSON.parse(line) as BackendEvent);
      } catch {
        /* ignore non-JSON noise */
      }
    }
  });
}

function sendEvent(ev: BackendEvent): void {
  win?.webContents.send('download:event', ev);
}

function failed(error: string): DoneEvent {
  return { event: 'done', ok: [], failed: [], error };
}

// ---- settings --------------------------------------------------------------

const settingsFile = () => path.join(app.getPath('userData'), 'settings.json');

function loadSettings(): Partial<Settings> {
  try {
    return JSON.parse(fs.readFileSync(settingsFile(), 'utf8'));
  } catch {
    return {};
  }
}

// ---- IPC ---------------------------------------------------------------------

ipcMain.handle('settings:get', (): Settings => ({
  folder: app.getPath('music'),
  bitrate: '192',
  enrich: true,
  ...loadSettings(),
}));

ipcMain.handle('settings:set', (_e, settings: Settings): void => {
  fs.writeFileSync(settingsFile(), JSON.stringify(settings));
});

ipcMain.handle('folder:pick', async (_e, current: string): Promise<string | null> => {
  const r = await dialog.showOpenDialog(win!, {
    properties: ['openDirectory', 'createDirectory'],
    defaultPath: current,
  });
  return r.canceled ? null : r.filePaths[0];
});

ipcMain.handle('folder:open', (_e, folder: string) => shell.openPath(folder));

ipcMain.handle('preview', (_e, url: string) => new Promise<PreviewResult>((resolve) => {
  const proc = run(['--url', url, '--preview']);
  let last: BackendEvent = { event: 'error', message: 'The backend did not respond.' };
  let stderr = '';
  readEvents(proc, (ev) => { last = ev; });
  proc.stderr.on('data', (d) => { stderr += d; });
  proc.on('error', (err) => resolve({ error: `Could not start the backend: ${err.message}` }));
  proc.on('close', () => {
    if (last.event === 'preview') {
      resolve({ kind: last.kind, name: last.name, tracks: last.tracks });
    } else {
      resolve({ error: (last.event === 'error' && last.message) || stderr.trim() || 'Unknown error' });
    }
  });
}));

ipcMain.handle('download:start', (_e, opts: DownloadOptions): { started: true } | { error: string } => {
  if (job) return { error: 'A download is already running.' };
  const args = ['--url', opts.url, '--out', opts.folder, '--bitrate', String(opts.bitrate), ...ffmpegArgs()];
  if (!opts.enrich) args.push('--no-enrich');
  for (const id of opts.trackIds) args.push('--track-id', id);

  const proc = run(args);
  job = proc;
  let sawDone = false;
  readEvents(proc, (ev) => {
    if (ev.event === 'done') sawDone = true;
    sendEvent(ev);
  });
  proc.on('error', (err) => {
    sendEvent(failed(`Could not start the backend: ${err.message}`));
    job = null;
  });
  proc.on('close', (code) => {
    if (!sawDone) sendEvent(failed(`The backend stopped unexpectedly (exit code ${code}).`));
    job = null;
  });
  return { started: true };
});

ipcMain.handle('download:cancel', (): void => {
  if (!job) return;
  const proc = job;
  try { proc.stdin.write('cancel\n'); } catch { /* already closed */ }
  // If it hasn't stopped on its own (e.g. mid-search), force it.
  setTimeout(() => { if (job === proc) proc.kill(); }, 8000);
});

// ---- window ------------------------------------------------------------------

function createWindow(): void {
  win = new BrowserWindow({
    width: 980,
    height: 720,
    minWidth: 720,
    minHeight: 560,
    backgroundColor: '#121212',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  win.setMenuBarVisibility(false);
  win.loadFile(path.join(__dirname, 'renderer', 'index.html'));
}

app.whenReady().then(createWindow);
app.on('before-quit', () => { job?.kill(); });
app.on('window-all-closed', () => app.quit());
