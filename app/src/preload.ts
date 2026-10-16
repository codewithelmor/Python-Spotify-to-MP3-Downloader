import { contextBridge, ipcRenderer, IpcRendererEvent } from 'electron';

const api: Api = {
  getSettings: () => ipcRenderer.invoke('settings:get'),
  saveSettings: (s) => ipcRenderer.invoke('settings:set', s),
  pickFolder: (current) => ipcRenderer.invoke('folder:pick', current),
  openFolder: (folder) => ipcRenderer.invoke('folder:open', folder),
  preview: (url) => ipcRenderer.invoke('preview', url),
  startDownload: (opts) => ipcRenderer.invoke('download:start', opts),
  cancelDownload: () => ipcRenderer.invoke('download:cancel'),
  onEvent: (handler) => {
    const listener = (_e: IpcRendererEvent, ev: BackendEvent) => handler(ev);
    ipcRenderer.on('download:event', listener);
    return () => ipcRenderer.removeListener('download:event', listener);
  },
};

contextBridge.exposeInMainWorld('api', api);
