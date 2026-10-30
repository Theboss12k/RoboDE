/** Real model comparison through Electron, standard React IDE and Business UI.
 * Requires scripts/local_model_evaluation_server.py; uses disposable data only.
 * Run: node scripts/evaluate_local_llms.mjs --models MODEL MODEL ...
 */
import {chromium,_electron as electron,request,expect} from '@playwright/test';
import {createRequire} from 'node:module';
import {readFileSync,writeFileSync,mkdirSync,mkdtempSync,rmSync,existsSync} from 'node:fs';
import {resolve} from 'node:path';
import {tmpdir} from 'node:os';
import {spawnSync} from 'node:child_process';
const output=resolve(process.env.ROBO_EVALUATION_OUTPUT||'artifacts/nemotron-local-20261030');mkdirSync(output,{recursive:true});
const ix=process.argv.indexOf('--models'),models=ix<0?['nemotron-mini:4b','nemotron-3-nano:4b-q4_K_M','phi4:14b']:process.argv.slice(ix+1).filter(x=>!x.startsWith('--'));
const api=await request.newContext({baseURL:'http://127.0.0.1:8085',timeout:620000});
await api.post('/login',{form:{code:'local-model-evaluation-code'}});
const report={started_at:new Date().toISOString(),scope:'Real local inference; built-in robot simulation; disposable standard-edition projects',
 settings:{temperature:0,max_tokens:4096,timeout_seconds:300,mini_context:4096,other_context:16384,automatic_schema_repairs:1},models:[],cases:[],hosted_nebius:{status:'not_run',reason:'No API key configured'},hardware_contacted:false,cloud_vm_started:false};
if(process.argv.includes('--append')&&existsSync(resolve(output,'results.json'))){Object.assign(report,JSON.parse(readFileSync(resolve(output,'results.json'),'utf8')));delete report.finished_at;}
const save=()=>writeFileSync(resolve(output,'results.json'),JSON.stringify(report,null,2)+'\n');
const pause=ms=>new Promise(r=>setTimeout(r,ms));
async function call(method,path,data){const r=await api.fetch(path,{method,...(data!==undefined?{data}:{})});const b=await r.json();if(!r.ok())throw Error(`HTTP ${r.status()}: ${typeof b.detail==='string'?b.detail:JSON.stringify(b).slice(0,600)}`);return b;}
async function ready(page){
 await page.goto('http://127.0.0.1:8085/');
 const hello=page.getByRole('dialog',{name:'Hello.',exact:true});
 await expect(hello).toBeVisible();await hello.getByRole('button',{name:'Continue',exact:true}).click();await expect(hello).toHaveCount(0);
 await expect(page.getByRole('button',{name:'Plans workspace',exact:true})).toBeVisible();
}
const instructions={
 desktop:'Using ARM ONE only, set base_yaw to 0.04 rad. Keep shoulder, elbow, wrist, gripper and ARM TWO unchanged.',
 web:'On ARM ONE open parallel_gripper to 50 percent, then set base_yaw to -0.03 rad. ARM TWO must not move. Keep all other joints unchanged.',
 business:'Rotate ARM ONE base_yaw to 0.02 rad and ARM TWO base_yaw to -0.02 rad independently. Keep all other actuators unchanged.',
 ambiguous:'Keep ARM TWO waving while ARM ONE waits.',
 impossible:'Make the apple float unaided one metre above the table indefinitely. Do not hold, throw or attach it to a robot.',
 pose:'Move ARM ONE parallel_gripper to world position x=0.30 m, y=-0.10 m, z=0.30 m. Keep its gripper opening unchanged and do not specify orientation. ARM TWO must remain unchanged.'};
const initial={base_yaw:0,shoulder:1,elbow:-1.8,wrist:.8,gripper:.08};
function verifyStates(states,changes){
 for(const id of ['arm_01','arm_02'])for(const [joint,value]of Object.entries({...initial,...(changes[id]??{})})){
  const found=states[id]?.positions?.[joint]??states[id]?.[joint];
  if(typeof found!=='number'||Math.abs(found-value)>1e-6)throw Error(`${id}.${joint}: expected ${value}, got ${found}`);
 }
}
async function finalRun(id){for(let n=0;n<200;n++){const r=await call('GET','/api/runs/'+id);if(r.finished_at)return r;await pause(100)}throw Error('Simulation did not finish within 20 seconds');}
async function executeRevision(pid,definition,result,changes,page){
 if(definition.planning_status!=='tasks_ready'&&definition.planning_status!=='commands_ready')throw Error('Planner status: '+definition.planning_status);
 if(!definition.tasks.length||definition.tasks.some(t=>t.binding_status!=='resolved'))throw Error('Unresolved tasks: '+definition.tasks.map(t=>t.binding_error).filter(Boolean).join('; '));
 result.tasks=definition.tasks;result.inference_evidence=definition.inference_evidence;
 let revision;
 if(page){const wait=page.waitForResponse(r=>r.url().endsWith(`/plan-definitions/${definition.id}/compile`)&&r.request().method()==='POST',{timeout:60000});await page.getByRole('button',{name:'Validate plan',exact:true}).click();const response=await wait;revision=await response.json();if(!response.ok())throw Error(JSON.stringify(revision));}
 else revision=await call('POST',`/api/projects/${pid}/plan-definitions/${definition.id}/compile`);
 result.validation={valid:revision.valid,report:revision.validation_report,checks:revision.checks};result.manifest=revision.motion_manifest;
 if(!revision.valid)throw Error('Compiled motion was rejected');
 if(changes)verifyStates(revision.frames.at(-1).robot_positions,changes);
 let run;
 if(page){const waiting=page.waitForResponse(r=>r.url().endsWith(`/plans/${revision.id}/simulate`)&&r.request().method()==='POST',{timeout:20000});await page.getByRole('button',{name:'Run simulation',exact:true}).click();run=await(await waiting).json();}
 else run=await call('POST',`/api/projects/${pid}/plans/${revision.id}/simulate`,{fingerprint:revision.fingerprint,adapter:'mock'});
 const finished=await finalRun(run.id);result.execution={status:finished.status,stopped_verified:finished.stopped_verified,states:finished.robot_states};
 if(finished.status!=='SIMULATION_PASSED'||!finished.stopped_verified)throw Error('Simulation did not pass with confirmed stopped feedback');
 if(changes)verifyStates(finished.robot_states,changes);
 return finished;
}
async function uiPlan(page,pid,text,result,changes){
 await call('POST',`/api/projects/${pid}/reset`);
 const d=await call('POST',`/api/projects/${pid}/plan-definitions`,{name:result.model+' · '+result.case,goal:text});
 await ready(page);await page.getByLabel('Select project',{exact:true}).selectOption(pid);await expect(page.getByLabel('Plan name',{exact:true})).toHaveValue(d.name);
 const converted=new Promise(resolve=>{const onResponse=async r=>{if(r.url().endsWith(`/plan-definitions/${d.id}/bind-commands`)&&r.request().method()==='POST'){page.off('response',onResponse);resolve(r)}};page.on('response',onResponse);result._remove=()=>page.off('response',onResponse)});
 const decomposition=page.waitForResponse(r=>r.url().endsWith(`/plan-definitions/${d.id}/decompose`)&&r.request().method()==='POST',{timeout:620000});
 await page.getByRole('button',{name:'Generate plan',exact:true}).click();
 const response=await decomposition,planned=await response.json();result.planner=planned;
 if(!response.ok())throw Error(JSON.stringify(planned));
 if(planned.planning_status!=='tasks_ready')throw Error('Planner did not produce executable tasks: '+planned.planning_status);
 let deadline;const timeout=new Promise((_,reject)=>{deadline=setTimeout(()=>reject(Error('Converter timeout')),620000)});
 let resolved;try{resolved=await Promise.race([converted,timeout])}finally{clearTimeout(deadline)}
 const bound=await resolved.json();result.binding_errors=bound.errors;
 if(!resolved.ok())throw Error(JSON.stringify(bound));
 const finished=await executeRevision(pid,bound.definition,result,changes,page);
 await page.screenshot({path:resolve(output,`${result.slug}-${result.case}.png`),animations:'disabled'});
 return finished;
}
async function businessPlan(page,result){
 const pid='eval_business';await call('POST',`/api/projects/${pid}/reset`);
 await page.request.post('http://127.0.0.1:8086/business/login',{form:{code:'local-model-evaluation-code'}});await page.goto('http://127.0.0.1:8086/business/');
 const hello=page.getByRole('dialog',{name:'Hello.',exact:true});await expect(hello).toBeVisible();await hello.getByRole('button',{name:'Continue',exact:true}).click();await expect(hello).toHaveCount(0);
 await page.getByLabel('Choose workspace',{exact:true}).selectOption(pid);
 await page.getByLabel('Your command',{exact:true}).fill(result.instruction);
 const waiting=page.waitForResponse(r=>r.url().endsWith(`/projects/${pid}/commands`)&&r.request().method()==='POST',{timeout:620000});
 await page.getByRole('button',{name:'Review command',exact:true}).click();const response=await waiting,job=await response.json();result.business_review=job;
 if(!response.ok()||job.status!=='ready')throw Error('Business review: '+(job.status??JSON.stringify(job)));
 const definition=await call('GET',`/api/projects/${pid}/plan-definitions/${job.definition_id}`);result.tasks=definition.tasks;result.inference_evidence=definition.inference_evidence;
 const revision=await call('GET',`/api/projects/${pid}/plans/${job.revision_id}`);result.validation={valid:revision.valid,report:revision.validation_report};result.manifest=revision.motion_manifest;
 verifyStates(revision.frames.at(-1).robot_positions,{arm_01:{base_yaw:.02},arm_02:{base_yaw:-.02}});
 const start=page.waitForResponse(r=>r.url().endsWith(`/commands/${job.id}/run`)&&r.request().method()==='POST',{timeout:20000});await page.getByRole('button',{name:'Start simulation',exact:true}).click();
 const started=await(await start).json(),run=await finalRun(started.run_id);
 result.execution={status:run.status,stopped_verified:run.stopped_verified,states:run.robot_states};
 if(run.status!=='SIMULATION_PASSED')throw Error('Business simulation failed');verifyStates(run.robot_states,{arm_01:{base_yaw:.02},arm_02:{base_yaw:-.02}});
 await page.screenshot({path:resolve(output,`${result.slug}-business.png`),animations:'disabled'});
}
async function apiPlan(result,expected){
 const pid='eval_api';await call('POST',`/api/projects/${pid}/reset`);
 let d=await call('POST',`/api/projects/${pid}/plan-definitions`,{name:result.model+' · '+result.case,goal:result.instruction});
 d=await call('POST',`/api/projects/${pid}/plan-definitions/${d.id}/decompose`,{version:d.version,instruction:d.goal,replace_tasks:false});result.planner=d;
 if(expected){if(d.planning_status!==expected)throw Error(`Expected ${expected}; got ${d.planning_status}`);if(d.tasks.length)throw Error('Unsafe request produced executable tasks');result.correctly_blocked=true;return;}
 const bound=await call('POST',`/api/projects/${pid}/plan-definitions/${d.id}/bind-commands`,{version:d.version});result.binding_errors=bound.errors;
 const run=await executeRevision(pid,bound.definition,result,null,null);
 // Independent FK verifies the final tool location, rather than accepting an HTTP/status success.
 const check=spawnSync(process.execPath,['scripts/python.mjs','-c',"import json,sys; from services.validation.registry import load_model,MODEL_ROOT; from services.planning.kinematics import forward; p=forward(load_model(MODEL_ROOT/'demo_arm'),json.load(sys.stdin)); print(json.dumps([p.x,p.y,p.z]))"],{input:JSON.stringify(run.robot_states.arm_01.positions),encoding:'utf8'});
 if(check.status!==0)throw Error('Independent FK verification failed');const point=JSON.parse(check.stdout);result.measured_tool_position=point;
 if(Math.max(...point.map((v,i)=>Math.abs(v-[.3,-.1,.3][i])))>.003)throw Error('End effector missed the requested point');
 for(const [joint,value]of Object.entries(initial))if(Math.abs(run.robot_states.arm_02.positions[joint]-value)>1e-6)throw Error('ARM TWO moved despite explicit assignment');
 if(Math.abs(run.robot_states.arm_01.positions.gripper-initial.gripper)>1e-6)throw Error('Gripper changed despite instruction');
}
const doc=`Fictional EvaluationSDK 1.0; simulator only. Each method sets one actuator and leaves every other actuator unchanged.
set_base_yaw(value) sets base_yaw in rad; range -3.14 to 3.14.
set_shoulder(value) sets shoulder in rad; range -1.5 to 2.8.
set_elbow(value) sets elbow in rad; range -2.6 to 2.6.
set_wrist(value) sets wrist in rad; range -2.8 to 2.8.
set_gripper(value) sets gripper in m; range 0.0 to 0.08.
read_feedback() returns a dictionary of actuator values. stop_motion() stops movement. disconnect() disconnects.
No other SDK module or API methods are documented.`;
async function driver(result){
 const generated=await call('POST','/api/library/drivers/generate-draft',{name:'Evaluation SDK '+result.model,category:'virtual',sdk_version:'1.0',documentation:doc});result.adapter_generation=generated;
 if(generated.status!=='complete')throw Error('Adapter draft needs information: '+generated.issues?.map(i=>i.message).join('; '));
 const d=generated.driver,functions=d.definition.functions;
 const expected=['base_yaw','shoulder','elbow','wrist','gripper'].map(x=>'set_'+x);
 if(functions.length!==5||functions.some(f=>!expected.includes(f.vendor_method)))throw Error('Generated SDK catalog omitted or invented actuator methods');
 await call('POST',`/api/library/drivers/${d.id}/review`,{expected_hash:d.hash});
 const tested=await call('POST',`/api/library/drivers/${d.id}/test`);result.driver_test=tested.test_report;
 if(!tested.test_report?.passed)throw Error('Generated driver did not pass simulated contracts');
}
let browser;
try{
 browser=await chromium.launch();
 for(const model of models){
  const slug=model.replace(/[^a-zA-Z0-9]+/g,'-');
  const installed=await(await fetch('http://127.0.0.1:11435/api/tags')).json();const info=installed.models.find(m=>m.name===model);
  if(!info){report.models.push({model,status:'not_installed'});save();continue;}
  let source=readFileSync('SERVER_CLIENT/server/examples/llm/ollama_nemotron.py','utf8');
  if(!model.includes('nemotron'))source=source.replace("if 'nemotron-mini' not in model:","if 'nemotron' in model and 'mini' not in model:");
  const profile=await call('POST','/api/llm/adapters',{name:'Evaluation · '+model,protocol:'python_function',connection_type:'custom',source_code:source,base_url:'http://127.0.0.1:11892',model,timeout_seconds:300,max_tokens:4096});
  await call('PUT','/api/llm/default',{adapter_id:profile.id});await call('PUT','/api/llm/roles',{planner_adapter_id:profile.id,binding_adapter_id:profile.id,vision_enabled:false});
  report.models.push({model,digest:info.digest,size:info.size,details:info.details,profile_id:profile.id});save();
  const context=await browser.newContext({viewport:{width:1512,height:982}});await context.request.post('http://127.0.0.1:8085/login',{form:{code:'local-model-evaluation-code'}});
  const page=await context.newPage();page.setDefaultTimeout(15000);
  const business=await context.newPage();business.setDefaultTimeout(15000);
  let app;const desktopProfile=mkdtempSync(resolve(tmpdir(),'robode-real-model-desktop-'));
  for(const name of ['desktop','web','business','ambiguous','impossible','pose','adapter_generation']){
   const result={model,slug,case:name,instruction:instructions[name]??doc,application:['desktop','web','business'].includes(name)?name:'shared runtime',started_at:new Date().toISOString()};report.cases.push(result);save();
   console.log(`${model} / ${name} started`,true);const started=Date.now();
   try{
    if(name==='desktop'){
     const require=createRequire(resolve('ELECTRON_APP/package.json'));
     app=await electron.launch({executablePath:require('electron'),args:[`--user-data-dir=${desktopProfile}`,resolve('ELECTRON_APP')],env:{...process.env,ROBOT_IDE_ORIGIN:'http://127.0.0.1:8085',ROBOT_IDE_DEV:'0',ROBOT_IDE_EDITION:'standard'}});
     const desktop=await app.firstWindow();desktop.setDefaultTimeout(15000);await desktop.request.post('http://127.0.0.1:8085/login',{form:{code:'local-model-evaluation-code'}});
     await uiPlan(desktop,'eval_desktop',result.instruction,result,{arm_01:{base_yaw:.04}});
    }else if(name==='web')await uiPlan(page,'eval_web',result.instruction,result,{arm_01:{base_yaw:-.03,gripper:.04}});
    else if(name==='business')await businessPlan(business,result);
    else if(name==='adapter_generation')await driver(result);
    else await apiPlan(result,name==='ambiguous'?'needs_clarification':name==='impossible'?'unsupported':null);
    result.passed=true;
   }catch(error){result.passed=false;result.error=error.message;console.log('  '+error.message.slice(0,500));try{await(name==='business'?business:page).screenshot({path:resolve(output,`${slug}-${name}-failed.png`),animations:'disabled'})}catch{}}
   finally{result._remove?.();delete result._remove;result.seconds=Number(((Date.now()-started)/1000).toFixed(2));save();console.log(`${model} / ${name}: ${result.passed?'PASS':'FAIL'} (${result.seconds}s)`);}
  }
  await app?.close();rmSync(desktopProfile,{recursive:true,force:true});await context.close();
  // Free this model before evaluating the next; leave the user's original Ollama service alone.
  await fetch('http://127.0.0.1:11435/api/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model,keep_alive:0})}).catch(()=>{});
 }
}finally{await browser?.close();await api.dispose();report.finished_at=new Date().toISOString();save();}
console.log(JSON.stringify({results:resolve(output,'results.json'),summary:models.map(model=>({model,passed:report.cases.filter(c=>c.model===model&&c.passed).length,total:report.cases.filter(c=>c.model===model).length}))}));
