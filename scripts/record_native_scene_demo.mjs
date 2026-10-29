/** Real NVIDIA worker demo; no injected transport or synthetic frames. */
import {chromium,expect} from '@playwright/test';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {resolve} from 'node:path';
const out=(await readFile('artifacts/native-demo-current.txt','utf8')).trim();
await mkdir(resolve(out,'browser'),{recursive:true});
const base='http://127.0.0.1:19887/api',origin='http://127.0.0.1:19888';
async function call(path,method='GET',body){const r=await fetch(base+path,{method,headers:{'Content-Type':'application/json'},body:body===undefined?undefined:JSON.stringify(body)});const data=await r.json();if(!r.ok)throw Error(JSON.stringify(data));return data;}
const browser=await chromium.launch({headless:true,slowMo:90});
const context=await browser.newContext({viewport:{width:1600,height:1000},recordVideo:{dir:resolve(out,'browser'),size:{width:1600,height:1000}}});
await context.request.post(origin+'/login',{form:{code:'gcp-recording-demo-code'}});
await context.addInitScript(()=>localStorage.setItem('robot-ide.project','gcp_demo'));
const page=await context.newPage();page.setDefaultTimeout(30000);
const chapters=[],errors=[];const began=Date.now();let currentRecord,run;
page.on('pageerror',error=>errors.push(error.message));
const button=(name,scope=page)=>scope.getByRole('button',{name,exact:true});
const pause=ms=>page.waitForTimeout(ms);
async function chapter(title,fn){const item={title,start:(Date.now()-began)/1000};chapters.push(item);console.log(title);try{await fn();await pause(1600);await page.screenshot({path:resolve(out,'browser',`${chapters.length}.png`)});}finally{item.end=(Date.now()-began)/1000;await writeFile(resolve(out,'chapters.json'),JSON.stringify(chapters,null,2));}}
async function fill(label,value,scope=page){const input=scope.getByLabel(label,{exact:true});await input.click();await input.fill(String(value));}
const heartbeat=setInterval(()=>void call('/projects/gcp_demo').catch(()=>{}),3000);
const report={real_native:true,project_id:'gcp_demo',browser_errors:errors};
try{
 await chapter('Connected NVIDIA Isaac Sim scene on GCP',async()=>{
  await page.goto(origin+'/');await expect(page.getByRole('dialog',{name:'Hello.'})).toBeVisible();await button('Continue').click();
  await button('Environment workspace').click();await expect(page.locator('.native-controls')).toBeVisible();
  const detail=await call('/projects/gcp_demo');if(detail.adapter!=='isaac_sim'||detail.worker?.engine!=='isaac_sim'||!detail.worker.physics_available)throw Error('Native worker validation failed');
  report.worker={engine:detail.worker.engine,version:detail.worker.simulator_version,asset_sha256:detail.worker.asset_sha256};
  report.initial_positions=Object.fromEntries(detail.robots.map(r=>[r.instance.instance.id,r.state.positions]));
  await button('Reset camera').click();await pause(2500);
 });
 await chapter('Configure and start the native scene camera',async()=>{
  const panel=page.getByRole('region',{name:'Scene recording',exact:true});
  await panel.getByLabel('Recording resolution').selectOption('1280x720');
  await panel.getByLabel('Recording frame rate').selectOption('10');
  await fill('Recording duration',180,panel);
  await panel.getByText('Camera position and look-at point',{exact:true}).click();
  for(const [key,value] of Object.entries({'Camera X (m)':1.25,'Camera Y (m)':1.9,'Camera Z (m)':1.3,'Look at X (m)':.15,'Look at Y (m)':.7,'Look at Z (m)':.3}))await fill(key,value,panel);
  await button('Start scene recording',panel).click();
  await expect(panel.getByRole('button',{name:'Stop recording',exact:true})).toBeVisible({timeout:180000});
  const records=await call('/projects/gcp_demo/recordings');currentRecord=records.find(r=>r.status==='recording');
  if(!currentRecord)throw Error('Native recording did not start');report.recording_id=currentRecord.id;
  await pause(2500);
 });
 await chapter('Eighteen explicitly assigned tasks, two independent robots',async()=>{
  await button('Plans workspace').click();
  await expect(page.locator('.plan-goal input').first()).toBeVisible().catch(()=>{});
  await button('Compile plan').click();
  await expect(page.getByText('Ready for simulation',{exact:true})).toBeVisible({timeout:60000});
  const definitions=await call('/projects/gcp_demo/plan-definitions');report.definition_id=definitions[0].id;
  const plans=(await call('/projects/gcp_demo')).plans;report.revision_id=plans[0].id;
  await pause(1800);
 });
 await chapter('Execute both robots in the native GPU simulation',async()=>{
  await button('Simulate').click();
  await expect(page.locator('.run-status')).toHaveText(/simulating|simulation passed|verifying/i,{timeout:30000});
  const detail=await call('/projects/gcp_demo');run=detail.active_run;
  if(!run)throw Error('No active native run was observed');report.run_id=run;
  let peak=0;const observations=[];
  for(let i=0;i<160;i++){
   const result=await call('/runs/'+run);report.run_status=result.status;
   if(i%3===0){const d=await call('/projects/gcp_demo');const positions=Object.fromEntries(d.robots.map(r=>[r.instance.instance.id,r.state.positions]));observations.push({elapsed:(Date.now()-began)/1000,positions});for(const q of Object.values(positions))peak=Math.max(peak,Math.abs(q.base_yaw));}
   if(['SIMULATION_PASSED','FAILED','CANCELLED','TIMED_OUT'].includes(result.status)){report.run=result;break;}
   await pause(700);
  }
  report.observations=observations;report.maximum_observed_yaw=peak;
  if(report.run_status!=='SIMULATION_PASSED')throw Error('Native task execution ended with '+report.run_status);
  if(peak<.2)throw Error('Robot motion was not observed in native feedback');
  await expect(page.locator('.run-status')).toHaveText('simulation passed',{timeout:10000});
  await pause(3000);
 });
 await chapter('Stop recording and download the native MP4',async()=>{
  await button('Environment workspace').click();
  const panel=page.getByRole('region',{name:'Scene recording',exact:true});
  await button('Stop recording',panel).click();
  await expect.poll(async()=>{const r=await call('/projects/gcp_demo/recordings/'+currentRecord.id);if(['failed','interrupted'].includes(r.status))throw Error(r.error);return r.cached;},{timeout:60000}).toBe(true);
  report.recording=await call('/projects/gcp_demo/recordings/'+currentRecord.id);
  const row=panel.locator('.recording-item').filter({hasText:new Date(report.recording.created_at).toLocaleString()});
  const download=page.waitForEvent('download');await row.getByRole('button',{name:'MP4',exact:true}).click();
  await (await download).saveAs(resolve(out,'RoboDE-NVIDIA-Isaac-Sim-native.mp4'));
  const detail=await call('/projects/gcp_demo');report.final_positions=Object.fromEntries(detail.robots.map(r=>[r.instance.instance.id,r.state.positions]));
  await button('Reset camera').click();await page.locator('.environment-scene').scrollIntoViewIfNeeded();await pause(2500);
 });
 report.status='passed';
}catch(error){report.status='failed';report.error=error.message;console.error(error);await page.screenshot({path:resolve(out,'failure.png')}).catch(()=>{});}
finally{
 clearInterval(heartbeat);
 if(run){const result=await call('/runs/'+run).catch(()=>null);if(result&&!result.finished_at)await call('/runs/'+run+'/stop','POST',{}).catch(()=>{});}
 const records=await call('/projects/gcp_demo/recordings').catch(()=>[]);
 for(const record of records.filter(r=>r.status==='recording'))await call('/projects/gcp_demo/recordings/'+record.id+'/stop','POST',{}).catch(()=>{});
 await writeFile(resolve(out,'demo-validation.json'),JSON.stringify(report,null,2));
 const video=page.video();await context.close();report.browser_video=await video.path();await writeFile(resolve(out,'demo-validation.json'),JSON.stringify(report,null,2));await browser.close();
}
if(report.status!=='passed')process.exitCode=1;
