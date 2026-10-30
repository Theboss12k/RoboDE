"""Private process protocol for bounded, injected actuator drivers."""
import importlib
import json
import math
from pathlib import Path
import sys
import time
import threading
from datetime import datetime, timezone

# -I removes ambient user paths. Load only this installation's contracts.
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from services.adapters.drivers import validate_source,DRIVER_CONTRACT
from shared.models.robotics import DriverDraft


class FakeSDK:
    def __init__(self, definition,initial_values=None):
        self.d = definition; self.calls = []; self.values = {f['id']:(initial_values or {}).get(f['id'],(f['minimum']+f['maximum'])/2) for f in definition['functions']}
        self.stopped = True
    def __getattr__(self, name):
        functions = [f for f in self.d['functions'] if f['vendor_method']==name]
        if functions:
            def setter(value):
                self.calls.append({'method':name, 'value':value})
                for f in functions:
                    self.values[f['id']] = value[f['vendor_joint']] if f['write_style']=='joint_vector' else value
                self.stopped = True
                return {'accepted':True}
            return setter
        if name == self.d['feedback_method'] and name:
            return lambda:dict(self.values)
        if name == self.d['stop_method'] and name:
            def stop(): self.stopped=True; return {'stopped':True}
            return stop
        if name == self.d['disconnect_method'] and name: return lambda:None
        raise AttributeError('Undocumented simulated SDK method')


class Worker:
    def __init__(self, body):
        self.b = body['bundle']; self.d = DriverDraft.model_validate(self.b['definition']); self.mode=body['mode']
        tree = validate_source(self.b['source_code'], self.d)
        self.functions = {f.id:f for f in self.d.functions}; self.targets = {}
        if self.mode == 'test': self.client=FakeSDK(self.b['definition'],body.get('initial_values'))
        elif self.mode == 'live':
            if self.b['reviewed_hash'] != self.b['hash'] or not (self.b.get('test_report') or {}).get('passed') or self.b['test_report'].get('contract_version')!=DRIVER_CONTRACT:
                raise ValueError('Reviewed and tested driver required')
            if not self.d.sdk_module: raise ValueError('SDK module must be explicitly configured')
            if not self.d.watchdog_method:raise ValueError('Live SDK requires a documented device watchdog(timeout_seconds) method')
            module=importlib.import_module(self.d.sdk_module)
            self.client=getattr(module,self.d.client_factory)(**body.get('connection',{}))
            getattr(self.client,self.d.watchdog_method)(self.d.watchdog_timeout_seconds)
        else: raise ValueError('Unknown worker mode')
        namespace={'__name__':'reviewed_driver'}
        exec(compile(tree,'<reviewed-driver>','exec'),{'__builtins__':{'__build_class__':__build_class__, 'dict':dict, 'NotImplementedError':NotImplementedError},'__name__':'reviewed_driver'},namespace)
        self.transport=namespace['Transport'](self.client,self.targets)
        if self.mode=='test':
            self.targets.update({method:{f.vendor_joint:self.client.values[f.id] for f in self.d.functions if f.write_style=='joint_vector' and f.vendor_method==method} for method in {f.vendor_method for f in self.d.functions if f.write_style=='joint_vector'}})
        self.last_heartbeat=time.monotonic()
        self.expired=False
        if self.mode=='live':
            measured=self.state()
            self.targets.update({method:{f.vendor_joint:measured['positions'][f.id] for f in self.d.functions if f.write_style=='joint_vector' and f.vendor_method==method} for method in {f.vendor_method for f in self.d.functions if f.write_style=='joint_vector'}})
            threading.Thread(target=self.watchdog,daemon=True).start()
    def watchdog(self):
        while not self.expired:
            if time.monotonic()-self.last_heartbeat>3:
                self.expired=True
                try:self.transport.stop()
                except Exception:pass
                return
            time.sleep(.1)
    def request(self, body):
        if self.expired:raise ValueError('Driver watchdog expired; reconnect and re-arm')
        op=body['operation'];self.last_heartbeat=time.monotonic()
        if self.mode=='live':getattr(self.client,self.d.watchdog_method)(self.d.watchdog_timeout_seconds)
        if op=='command':
            commands=body['commands']
            if not 1<=len(commands)<=128: raise ValueError('A bounded command batch is required')
            if len({c['function'] for c in commands}) != len(commands): raise ValueError('Duplicate actuator command')
            for c in commands:
                f=self.functions.get(c['function']);v=c['value']
                if f is None or isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) or not f.minimum<=v<=f.maximum:
                    raise ValueError('Unknown function or actuator value outside limits')
            trace=len(self.client.calls) if self.mode=='test' else 0
            for c in commands:
                f=self.functions[c['function']]
                if f.write_style=='joint_vector':self.targets[f.vendor_method][f.vendor_joint]=c['value']
            used=set()
            for c in commands:
                f=self.functions[c['function']]
                if f.write_style=='joint_vector' and f.vendor_method in used:continue
                acknowledgement=getattr(self.transport,f.id)(c['value']);used.add(f.vendor_method)
                if acknowledgement is False or isinstance(acknowledgement,dict) and (acknowledgement.get('accepted') is False or acknowledgement.get('success') is False or acknowledgement.get('error')):raise ValueError('Vendor SDK rejected the actuator command')
            result=self.state()
            if self.mode=='test':result.update(sdk_calls=self.client.calls[trace:],observed_values=dict(self.client.values))
            return result
        if op=='trace': return list(self.client.calls) if self.mode=='test' else []
        if op=='stop':self.transport.stop()
        elif op=='disconnect':self.transport.disconnect()
        elif op not in {'state','heartbeat'}:raise ValueError('Unknown driver operation')
        return self.state()
    def state(self):
        positions=self.transport.read_feedback() if self.d.feedback_method else None
        if self.mode=='live':
            if not isinstance(positions,dict) or not {'positions','velocities','stopped','device_id','measured_at'}<=set(positions):raise ValueError('SDK feedback requires measured positions, velocities, stopped, device_id and measured_at')
            result=positions
            if set(result['positions'])!=set(self.functions) or set(result['velocities'])!=set(self.functions):raise ValueError('Measured feedback must cover every declared actuator function')
            if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for key in ('positions','velocities') for v in result[key].values()):raise ValueError('Measured feedback contains invalid values')
            age=(datetime.now(timezone.utc)-datetime.fromisoformat(result['measured_at'].replace('Z','+00:00'))).total_seconds()
            if not -.1<=age<=1 or not isinstance(result['stopped'],bool):raise ValueError('Measured hardware feedback is stale or cannot confirm Stop')
            return {**result,'source':'hardware','connected':True}
        if positions is not None and (not isinstance(positions,dict) or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in positions.values())):
            raise ValueError('Invalid measured SDK feedback')
        return {'positions':positions,'source':'simulation' if self.mode=='test' else 'hardware',
                'measured_at':datetime.now(timezone.utc).isoformat(),'connected':True,
                'stopped':self.client.stopped if self.mode=='test' else None}


def main():
    worker=None
    for line in sys.stdin:
        try:
            data=json.loads(line)
            if worker is None:worker=Worker(data);result=worker.state()
            else:result=worker.request(data)
            print(json.dumps({'ok':True,'result':result},allow_nan=False),flush=True)
        except Exception as error:print(json.dumps({'ok':False,'error':str(error)}),flush=True)

if __name__=='__main__':main()
