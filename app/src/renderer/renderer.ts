// Plain browser script (no imports/exports); types come from ../types.d.ts.

function el<T extends HTMLElement = HTMLElement>(id: string): T {
  return document.getElementById(id) as T;
}

let preview: PreviewData | null = null;
let folder = '';
let running = false;
let rows: HTMLLIElement[] = []; // <li> elements for the tracks being downloaded, in order
let lastFolder = '';

function showMessage(text: string): void {
  el('message').textContent = text;
  el('message').hidden = !text;
}

function fmtTime(seconds: number): string {
  const s = Math.round(seconds || 0);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
}

function trackBoxes(): HTMLInputElement[] {
  return [...document.querySelectorAll<HTMLInputElement>('#tracks input')];
}

function selectedIds(): string[] {
  return trackBoxes().filter((b) => b.checked).map((b) => b.dataset.id!);
}

function setRunning(value: boolean): void {
  running = value;
  for (const id of ['url', 'previewBtn', 'selectAll', 'bitrate', 'enrich', 'folderBtn']) {
    el<HTMLInputElement>(id).disabled = value;
  }
  for (const box of trackBoxes()) box.disabled = value;
  el('downloadBtn').hidden = value;
  el('cancelBtn').hidden = !value;
  el<HTMLButtonElement>('cancelBtn').disabled = false;
  el('cancelBtn').textContent = 'Cancel';
}

function updateCount(): void {
  if (!preview) return;
  const selected = selectedIds().length;
  el('listCount').textContent = `${selected} of ${preview.tracks.length} selected`;
  el<HTMLButtonElement>('downloadBtn').disabled = selected === 0;
}

function renderTracks(data: PreviewData): void {
  const ul = el('tracks');
  ul.replaceChildren();
  for (const t of data.tracks) {
    const li = document.createElement('li');

    const box = document.createElement('input');
    box.type = 'checkbox';
    box.checked = true;
    box.dataset.id = t.spotify_track_id;
    box.setAttribute('aria-label', `${t.artist} - ${t.title}`);
    box.addEventListener('change', updateCount);

    const img = document.createElement('img');
    img.alt = '';
    img.loading = 'lazy';
    if (t.cover_url) img.src = t.cover_url;

    const meta = document.createElement('div');
    meta.className = 'meta';
    const title = document.createElement('div');
    title.className = 'title';
    title.textContent = t.title;
    const artist = document.createElement('div');
    artist.className = 'artist';
    artist.textContent = t.artist;
    meta.append(title, artist);

    const time = document.createElement('span');
    time.className = 'time';
    time.textContent = fmtTime(t.duration);
    const state = document.createElement('span');
    state.className = 'state';

    li.append(box, img, meta, time, state);
    ul.append(li);
  }
  el<HTMLInputElement>('selectAll').checked = true;
  el('listTitle').textContent = data.name || 'Track';
  el('listSection').hidden = false;
  updateCount();
}

async function loadPreview(): Promise<void> {
  const url = el<HTMLInputElement>('url').value.trim();
  if (!url) return showMessage('Paste a Spotify link first.');
  showMessage('');
  el('progressSection').hidden = true;
  el<HTMLButtonElement>('previewBtn').disabled = true;
  el('previewBtn').textContent = 'Loading…';
  const result = await window.api.preview(url);
  el<HTMLButtonElement>('previewBtn').disabled = false;
  el('previewBtn').textContent = 'Load';
  if (result.error !== undefined) {
    el('listSection').hidden = true;
    return showMessage(result.error);
  }
  preview = result;
  renderTracks(result);
}

async function startDownload(): Promise<void> {
  const ids = selectedIds();
  if (!ids.length) return;
  const bitrate = el<HTMLSelectElement>('bitrate').value;
  const enrich = el<HTMLInputElement>('enrich').checked;
  await window.api.saveSettings({ folder, bitrate, enrich });

  // Rows for the selected tracks, in download order (the backend keeps playlist order).
  const all = [...document.querySelectorAll<HTMLLIElement>('#tracks li')];
  rows = all.filter((li) => li.querySelector('input')!.checked);
  for (const li of all) {
    li.className = '';
    li.querySelector('.state')!.textContent = '';
  }

  el('log').textContent = '';
  el('summary').hidden = true;
  el('overallBar').style.width = '0';
  el('trackBar').style.width = '0';
  el('overallText').textContent = 'Starting…';
  el('trackText').textContent = '';
  el('progressSection').hidden = false;
  showMessage('');
  setRunning(true);

  const r = await window.api.startDownload({
    url: el<HTMLInputElement>('url').value.trim(), folder, bitrate, enrich, trackIds: ids,
  });
  if ('error' in r) {
    setRunning(false);
    showMessage(r.error);
  }
}

function setRowState(index: number, cls: string, text: string): void {
  const li = rows[index - 1];
  if (!li) return;
  li.className = cls;
  li.querySelector('.state')!.textContent = text;
  if (cls === 'active') li.scrollIntoView({ block: 'nearest' });
}

function onEvent(ev: BackendEvent): void {
  switch (ev.event) {
    case 'log': {
      const log = el('log');
      log.textContent += `${ev.message}\n`;
      log.scrollTop = log.scrollHeight;
      break;
    }
    case 'start':
      lastFolder = ev.folder;
      el('overallText').textContent = `0 of ${ev.total} done`;
      break;
    case 'track_start':
      setRowState(ev.index, 'active', 'Downloading');
      el('trackBar').style.width = '0';
      el('trackText').textContent = ev.label;
      el('overallText').textContent = `Track ${ev.index} of ${ev.total}`;
      el('overallBar').style.width = `${((ev.index - 1) / ev.total) * 100}%`;
      break;
    case 'progress':
      el('trackBar').style.width = `${ev.percent}%`;
      if (ev.converting) {
        setRowState(rows.findIndex((r) => r.className === 'active') + 1, 'active', 'Converting');
      }
      break;
    case 'track_done':
      setRowState(ev.index, 'done', 'Done');
      el('overallBar').style.width = `${(ev.index / rows.length) * 100}%`;
      break;
    case 'track_error':
      setRowState(ev.index, 'error', 'Failed');
      break;
    case 'done':
      finish(ev);
      break;
  }
}

function finish(summary: DoneEvent): void {
  setRunning(false);
  if (summary.folder) lastFolder = summary.folder;
  el('trackText').textContent = '';
  el('trackBar').style.width = '0';
  if (summary.error) {
    showMessage(summary.error);
    return;
  }
  const total = summary.ok.length + summary.failed.length;
  if (!summary.cancelled) el('overallBar').style.width = '100%';
  el('overallText').textContent = summary.cancelled ? 'Cancelled' : 'Finished';
  el('summaryText').textContent =
    `${summary.ok.length} of ${total} track(s) saved${summary.failed.length ? `, ${summary.failed.length} failed` : ''}.`;
  const failedList = el('failed');
  failedList.replaceChildren();
  for (const f of summary.failed) {
    const li = document.createElement('li');
    li.textContent = `${f.track}: ${f.error}`;
    failedList.append(li);
  }
  el('openBtn').hidden = !lastFolder;
  el('summary').hidden = false;
}

function setFolder(path: string): void {
  folder = path;
  el('folder').textContent = path;
  el('folder').title = path;
}

async function init(): Promise<void> {
  const s = await window.api.getSettings();
  setFolder(s.folder);
  el<HTMLSelectElement>('bitrate').value = s.bitrate;
  el<HTMLInputElement>('enrich').checked = s.enrich;

  el('previewBtn').addEventListener('click', loadPreview);
  el('url').addEventListener('keydown', (e) => {
    if ((e as KeyboardEvent).key === 'Enter' && !running) loadPreview();
  });
  el('selectAll').addEventListener('change', (e) => {
    const checked = (e.target as HTMLInputElement).checked;
    for (const box of trackBoxes()) box.checked = checked;
    updateCount();
  });
  el('folderBtn').addEventListener('click', async () => {
    const picked = await window.api.pickFolder(folder);
    if (picked) setFolder(picked);
  });
  el('downloadBtn').addEventListener('click', startDownload);
  el('cancelBtn').addEventListener('click', () => {
    el<HTMLButtonElement>('cancelBtn').disabled = true;
    el('cancelBtn').textContent = 'Cancelling…';
    window.api.cancelDownload();
  });
  el('openBtn').addEventListener('click', () => window.api.openFolder(lastFolder));
  window.api.onEvent(onEvent);
}

init();
