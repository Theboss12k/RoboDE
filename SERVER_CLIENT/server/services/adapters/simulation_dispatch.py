"""Execute reviewed generated driver code with simulated SDKs during plan playback."""
from services.adapters.drivers import DriverRegistry,DriverProcess
from services.validation.registry import validate_positions

class SimulatedDispatch:
    def __init__(self,store,llm,models):self.registry=DriverRegistry(store,llm);self.models=models;self.workers={};self.previous={};self.previous_time=None
    async def open(self,states):
        try:
            for rid,model in self.models.items():
                binding=model.get('binding')
                if not binding:continue
                driver=self.registry.get(binding['definition']['driver_id'])
                if driver['hash']!=binding['driver_hash'] or not binding['published']:raise ValueError('Simulation driver binding changed')
                q=dict(states[rid].positions);functions={f['id']:f for f in driver['definition']['functions']}
                initial={j['function_id']:q[j['joint_id']]*j['scale']+j['offset'] if functions[j['function_id']]['mode']=='position' else 0. for j in binding['definition']['joints'] if j['role']=='independent'}
                process=DriverProcess();self.workers[rid]=(process,binding,functions);await process.start(driver,initial_values=initial);self.previous[rid]=q
        except BaseException:await self.close();raise
    async def dispatch(self,frame):
        positions={rid:dict(q) for rid,q in frame.robot_positions.items()};dt=0. if self.previous_time is None else frame.time-self.previous_time
        for rid,(process,binding,functions) in self.workers.items():
            commands=[]
            for j in binding['definition']['joints']:
                if j['role']!='independent':continue
                f=functions[j['function_id']];q=positions[rid][j['joint_id']]
                value=q*j['scale']+j['offset'] if f['mode']=='position' else ((q-self.previous[rid][j['joint_id']])/dt*j['scale'] if dt else 0.)
                commands.append({'function':f['id'],'value':value})
            observed=await process.request({'operation':'command','commands':commands})
            if observed['source']!='simulation':raise ValueError('Simulation cannot accept hardware transport feedback')
            for j in binding['definition']['joints']:
                if j['role']!='independent':continue
                f=functions[j['function_id']];value=observed['observed_values'][f['id']]
                positions[rid][j['joint_id']]=(value-j['offset'])/j['scale'] if f['mode']=='position' else self.previous[rid][j['joint_id']]+value/j['scale']*dt
            for _ in binding['definition']['joints']:
                for j in binding['definition']['joints']:
                    if j['role']=='coupled':positions[rid][j['joint_id']]=positions[rid][j['coupled_to']]*j['multiplier']+j['offset']
            validate_positions(self.models[rid],positions[rid]);self.previous[rid]=dict(positions[rid])
            if any(abs(positions[rid][key]-value)>1e-6 for key,value in frame.robot_positions[rid].items()):raise ValueError('Generated adapter translation does not match the validated trajectory')
        self.previous_time=frame.time
        return frame.model_copy(update={'robot_positions':positions})
    async def close(self):
        confirmed=True
        for process,_,_ in self.workers.values():
            try:confirmed=bool((await process.request({'operation':'stop'})).get('stopped')) and confirmed
            except Exception:confirmed=False
            await process.close()
        self.workers={}
        return confirmed
