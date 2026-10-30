"""Deterministic trajectory checking with explicit coverage, never an LLM verdict."""
import math
from shared.models.robotics import ValidationReport,ValidationFinding
from services.validation.trajectory import validate_trajectory
from services.planning.workflow import validate_cell
from services.planning.kinematics import forward,with_base


async def check_plan(client,models,frames,objects):
    findings=[];coverage=['joint_limits','velocity','acceleration','sampled_geometry','synchronized_robots']
    for rid,model in models.items():
        try:
            stationary=model.get('mobility',{}).get('classification','STATIONARY')=='STATIONARY'
            validate_trajectory(model,[f.model_copy(update={'positions':f.robot_positions[rid]}) for f in frames],objects,check_geometry=stationary)
            binding=model.get('binding',{}).get('definition',{})
            bounds=binding.get('workspace_bounds');nav=binding.get('mobility',{}).get('navigation_bounds')
            for frame in frames:
                base=frame.base_poses.get(rid,model.get('base_pose',{}))
                if nav and not (nav[0]<=base.get('x',0)<=nav[2] and nav[1]<=base.get('y',0)<=nav[3]):
                    raise ValueError('Robot base leaves the configured navigation workspace')
                if bounds and binding.get('mobility',{}).get('classification')!='MOVING':
                    p=forward({**model,'base_pose':base},frame.robot_positions[rid])
                    if any(not bounds[n]<=v<=bounds[n+3] for n,v in enumerate((p.x,p.y,p.z))):
                        findings.append(ValidationFinding(code='OUT_OF_WORKSPACE',message='Tool leaves configured workspace',robot_id=rid,task_id=frame.active_steps.get(rid),position=[p.x,p.y,p.z],time=frame.time))
        except ValueError as error:findings.append(ValidationFinding(code='TRAJECTORY',message=str(error),robot_id=rid))
    try:
        if all(m.get('mobility',{}).get('classification','STATIONARY')=='STATIONARY' for m in models.values()):validate_cell(frames,models,objects)
    except ValueError as error:findings.append(ValidationFinding(code='ROBOT_COLLISION',message=str(error)))
    if findings:return ValidationReport(status='failed',coverage=coverage,findings=findings)
    from services.planning.motion_client import MotionUnavailable
    try:
        report=ValidationReport.model_validate(await client.validate(models,frames,objects))
        report.coverage=list(dict.fromkeys(coverage+report.coverage));return report
    except MotionUnavailable as error:
        return ValidationReport(status='incomplete',coverage=coverage,findings=[ValidationFinding(code='WORKER_UNAVAILABLE',message=str(error))])
