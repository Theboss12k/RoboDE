"""Line-oriented adapter process. Generated SDK drafts are never imported here.
Only the bounded, reviewed translation expression runs with a simulated or
explicitly selected ROS bridge transport. This is a process boundary, not a
sandbox for executing arbitrary SDK source.
"""
import ast
import json
import math
import sys
import time
import uuid
import urllib.request


def translator(source):
    tree = ast.parse(source)
    allowed = (ast.Module,ast.FunctionDef,ast.arguments,ast.arg,ast.Return,ast.Dict,ast.Constant,
               ast.Subscript,ast.Name,ast.Load,ast.BinOp,ast.Mult,ast.Div,ast.UnaryOp,ast.USub)
    if len(tree.body) != 1 or not isinstance(tree.body[0],ast.FunctionDef) or tree.body[0].name != 'translate':
        raise ValueError('Only a bounded translate function is supported')
    if any(not isinstance(n,allowed) for n in ast.walk(tree)):
        raise ValueError('Unsupported generated translation expression')
    if any(isinstance(n,ast.Name) and n.id != 'positions' for n in ast.walk(tree)):
        raise ValueError('Translation can only read actuator positions')
    namespace = {}
    exec(compile(tree,'<translation>','exec'),{'__builtins__':{}},namespace)
    return namespace['translate']


ADAPTER_CLASS = """class Adapter:
    def __init__(self, transport):
        self.transport = transport

    def command(self, positions):
        return self.transport.command(translate(positions))

    def get_state(self):
        return self.transport.get_state()

    def request_stop(self):
        return self.transport.stop()
"""


def adapter_class(source):
    tree = ast.parse(source)
    if len(tree.body) != 2 or ast.dump(tree.body[1]) != ast.dump(ast.parse(ADAPTER_CLASS).body[0]):
        raise ValueError('Only the generated injectable adapter interface is executable')
    translate = translator(ast.unparse(tree.body[0]))
    namespace = {'__builtins__':{'__build_class__':__build_class__},'__name__':'generated_adapter','translate':translate}
    exec(compile(ADAPTER_CLASS,'<adapter-template>','exec'),namespace)
    return namespace['Adapter']


class SimulatedTransport:
    def __init__(self,bundle):
        self.bundle,self.positions = bundle,bundle['initial']
        self.last_command = None

    def command(self,translated):
        self.last_command = translated
        self.positions = {key:translated[remote]/self.bundle['scales'][key] for key,remote in self.bundle['joint_mapping'].items()}
        return self.get_state()

    def get_state(self):
        return self.positions

    def stop(self):
        return True


class Worker:
    def __init__(self, bundle, mode, token=''):
        self.bundle,self.mode,self.token = bundle,mode,token
        self.session_id = uuid.uuid4().hex
        self.translate = translator(bundle['translation'])
        self.positions = bundle['initial']
        self.stopped = True
        self.mapping = bundle['joint_mapping']
        self.config = bundle['connection']
        self.transport = SimulatedTransport(bundle)
        self.adapter = adapter_class(bundle['adapter_code'])(self.transport)

    def bridge(self, operation, body=None):
        url = self.config.get('bridge_url','').rstrip('/') + '/v1/' + operation
        req = urllib.request.Request(url,data=json.dumps(body or {}).encode(),headers={
            'Content-Type':'application/json','Authorization':'Bearer '+self.token,'X-Control-Session':self.session_id},method='POST')
        with urllib.request.urlopen(req,timeout=5) as response:
            result = json.load(response)
        observed = result['positions']
        self.positions = {joint:observed[remote]/self.bundle['scales'][joint] for joint,remote in self.mapping.items()}
        self.stopped = result.get('stopped') is True
        return {'positions':self.positions,'stopped':self.stopped,'connected':True,
                'measured_at':result['measured_at'],'source':'hardware','device_id':result['device_id'],
                'ready':result.get('ready',False),'stop_supported':result.get('stop_supported',False)}

    def request(self, data):
        op = data['operation']
        if op == 'command':
            q = data['positions']
            if set(q) != set(self.bundle['controls']):
                raise ValueError('Every actuator must be supplied exactly once')
            for key,value in q.items():
                a = self.bundle['controls'][key]
                if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not a['min'] <= value <= a['max']:
                    raise ValueError('Invalid actuator value: '+key)
            translated = self.translate(q)
            if self.mode == 'live':
                result = self.bridge('command',{'positions':translated,'duration':data.get('duration',1)})
            else:
                # Injected fake transport records the actual translated command,
                # then returns independently decoded transport feedback.
                self.adapter.command(q)
                self.positions,self.stopped = self.adapter.get_state(),True
                translated = self.transport.last_command
                result = self.state()
            result['translated_command'] = translated
            return result
        if self.mode == 'live':
            return self.bridge(op if op in {'stop','disconnect'} else 'state')
        if op == 'stop':
            self.stopped = self.adapter.request_stop() is True
        return self.state()

    def state(self):
        from datetime import datetime, timezone
        return {'positions':self.positions,'stopped':self.stopped,'connected':True,'source':'simulation',
                'measured_at':datetime.now(timezone.utc).isoformat(),'transport':'injected_simulated_transport',
                **({'translated_command':self.transport.last_command} if self.transport.last_command is not None else {})}


def main():
    worker = None
    for line in sys.stdin:
        try:
            data = json.loads(line)
            if worker is None:
                worker = Worker(data['bundle'],data['mode'],data.get('token',''))
                result = worker.request({'operation':'state'})
            else:
                result = worker.request(data)
            print(json.dumps({'result':result},allow_nan=False),flush=True)
        except Exception as error:
            print(json.dumps({'error':str(error)}),flush=True)

if __name__ == '__main__':
    main()
