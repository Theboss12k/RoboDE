/** Isolate the Converter from Planner failures, using the same disposable runtime. */
import {request} from '@playwright/test';
import {readFileSync,writeFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {spawnSync} from 'node:child_process';
const output=resolve(process.env.ROBO_EVALUATION_OUTPUT||'artifacts/nemotron-local-20261030');
const baseline=JSON.parse(readFileSync(resolve(output,'results.json'),'utf8'));
const api=await request.newContext({baseURL:'http://127.0.0.1:8085',timeout:320000});
await api.post('/login',{form:{code:'local-model-evaluation-code'}});
async function call(method,path,data){const r=await api.fetch(path,{method,...(data?{data}:{})});const b=await r.json();if(!r.ok())throw Error(JSON.stringify(b));return b;}
const report={started_at:new Date().toISOString(),scope:'Converter only: predefined semantic tasks, no Planner inference or generated calls injected',cases:[]};
const save=()=>writeFileSync(resolve(output,'converter-results.json'),JSON.stringify(report,null,2)+'\n');
const initial={base_yaw:0,shoulder:1,elbow:-1.8,wrist:.8,gripper:.08};
const cases=[
 {id:'joint',intent:'Set ARM ONE base_yaw to 0.04 rad. Leave all other joints and ARM TWO unchanged.'},
 {id:'pose',intent:'Move ARM ONE parallel_gripper to world position x=0.30 m, y=-0.10 m, z=0.30 m. Do not specify orientation. Keep its gripper opening and ARM TWO unchanged.'},
];
try{
 for(const model of baseline.models){
  for(const test of cases){
   const c={model:model.model,case:test.id,instruction:test.intent,started_at:new Date().toISOString()};report.cases.push(c);save();const started=Date.now();
   console.log(`${model.model} / converter ${test.id} started`);
   try{
    await call('POST','/api/projects/eval_api/reset');
    let d=await call('POST','/api/projects/eval_api/plan-definitions',{name:`Converter ${test.id} · ${model.model}`,goal:test.intent});
    const path=`/api/projects/eval_api/plan-definitions/${d.id}`;
    d=await call('PUT',path,{version:d.version,name:d.name,goal:d.goal,tasks:[{id:'task_01',name:test.id,operation:'command',robot_id:'arm_01',intent:test.intent,authored_by:'planner',binding_status:'unresolved',function_calls:[],dependencies:[]}]});
    const bound=await call('POST',path+'/bind-commands',{version:d.version,adapter_id:model.profile_id});
    c.tasks=bound.definition.tasks;c.errors=bound.errors;c.inference_evidence=bound.definition.inference_evidence;
    if(bound.errors.length||c.tasks.some(t=>t.binding_status!=='resolved'))throw Error('Converter left unresolved commands');
    const revision=await call('POST',path+'/compile');c.validation={valid:revision.valid,report:revision.validation_report};c.manifest=revision.motion_manifest;
    if(!revision.valid)throw Error('Motion validation failed');
    const run=await call('POST',`/api/projects/eval_api/plans/${revision.id}/simulate`,{fingerprint:revision.fingerprint,adapter:'mock'});
    let final;
    for(let n=0;n<200;n++){final=await call('GET','/api/runs/'+run.id);if(final.finished_at)break;await new Promise(r=>setTimeout(r,100));}
    c.execution={status:final.status,stopped_verified:final.stopped_verified,states:final.robot_states};
    if(final.status!=='SIMULATION_PASSED'||!final.stopped_verified)throw Error('Simulation did not confirm success and stopped feedback');
    for(const [joint,value]of Object.entries(initial))if(Math.abs(final.robot_states.arm_02.positions[joint]-value)>1e-6)throw Error('Unassigned robot moved');
    if(test.id==='joint'){
     for(const [joint,value]of Object.entries({...initial,base_yaw:.04}))if(Math.abs(final.robot_states.arm_01.positions[joint]-value)>1e-6)throw Error('Wrong actuator state: '+joint);
    }else{
     const measured=spawnSync(process.execPath,['scripts/python.mjs','-c',"import json,sys; from services.validation.registry import load_model,MODEL_ROOT; from services.planning.kinematics import forward; p=forward(load_model(MODEL_ROOT/'demo_arm'),json.load(sys.stdin)); print(json.dumps([p.x,p.y,p.z]))"],{input:JSON.stringify(final.robot_states.arm_01.positions),encoding:'utf8'});
     if(measured.status!==0)throw Error('FK check failed');c.measured_tool_position=JSON.parse(measured.stdout);
     if(Math.max(...c.measured_tool_position.map((v,i)=>Math.abs(v-[.3,-.1,.3][i])))>.003)throw Error('Incorrect tool position');
     if(Math.abs(final.robot_states.arm_01.positions.gripper-initial.gripper)>1e-6)throw Error('Gripper changed');
    }
    c.passed=true;
   }catch(error){c.passed=false;c.error=error.message;}
   c.seconds=Number(((Date.now()-started)/1000).toFixed(2));save();console.log(`${model.model} / converter ${test.id}: ${c.passed?'PASS':'FAIL'} (${c.seconds}s) ${c.error??''}`);
  }
  await fetch('http://127.0.0.1:11435/api/generate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({model:model.model,keep_alive:0})});
 }
}finally{await api.dispose();report.finished_at=new Date().toISOString();save();}
