const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('robotIdeDesktop', Object.freeze({
  platform: process.platform,
  chooseIsaacFile: (kind) => ipcRenderer.invoke('isaac:choose-file', kind),
  workspaceAccessCode: () => ipcRenderer.invoke('workspace:access-code'),
}));
