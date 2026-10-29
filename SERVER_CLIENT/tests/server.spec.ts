import {test,expect} from '@playwright/test';
const code='hosted-browser-test-code';
async function signIn(page:any){await page.goto('/');await page.getByLabel('Workspace access code').fill(code);await page.getByRole('button',{name:'Open workspace',exact:true}).click();await expect(page.getByLabel('Select project',{exact:true})).toHaveValue('apple_transfer');}

test('two authenticated browsers share server-compiled plans and local Monaco assets',async({page,browser})=>{
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 const calls:string[]=[];page.on('request',r=>{if(r.url().includes('/api/'))calls.push(r.url());});
 expect((await page.request.get('/api/projects')).status()).toBe(401);
 await signIn(page);
 const base='/api/projects/apple_transfer/plan-definitions';
 const definition=await (await page.request.post(base,{data:{name:'Browser server plan',goal:'Turn the robot'}})).json();
 const update=await page.request.put(base+'/'+definition.id,{data:{version:definition.version,name:definition.name,goal:definition.goal,tasks:[{id:'turn',name:'Turn',operation:'command',robot_id:'arm_01',dependencies:[],command:{type:'SET_ACTUATOR',target:'base_yaw',value:.2,unit:'rad'}}]}});expect(update.ok()).toBe(true);
 const compiled=await page.request.post(base+'/'+definition.id+'/compile');expect(compiled.status()).toBe(201);const revision=await compiled.json();expect(revision.valid).toBe(true);
 const run=await page.request.post(`/api/projects/apple_transfer/plans/${revision.id}/simulate`,{data:{fingerprint:revision.fingerprint,adapter:'mock',mode:'simulation'}});expect(run.ok()).toBe(true);const started=await run.json();
 await expect.poll(async()=>(await (await page.request.get('/api/runs/'+started.id)).json()).status).toBe('SIMULATION_PASSED');
 await page.reload();await page.getByRole('button',{name:'Plans workspace',exact:true}).click();
 await page.getByRole('tab',{name:'Generated code',exact:true}).click();
 await expect(page.locator('.monaco-editor')).toBeVisible();await expect(page.locator('.code-bar')).toContainText(revision.id);
 const context=await browser.newContext();const other=await context.newPage();await signIn(other);
 await other.getByRole('button',{name:'Plans workspace',exact:true}).click();await expect(other.locator('.plan-name')).toHaveValue('Browser server plan');
 expect(calls.every(url=>new URL(url).origin==='http://127.0.0.1:8082')).toBe(true);
 expect(errors).toEqual([]);await context.close();
});

test('LAN HTTP interface controls work without secure-context randomUUID',async({page})=>{
 await page.addInitScript(()=>{Object.defineProperty(Crypto.prototype,'randomUUID',{value:undefined,configurable:true});});
 const errors:string[]=[];page.on('pageerror',e=>errors.push(e.message));
 await signIn(page);await page.getByRole('button',{name:'Environment workspace',exact:true}).click();
 await page.locator('.scene-robot-picker button').first().click();
 const editor=page.getByRole('region',{name:'Robot virtual controls'});
 await expect(editor.getByText('Connected · simulated feedback',{exact:true})).toBeVisible();
 await editor.getByRole('button',{name:'Revert',exact:true}).click();
 expect(errors).toEqual([]);
});

test('desktop GCP setup saves safely without booting a VM on navigation',async({page})=>{
 let starts=0;
 await page.route('**/api/configuration/isaac/gpu/start',async route=>{starts++;await route.fulfill({status:202,json:{message:'Checking independent shutdown safeguards before boot.'}});});
 await page.route('**/api/configuration/isaac/probe',route=>route.fulfill({json:{engine:'isaac_sim',simulator_version:'6.2.x',scene_loading:true}}));
 await signIn(page);await page.getByRole('button',{name:'Environment workspace',exact:true}).click();
 await page.getByRole('button',{name:'Isaac Sim setup',exact:true}).click();
 await page.getByRole('button',{name:'GCP GPU VM',exact:false}).click();
 await page.getByLabel('GCP project',{exact:true}).fill('my-gpu-project');
 await page.getByLabel('GCP zone',{exact:true}).fill('us-central1-a');
 await page.getByLabel('GCP instance',{exact:true}).fill('robot-gpu');
 await page.getByLabel('Isaac worker token',{exact:true}).fill('isolated-gcp-worker-token');
 await page.getByRole('button',{name:'Save worker connection',exact:true}).click();
 await expect(page.getByRole('button',{name:'Start GPU VM',exact:true})).toBeEnabled();
 expect(starts).toBe(0);
 const saved=await (await page.request.get('/api/configuration/isaac')).json();
 expect(saved.deployment).toBe('gcp');expect(saved.on_demand).toBe(true);expect(saved.token).toBeUndefined();
 await page.getByRole('button',{name:'Test saved connection',exact:true}).click();
 await expect(page.getByText('robot loading available',{exact:false})).toBeVisible();
 await page.getByRole('button',{name:'Start GPU VM',exact:true}).click();
 await expect(page.getByText('Checking independent shutdown safeguards before boot.',{exact:true})).toBeVisible();
 expect(starts).toBe(1);
});

test('desktop local setup uses native file picker, saves catalog and exposes lifecycle controls',async({page})=>{
 await page.addInitScript(()=>{window.robotIdeDesktop={platform:'linux',chooseIsaacFile:async(kind:string)=>kind==='launcher'?'/opt/Isaac Sim/python.sh':'/data/robot assets/catalog.yaml'};});
 await page.route('**/api/configuration/isaac/setup',route=>route.fulfill({json:{platform:'linux',local_supported:true,gcloud_available:false,nvidia_tools_available:true,supported_version:'6.2.x'}}));
 let state={status:'stopped',managed:false,message:'Local Isaac Sim is stopped.'};
 await page.route('**/api/configuration/isaac/local',route=>route.fulfill({json:state}));
 await page.route('**/api/configuration/isaac/local/start',async route=>{state={status:'ready',managed:true,message:'Local Isaac Sim is ready.'};await route.fulfill({status:202,json:state});});
 await page.route('**/api/configuration/isaac/local/stop',async route=>{state={status:'stopped',managed:false,message:'Local Isaac process stopped.'};await route.fulfill({json:state});});
 await page.route('**/api/configuration/isaac/local/log',route=>route.fulfill({json:{text:'Native worker log · token [redacted]'}}));
 await signIn(page);await page.getByRole('button',{name:'Environment workspace',exact:true}).click();await page.getByRole('button',{name:'Isaac Sim setup',exact:true}).click();
 await page.getByRole('button',{name:'This computer',exact:false}).click();
 await page.getByRole('button',{name:'Choose Isaac launcher',exact:true}).click();
 await expect(page.getByLabel('Local Isaac launcher',{exact:true})).toHaveValue('/opt/Isaac Sim/python.sh');
 await expect(page.getByRole('button',{name:'Choose Isaac scene file',exact:true})).toHaveCount(0);
 await page.getByLabel('Local Isaac scene source',{exact:true}).selectOption('catalog');
 await page.getByRole('button',{name:'Choose Isaac scene file',exact:true}).click();
 await expect(page.getByLabel('Local Isaac scene file',{exact:true})).toHaveValue('/data/robot assets/catalog.yaml');
 await page.getByRole('button',{name:'Generate worker token',exact:true}).click();
 await expect(page.getByRole('button',{name:'Start local Isaac Sim',exact:true})).toBeDisabled();
 await page.getByRole('button',{name:'Save worker connection',exact:true}).click();
 await expect(page.getByLabel('Isaac worker token',{exact:true})).toHaveValue('');
 const saved=await (await page.request.get('/api/configuration/isaac')).json();expect(saved.on_demand).toBe(false);expect(saved.load_scene).toBe(true);expect(saved.deployment).toBe('local');
 await page.getByRole('button',{name:'Start local Isaac Sim',exact:true}).click();
 await expect(page.getByRole('button',{name:'Stop local Isaac Sim',exact:true})).toBeEnabled();
 await expect(page.getByLabel('Local Isaac launcher',{exact:true})).toBeDisabled();
 await page.getByRole('button',{name:'View simulator log',exact:true}).click();await expect(page.locator('.isaac-log')).toContainText('[redacted]');
 await page.getByRole('button',{name:'Stop local Isaac Sim',exact:true}).click();
 await expect(page.getByRole('button',{name:'Start local Isaac Sim',exact:true})).toBeEnabled();
});

test('macOS setup explains local limitation and retains the GCP choice',async({page})=>{
 await page.route('**/api/configuration/isaac/setup',route=>route.fulfill({json:{platform:'darwin',local_supported:false,gcloud_available:true,nvidia_tools_available:false,supported_version:'6.2.x'}}));
 await signIn(page);await page.getByRole('button',{name:'Environment workspace',exact:true}).click();await page.getByRole('button',{name:'Isaac Sim setup',exact:true}).click();
 await page.getByRole('button',{name:'This computer',exact:false}).click();
 await expect(page.getByText('Isaac Sim cannot run natively on macOS.',{exact:false})).toBeVisible();
 await expect(page.getByRole('button',{name:'Start local Isaac Sim',exact:true})).toBeDisabled();
 await page.getByRole('button',{name:'GCP GPU VM',exact:false}).click();await expect(page.getByLabel('GCP project',{exact:true})).toBeVisible();
});
