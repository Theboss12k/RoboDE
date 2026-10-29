/** Acceptance check against a separately installed, running RoboDE workspace. Never starts a GPU. */
import {chromium,expect} from '@playwright/test';
import fs from 'node:fs/promises';
import path from 'node:path';
const installation=path.resolve(process.argv[2]||'');
if(!process.argv[2])throw Error('Usage: node scripts/verify_installer_ui.mjs INSTALLATION [PORT_OFFSET]');
const offset=Number(process.argv[3]||10000),ide=`http://127.0.0.1:${8081+offset}`,business=`http://127.0.0.1:${8080+offset}`;
const settings=JSON.parse(await fs.readFile(path.join(installation,'installation.json'),'utf8'));
const {access_code:code}=JSON.parse(await fs.readFile(path.join(installation,'access.json'),'utf8'));
const output=path.dirname(installation);
const browser=await chromium.launch();
const report={version:settings.version,simulation:settings.simulation,checks:[],screenshots:[]};
try{
  const context=await browser.newContext({viewport:{width:1440,height:1000},reducedMotion:'reduce'});
  const login=await context.request.post(ide+'/login',{form:{code},maxRedirects:0});expect(login.status()).toBe(303);
  const page=await context.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));
  await page.goto(ide+'/');
  const welcome=page.getByRole('dialog',{name:'Hello.'});
  if(await welcome.isVisible())await welcome.getByRole('button',{name:'Continue',exact:true}).click();
  await expect(page.getByLabel('Select project',{exact:true})).toHaveValue('apple_transfer');
  for(const tab of ['Robots workspace','Environment workspace','Plans workspace'])await page.getByRole('button',{name:tab,exact:true}).click();
  report.checks.push('Installed production IDE login, project selection and three workspaces');
  await page.screenshot({path:path.join(output,'installed-ide.png'),fullPage:true});report.screenshots.push('installed-ide.png');
  async function api(method,url,data){const response=await context.request.fetch(ide+url,{method,data});expect(response.ok(),`${method} ${url}: ${response.status()}`).toBeTruthy();return response.json()}
  const example=JSON.parse(await fs.readFile(path.join(settings.release,'SERVER_CLIENT/server/examples/plans/wave.json'),'utf8'));
  const base='/api/projects/apple_transfer/plan-definitions';
  const created=await api('POST',base,{name:'Installer acceptance · Wave',goal:example.goal});
  const saved=await api('PUT',base+'/'+created.id,{name:created.name,goal:example.goal,version:created.version,tasks:example.tasks});
  const revision=await api('POST',base+'/'+saved.id+'/compile');expect(revision.valid).toBe(true);expect(revision.adapter).toBe('mock');
  let run=await api('POST',`/api/projects/apple_transfer/plans/${revision.id}/simulate`,{fingerprint:revision.fingerprint,adapter:'mock',mode:'simulation'});
  const deadline=Date.now()+45000;
  while(!run.finished_at&&Date.now()<deadline){await new Promise(resolve=>setTimeout(resolve,250));run=await api('GET','/api/runs/'+run.id)}
  expect(run.status).toBe('SIMULATION_PASSED');expect(run.stopped_verified).toBe(true);
  report.checks.push('Installed example compiles and executes through the installed built-in simulator');report.example={run_id:run.id,status:run.status,stopped_verified:run.stopped_verified};
  const mobile=await browser.newContext({viewport:{width:390,height:844},isMobile:true,hasTouch:true,reducedMotion:'reduce'});
  expect((await mobile.request.post(business+'/login',{form:{code},maxRedirects:0})).status()).toBe(303);
  const phone=await mobile.newPage();phone.on('pageerror',e=>errors.push(e.message));await phone.goto(business+'/business/');
  const hello=phone.getByRole('dialog',{name:'Hello.'});if(await hello.isVisible())await hello.getByRole('button',{name:'Continue',exact:true}).click();
  await expect(phone.getByRole('heading',{name:'A clear view. A simple command.'})).toBeVisible();
  await phone.getByRole('button',{name:'Install Business App'}).click();
  await expect(phone.getByRole('dialog',{name:'Install RoboDE Business'})).toBeVisible();
  expect(await phone.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBeTruthy();
  const manifest=await (await mobile.request.get(business+'/business/manifest.webmanifest')).json();expect(manifest.display).toBe('standalone');
  expect((await mobile.request.get(business+'/api/configuration/llm')).status()).toBe(404);
  report.checks.push('Installed Business App login, shared workspace, phone layout, install UI and restricted API');
  await phone.screenshot({path:path.join(output,'installed-business-phone.png'),fullPage:true});report.screenshots.push('installed-business-phone.png');
  expect(errors).toEqual([]);report.status='passed';
  await fs.writeFile(path.join(output,'installed-ui-acceptance.json'),JSON.stringify(report,null,2)+'\n');
  console.log(JSON.stringify(report,null,2));
}finally{await browser.close()}
