"""Deliberately non-physical worker for isolated browser/transport tests only."""
import copy
from shared.models.domain import RobotState,now


class ContractScene:
    metadata={'engine':'contract_test','physics_available':False,'simulator_version':'test',
        'asset_sha256':'test-only','scene_loading':True,'scene_editing':True,'automatic_scene_transfer':True}
    def __init__(self):
        self.models={};self.instances={};self.objects=[];self.states={};self.loads=[];self.resets=0
    def load_scene(self,request):
        self.loads.append(request.model_copy(deep=True))
        self.models={r['instance']['instance']['id']:r['model'] for r in request.robots}
        self.instances={r['instance']['instance']['id']:r['instance'] for r in request.robots}
        self.states={rid:RobotState(instance_id=rid,positions=i['initial_configuration']['actuator_positions'],source='simulation') for rid,i in self.instances.items()}
        self.objects=copy.deepcopy(request.objects)
    def validate_scene(self,request):
        if {r['instance']['instance']['id'] for r in request.robots}!=set(self.models):raise ValueError('Robot mapping mismatch')
    def observe(self):
        stamp=now()
        return {'states':{rid:s.model_copy(update={'measured_at':stamp}).model_dump() for rid,s in self.states.items()},
            'objects':[o.model_dump() for o in self.objects],'measured_at':stamp,'simulation_time':0.,'faults':[]}
    def reset(self,positions,objects):
        self.resets+=1
        for rid,q in positions.items():self.states[rid].positions=dict(q)
        self.objects=copy.deepcopy(objects);self.stop()
    def advance(self,positions,dt):
        for rid,q in positions.items():self.states[rid].positions=dict(q);self.states[rid].stopped=False
    def sync_objects(self,objects):self.objects=copy.deepcopy(objects)
    def stop(self):
        for s in self.states.values():s.stopped=True
    def inventory(self):return {'assets':[],'scope':'contract_test'}


def connect_factory(backend):
    import httpx
    from simulation.isaac_sim.worker import create_worker
    from robot_system.registry.models.demo_arm.adapters.isaac_sim.adapter import IsaacCell
    token='isolated-contract-test-worker'
    worker=create_worker(backend,token)
    def factory(pid,instances,models,objects):
        client=httpx.AsyncClient(transport=httpx.ASGITransport(app=worker),base_url='http://worker',headers={'Authorization':'Bearer '+token})
        return IsaacCell(pid,instances,models,objects,client=client,require_native=False)
    return factory
