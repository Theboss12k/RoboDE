import { Fragment, useEffect, useState } from "react";
import { api } from "./api";
import type { EffectiveModels, FunctionCall, LLMConfiguration, Plan, PlanDefinition, ProjectDetail } from "./types";
import Feedback from "./ui/Feedback";

type Entry={id:string;kind:string;arguments:Record<string,unknown>;min?:number;max?:number;targets?:string[];frames?:{tool?:string;base?:string}};
export type ValidationStage="commands"|"motion"|"checker"|"done";
export type Validation={stage:ValidationStage;failed?:string};
const stages:[Exclude<ValidationStage,"done">,string][]=[["commands","Convert tasks"],["motion","Plan motion"],["checker","Check collisions"]];

/** Builds catalog arguments from labelled fields; Expert mode can still edit the raw JSON. */
function CallForm({entry,objects,busy,onAdd}:{entry:Entry;objects:{id:string;name:string}[];busy:boolean;onAdd:(args:Record<string,unknown>)=>void}){
 const [value,setValue]=useState(0),[target,setTarget]=useState(entry.targets?.[0]??""),[xyz,setXYZ]=useState([0,0,0]),[object,setObject]=useState(""),[destination,setDestination]=useState("");
 const [raw,setRaw]=useState(""),[error,setError]=useState("");
 const args=():Record<string,unknown>=>entry.kind==="actuator"||entry.kind==="component"?{value,unit:entry.arguments.unit}:entry.kind==="move"?{target,position:target==="base"?xyz.slice(0,2):xyz,frame:target==="base"?entry.frames?.base??entry.arguments.frame:entry.frames?.tool??entry.arguments.frame}
  :{object_id:object,...(entry.kind==="verify"&&destination?{target_id:destination}:{})};
 useEffect(()=>{setRaw(JSON.stringify(args(),null,2))},[entry.id,value,target,xyz.join(),object,destination]);
 return <div className="call-form">
  {(entry.kind==="actuator"||entry.kind==="component")&&<label className="field">Value · {String(entry.arguments.unit)}{entry.min!==undefined&&` (${entry.min} to ${entry.max})`}<input aria-label="Function value" type="number" step="any" min={entry.min} max={entry.max} value={value} disabled={busy} onChange={e=>setValue(Number(e.target.value))}/></label>}
  {entry.kind==="move"&&<><label className="field">Move<select aria-label="Function MOVE target" value={target} disabled={busy} onChange={e=>setTarget(e.target.value)}>{entry.targets?.map(t=><option key={t} value={t}>{t==="base"?"Mobile base":`Tool ${t}`}</option>)}</select></label>
   <div className="coordinate-grid">{["X","Y","Z"].filter(a=>target!=="base"||a!=="Z").map((a,n)=><label className="field" key={a}>{a} (m)<input aria-label={`Function ${a} (m)`} type="number" step="any" value={xyz[n]} disabled={busy} onChange={e=>{const v=[...xyz];v[n]=Number(e.target.value);setXYZ(v)}}/></label>)}</div><small>Frame: {String(target==="base"?entry.frames?.base??entry.arguments.frame:entry.frames?.tool??entry.arguments.frame)}</small></>}
  {["grasp","release","verify"].includes(entry.kind)&&<><label className="field">Object<select aria-label="Function object" value={object} disabled={busy} onChange={e=>setObject(e.target.value)}><option value="">Choose object</option>{objects.map(o=><option key={o.id} value={o.id}>{o.name}</option>)}</select></label>
   {entry.kind==="verify"&&<label className="field">Destination · optional<select aria-label="Function destination" value={destination} disabled={busy} onChange={e=>setDestination(e.target.value)}><option value="">None</option>{objects.map(o=><option key={o.id} value={o.id}>{o.name}</option>)}</select></label>}</>}
  <details className="expert-only"><summary>Arguments (JSON)</summary><textarea aria-label="Function call arguments" spellCheck={false} disabled={busy} value={raw} onChange={e=>setRaw(e.target.value)}/></details>
  <Feedback message={error}/>
  <button disabled={busy} onClick={()=>{try{const fromJson=JSON.parse(raw);const a=JSON.stringify(fromJson)!==JSON.stringify(args())?fromJson:args();if(!a||typeof a!=="object"||Array.isArray(a))throw Error("Arguments must be a JSON object");onAdd(a);setError("")}catch(e){setError((e as Error).message)}}}>Add function call</button>
 </div>;
}

export default function PlanningPipeline({detail,draft,revision,llm,busy,dirty,validation,canSimulate,onChange,onDecompose,onBind,onValidate,onSimulate,onSaved,onConfigureAI,onOpenControls,activity}:{
 detail:ProjectDetail;draft:PlanDefinition;revision:Plan|null;llm:LLMConfiguration;busy:boolean;dirty:boolean;validation:Validation|null;canSimulate:boolean;activity?:string|null;
 onChange:(value:PlanDefinition)=>void;onDecompose:(answers:Record<string,string>,replace:boolean,image?:unknown)=>void;onBind:()=>void;onValidate:()=>void;onSimulate:()=>void;onSaved:(p:PlanDefinition)=>void;onConfigureAI:()=>void;onOpenControls:()=>void;
}){
 const [answers,setAnswers]=useState<Record<string,string>>({}),[replace,setReplace]=useState(false),[error,setError]=useState("");
 const [models,setModels]=useState<EffectiveModels|null>(null);
 const [capture,setCapture]=useState<{snapshot_id:string;captured_at:string;mime_type:string;data_base64:string}|null>(null);
 useEffect(()=>{setReplace(false);setAnswers({});setCapture(null)},[draft.id]);
 useEffect(()=>{void api<EffectiveModels>(`/projects/${detail.project.id}/plan-definitions/${draft.id}/effective-models`).then(setModels).catch(()=>setModels(null))},[draft.id,draft.version,llm,detail.project.id]);
 const describe=(m?:{name:string|null;model:string|null;missing:boolean})=>m?.missing?"Unavailable model":m?.model??"Not configured";
 const scope=draft.allowed_robot_ids??[];
 const report=revision?.validation_report;
 const reportStale=dirty||revision?.definition_version!==draft.version||revision?.fingerprint!==detail.fingerprint;
 const failed=draft.tasks.filter(t=>t.binding_error);
 const overridden=draft.role_settings?.planner_adapter_id||draft.role_settings?.binding_adapter_id;
 // Each role is chosen independently; an empty choice falls back to the workspace Planner LLM or Task LLM.
 const selectRole=async(key:"planner_adapter_id"|"binding_adapter_id",id:string)=>{try{onSaved(await api<PlanDefinition>(`/projects/${detail.project.id}/plan-definitions/${draft.id}/roles`,{method:"PUT",body:JSON.stringify({...(draft.role_settings??{vision_enabled:false}),[key]:id||null})}));setError("")}catch(e){setError((e as Error).message)}};
 const roles=[["planner_adapter_id","Planner LLM",models?.planner],["binding_adapter_id","Task LLM",models?.binder]] as const;
 return <section className="plan-composer" aria-label="Plan instruction and actions">
  <div className="composer-heading"><div><span className="eyebrow">PROJECT → PLAN → TASKS</span><h3>What should the robots do?</h3></div><button className="text-button" disabled={busy} onClick={onOpenControls}>Robot controls</button></div>
  <label className="field plan-goal">Plan instruction<textarea aria-label="Plan goal" placeholder="Move the apple into the basket with Arm One, while Arm Two waves twice." value={draft.goal} disabled={busy} onChange={e=>onChange({...draft,goal:e.target.value})}/></label>
  <div className="composer-control-row"><div className="composer-robot-scope"><label className="field">Robots<select aria-label="Plan robot assignment" value={scope.length?"selected":"automatic"} disabled={busy} onChange={e=>onChange({...draft,allowed_robot_ids:e.target.value==="automatic"?[]:detail.robots.map(r=>r.instance.instance.id)})}><option value="automatic">Auto assign from project robots</option><option value="selected">Use selected robots</option></select></label>
   {scope.length>0&&<div role="group" aria-label="Robots allowed for this plan" className="plan-robot-choices">{detail.robots.map(r=>{const id=r.instance.instance.id;return <label key={id}><input type="checkbox" checked={scope.includes(id)} disabled={busy||(scope.length===1&&scope[0]===id)} onChange={e=>onChange({...draft,allowed_robot_ids:e.target.checked?[...scope,id]:scope.filter(x=>x!==id)})}/>{r.instance.instance.name}</label>})}</div>}
  </div>
  <div className="composer-actions" aria-label="Plan actions">
   <button className="primary" disabled={busy||!detail.robots.length||!draft.goal.trim()||!!draft.tasks.length&&!replace} onClick={()=>onDecompose(answers,replace,capture??undefined)}>{draft.tasks.length?"Regenerate plan":"Generate plan"}</button>
   <button className="secondary" disabled={busy||!draft.tasks.length} onClick={onValidate}>Validate plan</button>
   <button className="secondary" disabled={busy||!canSimulate} title={canSimulate?"Run the exact validated plan":"Validate the plan before running"} onClick={onSimulate}>Run simulation</button>
  </div>
  </div>
  {!!draft.tasks.length&&<label className="check-field regenerate-consent"><input type="checkbox" checked={replace} disabled={busy} onChange={e=>setReplace(e.target.checked)}/>Replace tasks and manual edits when regenerating</label>}
  <div className="composer-models" aria-label="Planner LLM and Task LLM">{roles.map(([key,label,effective],i)=><Fragment key={key}>{i>0&&<span aria-hidden="true">→</span>}
   <label className="composer-role"><strong>{label}</strong><select aria-label={`${label} for this plan`} value={draft.role_settings?.[key]??""} disabled={busy||dirty} onChange={e=>void selectRole(key,e.target.value)}>
    <option value="">{draft.role_settings?.[key]?"Workspace setting":`Workspace setting · ${describe(effective)}`}</option>{llm.adapters.map(p=><option key={p.id} value={p.id}>{p.name} · {p.model}</option>)}</select></label></Fragment>)}
   <button className="text-button" disabled={busy} onClick={onConfigureAI}>Configure AI</button></div>
  {dirty&&<small className="composer-explanation">Save the plan before changing its models.</small>}
  <small className="composer-explanation">The Planner LLM creates tasks and assigns robots. The Task LLM turns each task into the robot’s available actuator commands. You can edit the result before running.</small>
  {activity&&<p role="status" className="inline-note">{activity}</p>}
  <Feedback message={error}/>
  {draft.planning_error&&<Feedback message={draft.planning_error}/>}
  {draft.clarification_questions?.map(question=><label className="field" key={question}>{question}<input aria-label={question} value={answers[question]??""} disabled={busy} onChange={e=>setAnswers({...answers,[question]:e.target.value})}/></label>)}
  {validation&&<ol className="validate-progress" aria-label="Validation progress">{stages.map(([id,label],i)=>{const at=validation.stage==="done"?3:stages.findIndex(s=>s[0]===validation.stage);const state=i<at?"done":i===at?(validation.failed?"failed":"active"):"";return <li key={id} className={state}>{label}{state==="failed"?" · failed":state==="done"?" · done":state==="active"?" · running":""}</li>})}</ol>}
  {validation?.failed&&<Feedback message={validation.failed}/>}
  {!!failed.length&&<p role="alert" className="inline-note danger">{failed.length} task{failed.length===1?" needs":"s need"} conversion fixes. Select a task below to review its explanation.</p>}
  {report&&<details className={`plan-check-summary status-${report.status}`} open={report.status==="failed"}><summary>Motion and collision check: {reportStale?"outdated · validate again":report.status}</summary><p>{reportStale?"This report belongs to an earlier plan or scene. Validate the current plan before running.":report.status==="incomplete"?"Simulation is available, but physical execution stays blocked until all checks are complete.":report.status==="failed"?"Correct the failed checks before running.":"Motion checks passed. Physical movement still requires hardware validation and arming."}</p><ul>{report.findings.map((f,i)=><li key={i}>{f.task_id??f.robot_id??f.code}: {f.message}</li>)}</ul><small className="expert-only">Coverage: {report.coverage.join(", ")}</small></details>}
  <details className="expert-only composer-advanced"><summary>Advanced plan settings</summary>
   {overridden&&<small>This plan uses its own Planner LLM or Task LLM; they are selected above.</small>}
   {models?.custom&&models.explanations.map(x=><small key={x}>{x}</small>)}
   <button disabled={busy||!draft.tasks.length} onClick={onBind}>Convert commands again</button>
   <button disabled={busy||!detail.fingerprint} onClick={()=>{try{const canvas=document.querySelector<HTMLCanvasElement>(".plans-workspace canvas");if(!canvas)throw Error("Open the Simulation view before capturing the scene.");const data=canvas.toDataURL("image/png").split(",")[1];setCapture({snapshot_id:detail.fingerprint!,captured_at:new Date().toISOString(),mime_type:"image/png",data_base64:data});setError("")}catch(e){setError((e as Error).message)}}}>Capture scene for vision planner</button>{capture&&<small>Scene captured. Generate within 30 seconds.</small>}
   {!!draft.inference_evidence?.length&&<ul>{draft.inference_evidence.map((e,i)=><li key={i}><small>{e.stage==="binder"?"Task LLM":"Planner LLM"} · {e.model} · {e.duration_seconds?.toFixed(1)} s</small></li>)}</ul>}
  </details>
 </section>;
}

export function TaskCommandEditor({detail,draft,task,busy,onChange}:{detail:ProjectDetail;draft:PlanDefinition;task:NonNullable<PlanDefinition['tasks'][number]>;busy:boolean;onChange:(p:PlanDefinition)=>void}){
 const [entries,setEntries]=useState<Entry[]>([]),[fn,setFn]=useState(""),[error,setError]=useState("");
 useEffect(()=>{let active=true;setEntries([]);setFn("");setError("");if(task.robot_id)void api<Entry[]>(`/projects/${detail.project.id}/robots/${task.robot_id}/functions`).then(rows=>{if(active)setEntries(rows)}).catch(e=>{if(active)setError(e.message)});return()=>{active=false}},[task.id,task.robot_id,detail.project.id]);
 const update=(patch:Partial<typeof task>)=>onChange({...draft,tasks:draft.tasks.map(t=>t.id===task.id?{...task,...patch,authored_by:"user",binding_status:"unresolved",binding_fingerprint:null}:t)});
 const changeCalls=(calls:FunctionCall[])=>update({function_calls:calls});
 const entry=entries.find(e=>e.id===fn);
 return <section className="task-command-editor" aria-label="Task actuator commands">
  <label className="field">What this task does<textarea aria-label="Semantic task intent" disabled={busy} value={task.intent??""} onChange={e=>update({intent:e.target.value,function_calls:[],binding_error:null})}/></label>
  <h4>Actuator commands <small>{task.binding_status==="resolved"?"Converted":"Needs conversion"}</small></h4>
  <Feedback message={task.binding_error??error}/>
  {task.function_calls?.length?<ol className="resolved-calls">{task.function_calls.map((c,i)=><li key={i}><code>{c.function}({Object.entries(c.arguments).map(([k,v])=>`${k}=${JSON.stringify(v)}`).join(", ")})</code><button title="Remove this command" aria-label={`Remove call ${i+1}`} disabled={busy} onClick={()=>changeCalls((task.function_calls??[]).filter((_,j)=>j!==i))}>Remove</button></li>)}</ol>:<p className="inline-note">The converter will fill these commands when you generate or validate the plan.</p>}
  <details><summary>Add a command manually</summary><label className="field">Available robot command<select aria-label="Approved task function" value={fn} disabled={busy} onChange={e=>setFn(e.target.value)}><option value="">Select command</option>{entries.map(e=><option key={e.id} value={e.id}>{e.id}</option>)}</select></label>{entry&&<CallForm key={entry.id} entry={entry} objects={detail.objects??[]} busy={busy} onAdd={a=>changeCalls([...(task.function_calls??[]),{function:entry.id,arguments:a}])}/>}</details>
  <details className="expert-only"><summary>Timing and repetition</summary><label className="field">Duration (seconds)<input aria-label="Task duration seconds" type="number" step="any" min="0.01" max="3600" value={task.duration_seconds??""} disabled={busy} onChange={e=>update({duration_seconds:e.target.value?Number(e.target.value):null})}/></label><label className="field">Repetitions<input aria-label="Task repetitions" type="number" min="1" max="100" value={task.repeat_count??1} disabled={busy} onChange={e=>update({repeat_count:Number(e.target.value)})}/></label></details>
 </section>;
}
