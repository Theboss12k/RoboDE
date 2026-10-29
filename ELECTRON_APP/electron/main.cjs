const { app, BrowserWindow, session, shell, ipcMain, dialog, Menu, clipboard } = require('electron');
const path = require('node:path');
// Installed editions keep cookies and Chromium storage with their own workspace.
if (process.env.ROBOT_IDE_ELECTRON_USER_DATA) {
  const profile=process.env.ROBOT_IDE_ELECTRON_USER_DATA;
  if (!path.isAbsolute(profile)) throw new Error('Installed desktop profile must be an absolute path.');
  app.setPath('userData',profile);
}
const dev = process.env.ROBOT_IDE_DEV === '1';
const origin = process.env.ROBOT_IDE_ORIGIN || (dev ? 'http://127.0.0.1:5173' : 'http://127.0.0.1:8765');
app.enableSandbox();
async function workspaceAccessCode(){
  const fs=require('node:fs/promises');
  const filename=process.env.ROBOT_IDE_ACCESS_CODE_FILE || path.resolve(__dirname,'../../SERVER_CLIENT/server/robot_system/runtime/server/access.json');
  const value=process.env.ROBOT_IDE_ACCESS_CODE || await fs.readFile(filename,'utf8').then(text=>JSON.parse(text).access_code).catch(error=>{
    if(error.code==='ENOENT')throw new Error('Start the browser server once to create its workspace access code.');
    throw new Error('The saved workspace access code could not be read.');
  });
  if(typeof value!=='string'||value.length<12)throw new Error('No valid workspace access code is configured.');
  return {access_code:value};
}
app.whenReady().then(() => {
  ipcMain.handle('workspace:access-code', async (event) => {
    if(event.senderFrame!==event.sender.mainFrame || new URL(event.senderFrame.url).origin!==origin || !['127.0.0.1','localhost','[::1]'].includes(new URL(origin).hostname))
      throw new Error('Workspace access is only available to the local IDE window.');
    return workspaceAccessCode();
  });
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    ...(process.platform==='darwin'?[{role:'appMenu'}]:[]),
    {role:'fileMenu'},
    {label:'Workspace',submenu:[{label:'Show workspace access code',click:async()=>{
      const window=BrowserWindow.getFocusedWindow() || BrowserWindow.getAllWindows()[0];
      try{
        const {access_code}=await workspaceAccessCode();
        const result=await dialog.showMessageBox(window,{type:'info',title:'Workspace access code',message:'Workspace access code',detail:access_code+'\n\nUse this code to sign in to the browser IDE. Share only with trusted teammates.',buttons:['Close','Copy code'],defaultId:0,cancelId:0,noLink:true});
        if(result.response===1)clipboard.writeText(access_code);
      }catch(error){await dialog.showMessageBox(window,{type:'error',title:'Workspace access',message:error.message});}
    }}]},
    {role:'editMenu'},{role:'viewMenu'},{role:'windowMenu'},
  ]));
  ipcMain.handle('isaac:choose-file', async (event, kind) => {
    if (event.senderFrame !== event.sender.mainFrame || new URL(event.senderFrame.url).origin !== origin)
      throw new Error('File selection is only available to the IDE window.');
    const options = {
      launcher: { title: 'Choose Isaac Sim Python launcher', filters: [{ name: 'Isaac Python launcher', extensions: ['sh', 'bat', 'exe', '*'] }] },
      catalog: { title: 'Choose approved robot USD catalog', filters: [{ name: 'Asset catalog', extensions: ['yaml', 'yml'] }] },
      manifest: { title: 'Choose fixed Isaac cell manifest', filters: [{ name: 'Cell manifest', extensions: ['yaml', 'yml'] }] },
    };
    if (!Object.hasOwn(options, kind)) throw new Error('Unknown file selection.');
    const result = await dialog.showOpenDialog(BrowserWindow.fromWebContents(event.sender), { ...options[kind], properties: ['openFile'] });
    return result.canceled ? null : result.filePaths[0];
  });
  session.defaultSession.setPermissionRequestHandler((_wc, _permission, callback) => callback(false));
  const open = () => {
    const window = new BrowserWindow({ width: 1512, height: 980, minWidth: 1100, minHeight: 720,
      title: 'RoboDE', backgroundColor: '#101313', titleBarStyle: 'hiddenInset',
      webPreferences: { nodeIntegration: false, contextIsolation: true, sandbox: true,
        preload: path.join(__dirname, 'preload.cjs') } });
    window.webContents.setWindowOpenHandler(({ url }) => {
      // Only explicit links to the bundled Isaac setup references open externally.
      try {
        const parsed = new URL(url);
        const cloudSession=(parsed.protocol==='https:'&&/^[a-z0-9-]+\.trycloudflare\.com$/.test(parsed.hostname)) || (parsed.protocol==='http:'&&parsed.hostname==='127.0.0.1'&&['18083','18084'].includes(parsed.port));
        if (cloudSession || (parsed.protocol === 'https:' && ['docs.isaacsim.omniverse.nvidia.com', 'docs.omniverse.nvidia.com', 'docs.cloud.google.com', 'cloud.google.com', 'console.cloud.google.com'].includes(parsed.hostname)))
          void shell.openExternal(parsed.href).catch(() => {});
      } catch {}
      return { action: 'deny' };
    });
    window.webContents.on('will-navigate', (event, url) => {
      if (new URL(url).origin !== origin) event.preventDefault();
    });
    window.loadURL(origin);
  };
  open();
  app.on('activate', () => { if (BrowserWindow.getAllWindows().length === 0) open(); });
});
app.on('window-all-closed', () => app.quit());
