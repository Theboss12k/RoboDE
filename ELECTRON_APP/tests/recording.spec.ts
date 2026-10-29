import {test,expect,_electron as electron} from '@playwright/test';
import {createRequire} from 'node:module';
import {resolve} from 'node:path';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
const require=createRequire(resolve('ELECTRON_APP/package.json'));

test('Electron exposes native camera recording with clear offline requirements',async()=>{
  const profile=mkdtempSync(resolve(tmpdir(),'robode-video-ui-'));
  const app=await electron.launch({executablePath:require('electron'),args:[`--user-data-dir=${profile}`,resolve('ELECTRON_APP')],env:{...process.env,ROBOT_IDE_ORIGIN:'http://127.0.0.1:8082',ROBOT_IDE_DEV:'0'}});
  try{
    const page=await app.firstWindow();
    await page.request.post('http://127.0.0.1:8082/login',{form:{code:'hosted-browser-test-code'}});
    await page.goto('http://127.0.0.1:8082/');
    await page.getByRole('dialog',{name:'Hello.'}).getByRole('button',{name:'Continue',exact:true}).click();
    await page.getByRole('button',{name:'Environment workspace',exact:true}).click();
    const panel=page.getByRole('region',{name:'Scene recording',exact:true});
    await expect(panel.getByText(/Connect this project to NVIDIA Isaac Sim/)).toBeVisible();
    await expect(panel.getByRole('button',{name:'Start scene recording',exact:true})).toBeDisabled();
    await expect(panel.getByLabel('Recording resolution')).toHaveValue('1280x720');
    await panel.getByText('Camera position and look-at point',{exact:true}).click();
    const x=panel.getByLabel('Camera X (m)',{exact:true});
    await x.click();await x.fill('3');await expect(x).toHaveValue('3');
    expect(await panel.evaluate(el=>el.scrollWidth<=el.clientWidth+1)).toBeTruthy();
    await panel.screenshot({path:'artifacts/scene-recording-electron.png'});
  }finally{await app.close();rmSync(profile,{recursive:true,force:true});}
});
