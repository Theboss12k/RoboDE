/** Opt-in browser/native functional checks against scripts.ollama_functional_server. */
import {chromium, _electron as electron, expect} from '@playwright/test';
import {createRequire} from 'node:module';
import {resolve} from 'node:path';
import {mkdtempSync, readFileSync, writeFileSync, rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
const folder=resolve('artifacts/ollama-20261029');
const runtime=JSON.parse(readFileSync(resolve(folder,'runtime.json'),'utf8'));
const skipAdapters=process.env.OLLAMA_QA_SKIP_ADAPTERS==='1';
const results=skipAdapters?JSON.parse(readFileSync(resolve(folder,'ui-results.json'),'utf8')).results.filter(r=>r.name.includes('SDK adapter')):[];
const goal='Rotate the base to 0.2 radians, then open the gripper to 60 percent. Keep all other joints unchanged.';
const docs=`Bench SDK 1.0 is a fictional QA SDK, not a real hardware integration.
import bench_sdk; client = bench_sdk.Client(host).
client.move_base(angle): set only base_yaw to angle radians, range -3.14 to 3.14.
client.set_gripper(opening): set only gripper to opening metres, range 0.0 to 0.08.
client.get_joint_positions(): return a dictionary with base_yaw, shoulder, elbow, wrist in radians and gripper in metres.
client.stop(): request all motors to stop.
client.close(): disconnect the client without moving any motors.
The SDK does not document a general joint-position writer or camera. Missing functionality must remain unimplemented.`;
function save(){writeFileSync(resolve(folder,'ui-results.json'),JSON.stringify({model:runtime.model,results},null,2));}
async function step(name,fn){
 console.log(name+': START');
 const start=Date.now();
 try {const detail=await fn();results.push({name,passed:true,duration_seconds:(Date.now()-start)/1000,...detail});console.log(name+': PASS');}
 catch(error){results.push({name,passed:false,duration_seconds:(Date.now()-start)/1000,error:String(error)});console.log(name+': FAIL '+String(error).slice(0,1400));}
 save();
}
async function open(page,pid,origin,business=false){
 await page.request.post(origin+'/login',{form:{code:runtime.code}});
 await page.addInitScript(({pid,business})=>localStorage.setItem(business?'business.project':'robot-ide.project',pid),{pid,business});
 await page.goto(origin+(business?'/business/':'/'),{waitUntil:'domcontentloaded'});
 const welcome=page.getByRole('dialog',{name:'Hello.'});
 if(await welcome.isVisible())await welcome.getByRole('button',{name:'Continue',exact:true}).click();
 await expect(welcome).toHaveCount(0);
 await expect(page.getByLabel(business?'Choose workspace':'Select project',{exact:true})).toHaveValue(pid);
}
async function adapter(page,pid){
 let bundle;
 await page.getByRole('button',{name:'Open configuration',exact:true}).click();
 await page.getByRole('button',{name:'Configure adapters & test',exact:true}).first().click();
 await page.getByRole('button',{name:'Create adapter from documentation / custom commands',exact:true}).click();
 await page.getByRole('button',{name:/Physical robot/}).click();
 await page.getByRole('button',{name:'Continue',exact:true}).click();
 await page.getByRole('button',{name:/Use vendor documentation/}).click();
 await page.getByRole('button',{name:'Continue',exact:true}).click();
 await page.getByLabel('Adapter name',{exact:true}).fill('Phi-4 '+pid+' SDK');
 await page.getByLabel('SDK version',{exact:true}).fill('1.0');
 await page.getByLabel('Documentation LLM adapter',{exact:true}).selectOption(runtime.provider_id);
 await page.getByLabel('SDK documentation',{exact:true}).fill(docs);
 const discovery=page.waitForResponse(r=>r.url().endsWith('/discover-commands'),{timeout:310000});
 await page.getByRole('button',{name:'Extract commands from documentation',exact:true}).click();
 const response=await discovery;expect(response.ok(),await response.text()).toBe(true);
 await expect(page.locator('.command-definition').first()).toBeVisible();
 await page.getByRole('button',{name:'Continue',exact:true}).click();
 const generated=page.waitForResponse(r=>r.url().endsWith('/adapters/generate'),{timeout:310000});
 await page.getByRole('button',{name:'Generate draft',exact:true}).click();
 const draft=await generated;expect(draft.ok(),await draft.text()).toBe(true);bundle=await draft.json();
 expect(bundle.provenance.llm_adapter.model).toBe('phi4:14b');
 expect(bundle.sdk_source.length).toBeGreaterThan(40);expect(bundle.live_eligible).toBe(false);
 await page.getByLabel('I reviewed the generated adapter',{exact:true}).check();
 await page.getByRole('button',{name:'Record review & open simulator',exact:true}).click();
 await expect(page.getByText('Simulated contract tests passed',{exact:true})).toBeVisible({timeout:20000});
 const command=bundle.commands.find(c=>c.vendor_command.includes('move_base')&&c.simulation_supported);
 expect(command,'Expected a supported documentation-derived move_base task').toBeTruthy();
 await page.locator('.command-catalog').getByRole('button').filter({hasText:command.name}).click();
 for(const key of Object.keys(command.parameters))await page.getByLabel('Test parameter '+key,{exact:true}).fill('.12');
 await page.getByRole('button',{name:'Test '+command.name,exact:true}).click();
 await expect(page.locator('.command-result')).toContainText(command.id+' · passed',{timeout:15000});
 await expect(page.getByLabel('Feedback base_yaw',{exact:true})).toContainText('0.12');
 await page.screenshot({path:resolve(folder,pid+'-adapter.png')});
 await page.getByRole('button',{name:'Disconnect controls',exact:true}).click();
 await page.getByRole('button',{name:'Done',exact:true}).click();
 await page.getByRole('button',{name:'Close configuration',exact:true}).click();
 return {adapter_id:bundle.id,provenance:bundle.provenance,commands:bundle.commands.map(c=>({id:c.id,supported:c.simulation_supported})),hardware_contact:false};
}
async function planning(page,pid){
 await page.getByRole('button',{name:'Plans workspace',exact:true}).click();
 await page.getByRole('button',{name:'New plan',exact:true}).first().click();
 await page.getByLabel('New plan name',{exact:true}).fill('Phi-4 '+pid+' commands');
 await page.getByRole('button',{name:'Create plan',exact:true}).click();
 await page.getByLabel('Plan goal',{exact:true}).fill(goal);
 await page.getByLabel('Goal LLM adapter',{exact:true}).selectOption(runtime.provider_id);
 const drafted=page.waitForResponse(r=>r.url().endsWith('/draft'),{timeout:310000});
 await page.getByRole('button',{name:'Generate tasks',exact:true}).click();
 const response=await drafted;expect(response.ok(),await response.text()).toBe(true);const definition=await response.json();
 expect(definition.tasks.length).toBeGreaterThanOrEqual(2);
 expect(definition.tasks.every(t=>t.robot_id==='arm_01'&&t.llm_adapter_id===runtime.provider_id)).toBe(true);
 const compiled=page.waitForResponse(r=>r.url().endsWith('/compile'));
 await page.getByRole('button',{name:'Compile plan',exact:true}).click();
 const revision=await (await compiled).json();expect(revision.valid,JSON.stringify(revision.checks)).toBe(true);
 const running=page.waitForResponse(r=>r.url().endsWith('/simulate'));
 await page.getByRole('button',{name:'Simulate',exact:true}).click();const run=await (await running).json();
 await expect(page.locator('.run-status.success')).toHaveText('simulation passed',{timeout:25000});
 const finished=await (await page.request.get('http://127.0.0.1:18877/api/runs/'+run.id)).json();
 expect(finished.robot_states.arm_01.positions.base_yaw).toBeCloseTo(.2,5);
 expect(finished.robot_states.arm_01.positions.gripper).toBeCloseTo(.048,5);
 await page.screenshot({path:resolve(folder,pid+'-plan.png')});
 return {definition_id:definition.id,tasks:definition.tasks,revision_id:revision.id,run_id:run.id,status:finished.status,final_positions:finished.robot_states.arm_01.positions};
}
const browser=await chromium.launch();
let app;let profile;
try{
 const page=await browser.newPage({viewport:{width:1512,height:982}});
 page.setDefaultTimeout(15000);await open(page,'browser','http://127.0.0.1:18878');
 if(!skipAdapters)await step('browser: Phi-4 SDK adapter generation, review and simulated command',()=>adapter(page,'browser'));
 // Start each independent flow with clean UI state, preserving fixture evidence.
 await page.reload({waitUntil:'domcontentloaded'});await expect(page.getByRole('dialog',{name:'Hello.'})).toHaveCount(0);
 await step('browser: Phi-4 goal decomposition, compile and execution',()=>planning(page,'browser'));
 await page.close();
 profile=mkdtempSync(resolve(tmpdir(),'robot-ollama-electron-'));
 const require=createRequire(resolve('ELECTRON_APP/package.json'));
 app=await electron.launch({executablePath:require('electron'),args:[`--user-data-dir=${profile}`,resolve('ELECTRON_APP')],env:{...process.env,ROBOT_IDE_ORIGIN:'http://127.0.0.1:18878',ROBOT_IDE_DEV:'0'}});
 const desktop=await app.firstWindow();desktop.setDefaultTimeout(15000);await open(desktop,'electron','http://127.0.0.1:18878');
 if(!skipAdapters)await step('electron: Phi-4 SDK adapter generation, review and simulated command',()=>adapter(desktop,'electron'));
 await desktop.reload({waitUntil:'domcontentloaded'});await expect(desktop.getByRole('dialog',{name:'Hello.'})).toHaveCount(0);
 await step('electron: Phi-4 goal decomposition, compile and execution',()=>planning(desktop,'electron'));
 await app.close();app=null;
 const business=await browser.newPage({viewport:{width:390,height:844},isMobile:true,hasTouch:true});
 await open(business,'business','http://127.0.0.1:18879',true);
 await step('business: Phi-4 natural language review and shared-engine execution',async()=>{
  await business.getByLabel('Your command',{exact:true}).fill(goal);
  const prepared=business.waitForResponse(r=>r.url().endsWith('/commands')&&r.request().method()==='POST',{timeout:310000});
  await business.getByRole('button',{name:'Review command',exact:true}).click();
  const response=await prepared;expect(response.ok(),await response.text()).toBe(true);const job=await response.json();
  await business.getByRole('button',{name:'Start simulation',exact:true}).click();
  await expect(business.getByLabel('Command review').getByRole('heading',{name:'Completed',exact:true})).toBeVisible({timeout:25000});
  const progress=await (await business.request.get(`http://127.0.0.1:18879/api/business/projects/business/commands/${job.id}/run`)).json();
  expect(progress.robot_states.arm_01.positions.base_yaw).toBeCloseTo(.2,5);
  expect(progress.robot_states.arm_01.positions.gripper).toBeCloseTo(.048,5);
  await business.screenshot({path:resolve(folder,'business-plan.png'),fullPage:true});
  return {command_id:job.id,status:progress.status,final_positions:progress.robot_states.arm_01.positions,adapter_authoring:'IDE only by design'};
 });
}finally{if(app)await app.close();await browser.close();if(profile)rmSync(profile,{recursive:true,force:true});}
process.exitCode=results.some(r=>!r.passed)?1:0;
