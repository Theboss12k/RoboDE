"""Reviewed model/driver mappings; robot and driver identifiers remain stable."""
import json
import math
import uuid
from services.api.storage import atomic_json, safe_id, fingerprint
from services.validation.registry import load_model, validate_positions
from shared.models.robotics import RobotBinding
from shared.models.domain import now


class BindingRegistry:
    def __init__(self, store, drivers):
        self.store, self.drivers = store, drivers
        self.root = store.runtime/'robot_bindings'
    def path(self, binding_id): return self.root/safe_id(binding_id)/'binding.json'
    def list(self):
        result=[]
        for p in sorted(self.root.glob('*/binding.json')):
            b=self.get(p.parent.name,False)
            try:self.get(b['id']);b['validation_status']='current'
            except ValueError as error:b['validation_status']='stale';b['validation_error']=str(error)
            result.append(b)
        return result
    def get(self, binding_id, check_current=True):
        b=json.loads(self.path(binding_id).read_text())
        if b['hash']!=fingerprint({k:b[k] for k in ('definition','version','driver_hash','model_hash')}):raise ValueError('Mapping contents changed outside the review workflow')
        if check_current:
            driver=self.drivers.get(b['definition']['driver_id'])
            model=load_model(self.store.model_folder(b['definition']['model_id']))
            b['function_catalog']=driver['definition']['functions']
            if driver['hash']!=b['driver_hash'] or fingerprint(model)!=b['model_hash']:
                raise ValueError('Robot or driver changed; review and test a new binding')
        return b
    def get_revision(self,binding_id,digest):
        b=self.get(binding_id,False)
        if b['hash']==digest:return b
        old=json.loads((self.root/safe_id(binding_id)/'revisions'/(safe_id(digest)+'.json')).read_text())
        if old['hash']!=digest or old['hash']!=fingerprint({k:old[k] for k in ('definition','version','driver_hash','model_hash')}):raise ValueError('Historical mapping checksum differs')
        return old
    def save(self, data, binding_id=None):
        if binding_id:
            old=self.get(binding_id,False)
            if old['definition']==data.model_dump() and old['driver_hash']==self.drivers.get(data.driver_id)['hash'] and old['model_hash']==fingerprint(load_model(self.store.model_folder(data.model_id))):return old
        model=load_model(self.store.model_folder(data.model_id));driver=self.drivers.get(data.driver_id)
        controls=model['actuators']['actuators'];functions={f['id']:f for f in driver['definition']['functions']}
        if {j.joint_id for j in data.joints}!=set(controls) or len(data.joints)!=len(controls):
            raise ValueError('Map every moving URDF joint exactly once')
        names=set();used=set()
        for j in data.joints:
            if not math.isfinite(j.scale) or j.scale==0 or not math.isfinite(j.offset):raise ValueError('Mapping scale must be finite and nonzero')
            alias=(j.alias or j.joint_id).casefold()
            if alias in names:raise ValueError('Joint aliases must be unique within the robot')
            names.add(alias)
            if j.role=='independent':
                f=functions.get(j.function_id)
                if not f or j.function_id in used:raise ValueError('Choose one unique declared function for each independent joint')
                used.add(j.function_id)
                dimension={'rad':'angle','deg':'angle','m':'length','mm':'length'}
                if dimension[f['unit'].removesuffix('/s')]!=dimension[controls[j.joint_id]['unit']]:raise ValueError('Function and joint dimensions differ')
                if f['mode']=='position':
                    mapped=[controls[j.joint_id][key]*j.scale+j.offset for key in ('min','max')]
                    if min(mapped)<f['minimum']-1e-9 or max(mapped)>f['maximum']+1e-9:raise ValueError('Mapped URDF range exceeds the driver function limits')
            elif j.function_id:raise ValueError('Passive and coupled joints cannot have independent setters')
            if j.role=='coupled' and (j.coupled_to not in controls or j.coupled_to==j.joint_id):raise ValueError('Coupling requires another configured joint')
        by_id={j.joint_id:j for j in data.joints}
        for j in data.joints:
            seen=set();cursor=j
            while cursor.role=='coupled':
                if cursor.joint_id in seen:raise ValueError('Joint coupling contains a cycle')
                seen.add(cursor.joint_id);cursor=by_id[cursor.coupled_to]
        if model['kinematics']['solver']=='analytic_yaw_two_link_v1' and (set(data.end_effectors)!={model['capabilities']['end_effector']} or any(e.get('link')!='tool' or any(e.get(k,[0,0,0])) for e in data.end_effectors.values() for k in ('xyz','rpy'))):raise ValueError('The educational demo has a fixed tool TCP. Use a reviewed URDF for configurable tools and offsets')
        links={j['child'] for j in model['kinematics']['joints']}|{j['parent'] for j in model['kinematics']['joints']}
        if data.mobility.classification!='MOVING' and not data.end_effectors:raise ValueError('Select an end-effector link from the rendered model')
        for e in data.end_effectors.values():
            if e.get('link') not in links:raise ValueError('Unknown end-effector link')
            for key in ('xyz','rpy'):
                v=e.get(key,[0,0,0])
                if len(v)!=3 or not all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) for x in v):raise ValueError('Tool offsets require finite XYZ/RPY triples')
        if data.grasp_enabled:
            from services.commands.standard import tool_component
            configured={**model,'kinematics':{**model['kinematics'],'end_effectors':data.end_effectors}}
            for tool in data.end_effectors:tool_component(configured,tool)
        for tool,touch in data.grasp_contacts.items():
            if tool not in data.end_effectors or not touch or any(link not in links for link in touch):raise ValueError('Grasp contacts must name reviewed tool IDs and known touch links')
        m=data.mobility
        if m.classification!='STATIONARY':
            if m.left_wheel==m.right_wheel or any(w not in controls for w in (m.left_wheel,m.right_wheel)):raise ValueError('Select distinct left and right wheel actuators')
            for w in (m.left_wheel,m.right_wheel):
                f=functions.get(by_id[w].function_id)
                if not f or f['mode']!='velocity' or f['unit'] not in {'rad/s','deg/s'} or not f['minimum']<0<f['maximum']:raise ValueError('Differential-drive wheels require documented angular velocity functions')
            if len(m.footprint)<3 or any(len(p)!=2 or not all(math.isfinite(x) for x in p) for p in m.footprint):raise ValueError('Configure a planar footprint polygon')
            if not m.navigation_bounds or len(m.navigation_bounds)!=4 or m.navigation_bounds[0]>=m.navigation_bounds[2] or m.navigation_bounds[1]>=m.navigation_bounds[3]:raise ValueError('Configure navigation bounds [min_x,min_y,max_x,max_y]')
            if m.classification=='BOTH':validate_positions(model,m.transit_positions)
        if data.workspace_bounds and (len(data.workspace_bounds)!=6 or any(data.workspace_bounds[n]>=data.workspace_bounds[n+3] for n in range(3))):raise ValueError('Workspace bounds require min XYZ followed by max XYZ')
        old=self.get(binding_id,False) if binding_id else None
        if old:atomic_json(self.root/safe_id(binding_id)/'revisions'/(old['hash']+'.json'),old)
        b={'id':binding_id or uuid.uuid4().hex[:12],'version':old['version']+1 if old else 1,'definition':data.model_dump(),
           'driver_hash':driver['hash'],'model_hash':fingerprint(model),'created_at':now(),'published':False,'test_evidence':{},'hardware_validations':[],'function_catalog':driver['definition']['functions']}
        b['hash']=fingerprint({k:b[k] for k in ('definition','version','driver_hash','model_hash')});atomic_json(self.path(b['id']),b);return b
    def record_test(self, binding_id, kind, evidence):
        b=self.get(binding_id);b['test_evidence'][kind]={'hash':b['hash'],**evidence};atomic_json(self.path(binding_id),b);return b
    def review(self,binding_id,expected_hash):
        b=self.get(binding_id)
        if b['hash']!=expected_hash:raise ValueError('Mapping changed since review')
        b['reviewed_hash']=b['hash'];atomic_json(self.path(binding_id),b);return b
    def publish(self,binding_id):
        b=self.get(binding_id);d=self.drivers.get(b['definition']['driver_id'])
        from services.adapters.drivers import DRIVER_CONTRACT
        if (d.get('test_report') or {}).get('contract_version')!=DRIVER_CONTRACT:raise ValueError('Retest the driver with the current worker contract before publishing')
        if b.get('reviewed_hash')!=b['hash'] or d['reviewed_hash']!=d['hash'] or not (d.get('test_report') or {}).get('passed'):
            raise ValueError('Review the mapping and pass reviewed driver tests first')
        for stage in ('actuators','move'):
            evidence=b['test_evidence'].get(stage,{})
            if evidence.get('hash')!=b['hash'] or not evidence.get('passed'):raise ValueError('Pass actuator and MOVE tests for this exact mapping before publishing')
        expected={j['joint_id'] for j in b['definition']['joints'] if j['role']=='independent'}
        if not expected.issubset(b['test_evidence']['actuators'].get('tested_joints',[])):
            raise ValueError('Test every independent actuator before publishing')
        b['published']=True;atomic_json(self.path(binding_id),b);return b


def enrich_model(model,binding):
    import copy
    model=copy.deepcopy(model);d=binding['definition'];model['binding']=binding
    model['control_functions']={f['id']:f for f in binding.get('function_catalog',[])}
    if d.get('physical_description'):model['robot']['description']=d['physical_description']
    if not d.get('grasp_enabled'):model['capabilities']['operations']=[op for op in model['capabilities']['operations'] if op!='pick_place']
    model['mobility']=d['mobility'];model['joint_aliases']={j['joint_id']:j['alias'] or j['joint_id'] for j in d['joints']}
    model['kinematics']['end_effectors']=d['end_effectors']
    if d.get('grasp_enabled') and (model['capabilities'].get('components') or 'gripper' in model['actuators']['actuators']) and model['capabilities']['payload_kg']>0:
        model['capabilities']['operations']=list(dict.fromkeys([*model['capabilities']['operations'],'pick_place']))
    if d['mobility']['classification']!='STATIONARY':model['continuous_joints']=[d['mobility']['left_wheel'],d['mobility']['right_wheel']]
    return model
