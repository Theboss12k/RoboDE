/** Genuine browser footage against a disposable workspace and the real GCP worker. */
import{chromium,expect}from'@playwright/test';
import{mkdir,writeFile}from'node:fs/promises';
import{resolve}from'node:path';
const out=resolve('artifacts/walkthroughs/gcp');await mkdir(out,{recursive:true});
const api='http://127.0.0.1:19887/api',url='http://127.0.0.1:19888';
async function call(path,method='GET',data){const r=await fetch(api+path,{method,headers:{'Content-Type':'application/json'},body:data===undefined?undefined:JSON.stringify(data)});const body=await r.json();if(!r.ok)throw Error(path+': '+JSON.stringify(body));return body;}
const browser=await chromium.launch({headless:true,slowMo:130});
const context=await browser.newContext({viewport:{width:1600,height:900},recordVideo:{dir:out,size:{width:1600,height:900}}});
await context.request.post(url+'/login',{form:{code:'gcp-recording-demo-code'},maxRedirects:0});
const started=Date.now(),page=await context.newPage(),chapters=[],errors=[];let failure=null;
page.setDefaultTimeout(20000);page.on('pageerror',e=>errors.push(e.message));
const button=(name,scope=page)=>scope.getByRole('button',{name,exact:true});
const label=(name,scope=page)=>scope.getByLabel(name,{exact:true});
const pause=(ms=1200)=>page.waitForTimeout(ms);
async function click(name,scope=page){await button(name,scope).click();await pause(600);}
async function fill(name,value,scope=page){const el=label(name,scope);await el.click();await el.fill(String(value));await pause(350);}
async function chapter(title,narration,fn){const entry={title,narration,start:(Date.now()-started)/1000};chapters.push(entry);console.log(title);
 try{await fn();await pause(2200);await page.screenshot({path:resolve(out,String(chapters.length).padStart(2,'0')+'.png')});entry.end=(Date.now()-started)/1000;}
 catch(e){entry.error=e.message;entry.end=(Date.now()-started)/1000;throw e;}
 finally{await writeFile(resolve(out,'chapters.json'),JSON.stringify(chapters,null,2));}}
async function setup(){await click('Environment workspace');await click('Isaac Sim setup');}
const evidence={project_id:'gcp_demo',real_gcp:true,browser_errors:errors};
const configured=await call('/configuration/isaac');
evidence.gcp={project:configured.gcp_project,zone:configured.gcp_zone,instance:configured.gcp_instance};
try{
 await chapter('RoboDE with NVIDIA Isaac Sim on GCP','This walkthrough connects RoboDE to an actual NVIDIA L4 virtual machine in Google Cloud. The browser IDE runs locally, while Isaac Sim physics runs on the remote GPU. We use a disposable two-robot project. The three-dimensional view shows observed worker state; it is not a stream of the native Isaac editor.',async()=>{
  await page.goto(url+'/');await pause(2900);await label('Select project').selectOption('gcp_demo');await click('Environment workspace');await pause(1800);
  await page.evaluate(()=>{const el=document.createElement('div');el.style.cssText='position:fixed;width:18px;height:18px;border:2px solid #b4d5ff;border-radius:50%;pointer-events:none;z-index:999999;left:-50px;top:-50px;box-shadow:0 0 0 3px #080b1080';document.body.append(el);document.addEventListener('mousemove',e=>{el.style.left=(e.clientX-9)+'px';el.style.top=(e.clientY-9)+'px';});});
 });
 await chapter('Configured GCP connection and credit safeguards',`The saved target is GCP GPU VM: project ${configured.gcp_project}, zone ${configured.gcp_zone}, and instance ${configured.gcp_instance}. On-demand startup is enabled. An independent ten-minute idle watchdog and a two-hour provider STOP limit protect credits. Worker credentials remain hidden. Opening these settings does not start a VM or create cloud resources.`,async()=>{
  await click('Isaac Sim setup');await label('GCP project').scrollIntoViewIfNeeded();await pause(1800);
  await expect(label('GCP project')).toHaveValue('nvdiavm');await expect(label('On-demand GPU')).toBeChecked();
  await expect(label('Idle shutdown minutes')).toHaveValue('10');await expect(label('Maximum GPU session minutes')).toHaveValue('120');
  await label('Idle shutdown minutes').scrollIntoViewIfNeeded();await pause(1700);
 });
 await chapter('Start the GPU only when needed','Start GPU VM wakes the configured machine, verifies its provider runtime cap, opens the authenticated SSH tunnel, and waits for Isaac and the independent shutdown guard. This is a real cloud start. The boot wait is shortened in the edited video; a capacity error would be shown rather than replaced with simulated success.',async()=>{
  await click('Start GPU VM');await expect(page.locator('.isaac-connection')).toContainText(/Starting GPU|Checking GPU|Waiting for GPU/);await pause(4500);
 });
 // Skip the uninteresting boot wait between chapters, preserving genuine UI footage.
 let gpu;const deadline=Date.now()+390000;
 while(Date.now()<deadline){gpu=await call('/configuration/isaac/gpu');if(gpu.status==='ready')break;if(gpu.status==='error')throw Error(gpu.message);console.log('GPU boot: '+gpu.status);await pause(5000);}
 if(gpu?.status!=='ready')throw Error('The GPU did not become ready before the recording deadline.');
 await chapter('Verify the live NVIDIA worker','The VM is ready. Test saved connection checks the authenticated native Isaac Sim worker. The connection is protected through SSH rather than an exposed worker port. We verify the reported engine, simulator version, physics availability, and the active idle watchdog before moving a robot.',async()=>{
  await click('Test saved connection');await expect(page.locator('.isaac-connection')).toContainText('Connected to isaac_sim');
  const health=await call('/configuration/isaac/probe','POST',{});if(health.engine!=='isaac_sim'||!health.physics_available||!health.idle_guard_active)throw Error('Native worker verification failed');
  evidence.worker={engine:health.engine,version:health.simulator_version,physics_available:health.physics_available,idle_guard_active:health.idle_guard_active};
  await label('Isaac worker URL').scrollIntoViewIfNeeded();await pause(1800);
 });
 await chapter('Automatically transfer the project into Isaac Sim','Choose NVIDIA Isaac Sim as the simulation backend. RoboDE transfers this project’s two robots, their placements and stopped joint positions, plus the named scene objects. No manual rebuilding is needed for these registered educational robot models. Manufacturer robots require approved USD geometry and matching joint mappings.',async()=>{
  await label('Simulation backend').selectOption('isaac_sim');
  await expect(page.locator('.native-controls')).toBeVisible({timeout:90000});
  const detail=await call('/projects/gcp_demo');if(detail.adapter!=='isaac_sim'||!detail.worker?.physics_available)throw Error('Project is not using native Isaac physics');
  evidence.transferred_robots=detail.robots.length;evidence.transferred_objects=detail.objects.length;
  await page.locator('.isaac-connection').evaluate(el=>el.open=false);
  await label('Simulation backend').scrollIntoViewIfNeeded();await pause(2000);await click('Reset camera');
 });
 await chapter('Control a robot with observed GPU feedback','Open native controls for the first robot and connect to the project simulator. These joint targets reach the articulation in Isaac Sim, not an injected test transport. Adjust base yaw, watch the robot and feedback update, then request Stop. A stop request and confirmed stopped feedback are separate states.',async()=>{
  const native=page.locator('.native-controls');await native.getByRole('button',{name:/^Control /}).first().click();const controls=native.locator('.adapter-controls');
  await click('Connect controls',controls);await expect(controls.locator('.control-source')).toContainText('Isaac Sim physics worker');
  await fill('Control base_yaw','.25',controls);
  await expect.poll(async()=>Math.abs(Number((await label('Feedback base_yaw',controls).innerText()).split(' ')[0])-.25),{timeout:30000}).toBeLessThan(.04);
  const moved=await call('/projects/gcp_demo');evidence.observed_yaw=moved.robots[0].state.positions.base_yaw;
  await page.locator('.environment-scene').scrollIntoViewIfNeeded();await pause(4000);await click('Stop',controls);await pause(1800);
  await click('Disconnect controls',controls);await click('Close native controls');
 });
 await chapter('Add and remove objects in the cloud scene','The same Environment tools edit the remote scene. We add a named obstacle, place it away from the robot arms, and save the scene. Isaac’s observed inventory confirms it exists. Removing the object and saving again updates the native scene, while the two robot instances and original assets are retained.',async()=>{
  await click('obstacle');const name=page.locator('.world-editor .object-form').last().locator('input[aria-label^="Object name "]');await name.click();await name.fill('Cloud crate');await pause(400);await fill('Cloud crate x','1.2');await fill('Cloud crate y','0');await fill('Cloud crate z','.15');
  await click('Save scene');await expect(page.locator('.environment-scene')).toHaveAttribute('data-scene-saved','true');
  const added=await call('/projects/gcp_demo');const crate=added.objects.find(o=>o.name==='Cloud crate');if(!crate)throw Error('Cloud crate missing');
  evidence.object_added=crate.id;await pause(2500);await click('Remove Cloud crate');await click('Save scene');
  await expect(page.locator('.environment-scene')).toHaveAttribute('data-scene-saved','true');
  if((await call('/projects/gcp_demo')).objects.some(o=>o.id===crate.id))throw Error('Cloud object removal failed');evidence.object_removed=true;
 });
 await chapter('Compile and execute a two-robot plan','Plans keep robot assignments explicit. These two independent Move home goals are expanded into atomic tasks, compiled into an immutable revision, and simulated on the connected Isaac worker. The scheduler can execute independent robots concurrently. Generated Python and run history remain available for review.',async()=>{
  await click('Plans workspace');await page.getByRole('button',{name:'New plan',exact:true}).first().click();await fill('New plan name','NVIDIA GCP · two-robot home');await click('Create plan');
  await click('Generate tasks');await expect(page.locator('.atomic-task')).toHaveCount(4,{timeout:30000});await click('Compile plan');
  await expect(page.getByText('Ready for simulation',{exact:true})).toBeVisible({timeout:45000});
  await page.getByRole('tab',{name:'Generated code',exact:true}).click();await expect(page.locator('.monaco-editor')).toBeVisible();await pause(2000);
  await click('Simulate');await expect(page.locator('.run-status')).toHaveText('simulation passed',{timeout:120000});
  const detail=await call('/projects/gcp_demo');evidence.completed_run=detail.runs[0]?.id;evidence.plan_simulation_passed=true;
  await page.getByRole('tab',{name:'Run history',exact:true}).click();await pause(1800);
 });
 await chapter('Return to built-in and shut down the GPU','Switching back carries observed stopped state into the built-in simulator. Then Stop GPU VM ends compute usage for this session. The idle guard and provider limit remain configured for future starts. Retained storage can still incur charges. The recording finishes only after the configured GPU VM reports stopped.',async()=>{
  await click('Environment workspace');await label('Simulation backend').selectOption('mock');await expect(label('Simulation backend')).toHaveValue('mock');
  await expect(page.locator('.native-controls')).toHaveCount(0);await click('Isaac Sim setup');await click('Stop GPU VM');
  await expect(page.locator('.isaac-connection')).toContainText('GPU VM stopped',{timeout:90000});evidence.returned_to_builtin=true;evidence.vm_stopped=true;
 });
 evidence.status='passed';
}catch(e){failure=e;console.error(e.message);await page.screenshot({path:resolve(out,'failure.png')}).catch(()=>{});evidence.status='failed';evidence.error=e.message;}
finally{
 try{
  const detail=await call('/projects/gcp_demo');if(detail.active_run)await call('/runs/'+detail.active_run+'/stop','POST',{});
  await call('/projects/gcp_demo/disconnect','POST',{}).catch(()=>{});
  const gpu=await call('/configuration/isaac/gpu');if(!['terminated','unconfigured'].includes(gpu.status))await call('/configuration/isaac/gpu/stop','POST',{});
 }catch(e){evidence.cleanup_error=e.message;console.error('Verify VM shutdown: '+e.message);}
 const video=page.video();await context.close();await browser.close();
 await writeFile(resolve(out,'recording-1.json'),JSON.stringify({path:await video.path(),mode:'gcp',errors,chapters:chapters.filter(c=>!c.error)},null,2));
 await writeFile(resolve(out,'validation.json'),JSON.stringify(evidence,null,2));
}
if(failure)process.exitCode=1;
