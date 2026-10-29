import { test, expect, _electron as electron } from '@playwright/test';
import { createRequire } from 'node:module';
import { resolve } from 'node:path';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
const electronRequire = createRequire(resolve('ELECTRON_APP/package.json'));

test('Electron imports a reviewed URDF into its global robot library',async()=>{
 const profile=mkdtempSync(resolve(tmpdir(),'robot-electron-urdf-'));
 const app=await electron.launch({executablePath:electronRequire('electron'),args:[`--user-data-dir=${profile}`,resolve('ELECTRON_APP')],env:{...process.env,ROBOT_IDE_ORIGIN:'http://127.0.0.1:8082',ROBOT_IDE_DEV:'0'}});
 try {
  const page=await app.firstWindow();
  await page.request.post('http://127.0.0.1:8082/login',{form:{code:'hosted-browser-test-code'}});
  await page.goto('http://127.0.0.1:8082/',{waitUntil:'domcontentloaded'});
  const welcome=page.getByRole('dialog',{name:'Hello.'});
  await expect(welcome).toBeVisible();await welcome.getByRole('button',{name:'Continue',exact:true}).click();
  await page.getByRole('button',{name:'Open configuration',exact:true}).click();
  await page.getByRole('button',{name:'Add robot to library',exact:true}).click();
  await page.getByRole('button',{name:'Import URDF',exact:true}).click();
  await page.getByLabel('URDF source file',{exact:true}).setInputFiles(resolve('SERVER_CLIENT/server/examples/robots/bench_gantry.urdf'));
  await page.getByRole('button',{name:'Read URDF',exact:true}).click();
  await expect(page.getByLabel('URDF slide_y min',{exact:true})).toHaveValue('-0.5');
  const robotId=page.getByLabel('URDF robot ID',{exact:true});
  await robotId.click();await robotId.fill('electron_urdf_acceptance');
  await expect(robotId).toHaveValue('electron_urdf_acceptance');
  for(const joint of ['slide_x','slide_y','slide_z']){
    const field=page.getByLabel(`URDF ${joint} acceleration`,{exact:true});
    await field.click();await field.fill('0.8');
    await expect(field.locator('..')).toContainText('User configured');
    await expect(field).toHaveValue('0.8');
  }
  await page.getByRole('button',{name:'Validate robot definition',exact:true}).click();
  await expect(page.getByText('Definition validated · serial-chain IK available',{exact:true})).toBeVisible();
  await page.getByLabel('I reviewed the URDF robot configuration',{exact:true}).check();
  await page.getByRole('button',{name:'Save global robot & continue',exact:true}).click();
  await expect(page.getByRole('heading',{name:'3. Control adapter for Bench gantry',exact:true})).toBeVisible();
  expect((await page.request.get('http://127.0.0.1:8082/api/registry/electron_urdf_acceptance/source')).status()).toBe(200);
  await page.screenshot({path:'artifacts/urdf-import-electron.png'});
 }finally{await app.close();rmSync(profile,{recursive:true,force:true});}
});

test('sandboxed Electron exposes scoped Isaac file selection only to the trusted IDE', async () => {
  const profile=mkdtempSync(resolve(tmpdir(),'robot-electron-qa-'));
  const app = await electron.launch({ executablePath: electronRequire('electron'), args: [`--user-data-dir=${profile}`,resolve('ELECTRON_APP')],
    env: { ...process.env, ROBOT_IDE_ORIGIN: 'http://127.0.0.1:8082', ROBOT_IDE_DEV: '0', ROBOT_IDE_ACCESS_CODE:'native-workspace-test-code' } });
  try {
    const page = await app.firstWindow();
    await page.request.post('http://127.0.0.1:8082/login', {form:{code:'hosted-browser-test-code'}});
    await page.goto('http://127.0.0.1:8082/', {waitUntil:'domcontentloaded'});
    const welcome = page.getByRole('dialog', {name: 'Hello.'});
    await expect(welcome).toBeVisible();
    await page.screenshot({path: 'artifacts/ui-final/electron-welcome.png', animations: 'disabled'});
    await welcome.getByRole('button', {name: 'Continue', exact: true}).click();
    await expect(welcome).toHaveCount(0);
    await expect(page.getByLabel('Select project', { exact: true })).toHaveValue('apple_transfer');
    const preferences = await app.evaluate(({ BrowserWindow }) => {
      const p = BrowserWindow.getAllWindows()[0].webContents.getLastWebPreferences();
      return { sandbox: p.sandbox, contextIsolation: p.contextIsolation, nodeIntegration: p.nodeIntegration };
    });
    expect(preferences).toEqual({ sandbox: true, contextIsolation: true, nodeIntegration: false });
    expect(await page.evaluate(() => typeof (window as any).require)).toBe('undefined');
    expect(await page.evaluate(() => window.robotIdeDesktop?.platform)).toBe(process.platform);
    const access=await app.evaluate(({BrowserWindow})=>BrowserWindow.getAllWindows()[0].webContents.executeJavaScript('typeof window.robotIdeDesktop.workspaceAccessCode'));
    expect(access).toBe('function');
    expect(await page.evaluate(()=>window.robotIdeDesktop!.workspaceAccessCode())).toEqual({access_code:'native-workspace-test-code'});
    const menuCode=await app.evaluate(async({Menu,dialog,clipboard})=>{
      const item=Menu.getApplicationMenu()!.items.find(i=>i.label==='Workspace')!.submenu!.items.find(i=>i.label==='Show workspace access code')!;
      const original=dialog.showMessageBox,write=clipboard.writeText;let detail='',copied='';
      let finish!:()=>void;const copiedCode=new Promise<void>(resolve=>finish=resolve);
      try{dialog.showMessageBox=(async(_window:any,options:any)=>{detail=options.detail;return{response:1,checkboxChecked:false};}) as any;
        clipboard.writeText=(value:string)=>{copied=value;finish();};
        item.click();await copiedCode;return{detail,copied};
      }finally{dialog.showMessageBox=original;clipboard.writeText=write;}
    });
    expect(menuCode.detail).toContain('native-workspace-test-code');expect(menuCode.copied).toBe('native-workspace-test-code');
    await page.route('**/api/workspace/access',route=>route.fulfill({status:405,json:{detail:'Method Not Allowed'}}));
    await page.getByRole('button',{name:'Open configuration',exact:true}).click();
    await page.getByRole('button',{name:'Workspace access',exact:true}).click();
    await page.getByRole('button',{name:'Show workspace access code',exact:true}).click();
    await expect(page.getByLabel('Revealed workspace access code',{exact:true})).toHaveValue('native-workspace-test-code');
    await page.getByRole('button',{name:'Hide access code',exact:true}).click();
    await page.getByRole('button',{name:'Close configuration',exact:true}).click();
    await app.evaluate(({ dialog }) => { dialog.showOpenDialog = async () => ({ canceled: false, filePaths: ['/tmp/approved/catalog.yaml'] }); });
    const result = await page.evaluate(() => window.robotIdeDesktop!.chooseIsaacFile('catalog'));
    expect(result).toBe('/tmp/approved/catalog.yaml');
    const rejected = await page.evaluate(async () => {
      try { await window.robotIdeDesktop!.chooseIsaacFile('execute' as any); return ''; } catch (e) { return (e as Error).message; }
    });
    expect(rejected).toContain('Unknown file selection');
    const denied = await app.evaluate(async ({ BrowserWindow }, preload) => {
      const untrusted = new BrowserWindow({ show: false, webPreferences: { preload, sandbox: true, contextIsolation: true, nodeIntegration: false } });
      try {
        await untrusted.loadURL('data:text/html,<h1>Untrusted page</h1>');
        return await untrusted.webContents.executeJavaScript("window.robotIdeDesktop.chooseIsaacFile('catalog').then(()=> 'unexpected').catch(e=>e.message)");
      } finally { untrusted.destroy(); }
    }, resolve('ELECTRON_APP/electron/preload.cjs'));
    expect(denied).toContain('only available to the IDE window');
    const accessDenied = await app.evaluate(async ({ BrowserWindow }, preload) => {
      const untrusted = new BrowserWindow({ show: false, webPreferences: { preload, sandbox: true, contextIsolation: true, nodeIntegration: false } });
      try {await untrusted.loadURL('data:text/html,<h1>Untrusted</h1>');
        return await untrusted.webContents.executeJavaScript("window.robotIdeDesktop.workspaceAccessCode().then(()=> 'unexpected').catch(e=>e.message)");
      }finally{untrusted.destroy();}
    },resolve('ELECTRON_APP/electron/preload.cjs'));
    expect(accessDenied).toContain('only available to the local IDE window');
    await page.getByRole('button', { name: 'Environment workspace', exact: true }).click();
    await page.getByRole('button', { name: 'Isaac Sim setup', exact: true }).click();
    await page.getByRole('button', { name: 'This computer', exact: false }).click();
    await expect(page.getByRole('button', { name: 'Choose Isaac launcher', exact: true })).toBeVisible();
    if (process.platform === 'darwin') await expect(page.getByRole('button', { name: 'Start local Isaac Sim', exact: true })).toBeDisabled();
  } finally { await app.close();rmSync(profile,{recursive:true,force:true}); }
});

test('Electron runs a saved plan and keeps failed submissions inside the dialog',async()=>{
 const profile=mkdtempSync(resolve(tmpdir(),'robot-electron-qa-'));
 const app=await electron.launch({executablePath:electronRequire('electron'),args:[`--user-data-dir=${profile}`,resolve('ELECTRON_APP')],env:{...process.env,ROBOT_IDE_ORIGIN:'http://127.0.0.1:8082',ROBOT_IDE_DEV:'0'}});
 try {
  const page=await app.firstWindow();const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
  await page.getByLabel('Workspace access code').fill('hosted-browser-test-code');await page.getByRole('button',{name:'Open workspace',exact:true}).click();
  await page.getByRole('button',{name:'New plan',exact:true}).first().click();const dialog=page.getByRole('dialog',{name:'New plan',exact:true});
  await dialog.getByLabel('New plan name').fill('Electron acceptance');await dialog.getByRole('button',{name:'Create plan',exact:true}).click();
  await page.getByRole('button',{name:'Add task',exact:true}).click();await page.getByRole('button',{name:'Save changes',exact:true}).click();
  await page.getByRole('button',{name:'Compile plan',exact:true}).click();await page.getByRole('tab',{name:'Generated code',exact:true}).click();await expect(page.locator('.monaco-editor')).toBeVisible();
  await page.getByRole('button',{name:'Simulate',exact:true}).click();await expect(page.locator('.run-status.success')).toHaveText('simulation passed',{timeout:25000});
  await page.route('**/plan-definitions',async route=>route.request().method()==='POST'?route.fulfill({status:422,json:{detail:'Choose another plan name.'}}):route.continue());
  await page.getByRole('button',{name:'New plan',exact:true}).first().click();await dialog.getByLabel('New plan name').fill('Failed draft');await dialog.getByRole('button',{name:'Create plan',exact:true}).click();
  await expect(dialog.getByRole('alert')).toContainText('Choose another plan name.');
  expect(await dialog.getByRole('alert').evaluate(el=>getComputedStyle(el).position)).toBe('static');
  await page.screenshot({path:'artifacts/qa-20261027/electron-warning.png'});expect(errors).toEqual([]);
 } finally {await app.close();rmSync(profile,{recursive:true,force:true});}
});
