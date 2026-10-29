import type { Model, StandardCommand } from "./types";
export default function StandardTaskEditor({model,command,onChange,disabled}:{model:Model;command:StandardCommand;onChange:(v:StandardCommand)=>void;disabled:boolean}) {
 const actuators=model.actuators.actuators;
 const effectors=Object.keys(model.kinematics.end_effectors??{});
 if(!effectors.length&&model.kinematics.solver==="analytic_yaw_two_link_v1")effectors.push(model.capabilities.end_effector);
 const components={...(model.capabilities.components??{})};
 if(model.kinematics.solver==="analytic_yaw_two_link_v1"&&actuators.gripper)components[model.capabilities.end_effector]??={actuator:"gripper",closed:0,open:.08};
 const targets=command.type==="SET_ACTUATOR"?Object.keys(actuators):command.type==="SET_COMPONENT"?Object.keys(components):effectors;
 function choose(type:StandardCommand["type"],target?:string){
  const id=target??(type==="SET_ACTUATOR"?Object.keys(actuators)[0]:type==="SET_COMPONENT"?Object.keys(components)[0]:effectors[0])??"";
  onChange(type==="MOVE_END_EFFECTOR"?{type,target:id,position:[.3,0,.3],position_unit:"m",frame:model.kinematics.world_frame??"world"}:{type,target:id,value:type==="SET_COMPONENT"?50:Math.max(actuators[id]?.min??0,Math.min(0,actuators[id]?.max??0)),unit:type==="SET_COMPONENT"?"percent":actuators[id]?.unit as "rad"|"m"});
 }
 return <section className="standard-task-editor">
  <label className="field">Command type<select aria-label="Standard command type" value={command.type} disabled={disabled} onChange={e=>choose(e.target.value as StandardCommand["type"])}>
   <option value="SET_ACTUATOR">Set actuator · direct</option><option value="SET_COMPONENT">Set component · direct</option><option value="MOVE_END_EFFECTOR">Move end effector · IK</option>
  </select></label>
  <label className="field">Target component<select aria-label="Command target" value={command.target} disabled={disabled} onChange={e=>choose(command.type,e.target.value)}>{!targets.length&&<option value="">No configured targets</option>}{targets.map(id=><option key={id}>{id}</option>)}</select></label>
  {command.type==="MOVE_END_EFFECTOR"?<>
   <p>Frame: {command.frame} · position in m. IK uses the configured model and joint limits.</p>
   <div className="coordinate-inputs">{["X","Y","Z"].map((axis,i)=><label key={axis}>{axis} · m<input aria-label={`Command ${axis}`} type="number" step=".01" value={command.position?.[i]??0} disabled={disabled} onChange={e=>{const position=[...(command.position??[0,0,0])] as [number,number,number];position[i]=Number(e.target.value);onChange({...command,position});}}/></label>)}</div>
   <label><input type="checkbox" aria-label="Include tool orientation" checked={!!command.orientation_rpy} disabled={disabled} onChange={e=>onChange({...command,orientation_rpy:e.target.checked?[0,0,0]:undefined,orientation_unit:e.target.checked?"rad":undefined})}/> Specify tool orientation</label>
   {command.orientation_rpy&&<div className="coordinate-inputs">{["Roll","Pitch","Yaw"].map((axis,i)=><label key={axis}>{axis} · rad<input aria-label={`Command ${axis}`} type="number" step=".01" value={command.orientation_rpy![i]} disabled={disabled} onChange={e=>{const orientation_rpy=[...command.orientation_rpy!] as [number,number,number];orientation_rpy[i]=Number(e.target.value);onChange({...command,orientation_rpy});}}/></label>)}</div>}
  </>:<label className="field">Target value · {command.unit}<input aria-label="Command value" type="number" step=".01" min={command.unit==="percent"?0:actuators[command.target]?.min} max={command.unit==="percent"?100:actuators[command.target]?.max} value={command.value??0} disabled={disabled} onChange={e=>onChange({...command,value:Number(e.target.value)})}/><small>{command.unit==="percent"?"0 = closed; 100 = open":`${actuators[command.target]?.min} to ${actuators[command.target]?.max} ${command.unit}`} · Direct adapter control; IK is bypassed.</small></label>}
 </section>;
}
