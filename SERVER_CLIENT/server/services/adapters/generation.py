"""Versioned adapter bundles, review evidence and transport contract testing."""
import ast
import asyncio
from services.commands.standard import capability_description
from services.ai_orchestrator.llm import json_answer
import hashlib
import json
import math
import os
import sys
import uuid
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
import re
import httpx
from pydantic import Field
from shared.models.domain import Contract, now
from services.adapters.commands import AdapterCommand, validate_catalog, default_commands
from services.api.storage import atomic_json, safe_id
from services.validation.registry import MODEL_ROOT, load_model

WORKER = Path(__file__).with_name('worker.py')


def sdk_source_answer(answer):
    source = answer.strip()
    if source.startswith('```'):
        # A local model may append a review explanation after its one code block.
        # Keep only the explicitly fenced Python, never evaluate surrounding text.
        match = re.fullmatch(r'```(?:python|py)?\s*\n([\s\S]*?)\n```([^`]*)', source, re.IGNORECASE)
        if not match:
            raise ValueError('SDK provider returned an incomplete or ambiguous Python draft')
        source = match[1]
    try:
        ast.parse(source)
    except SyntaxError as error:
        raise ValueError('SDK provider returned invalid Python; no draft was activated') from error
    return source


class GenerateAdapter(Contract):
    model_id: str
    name: str = Field(min_length=1,max_length=100)
    kind: Literal['sdk','ros2','mock','isaac_sim']
    target: Literal['physical','virtual'] | None = None
    configuration_method: Literal['documentation','custom','template'] = 'template'
    commands: list[AdapterCommand] | None = Field(default=None,max_length=64)
    llm_adapter_id: str | None = None
    sdk_version: str = Field(default='',max_length=100)
    documentation: str = Field(default='',max_length=60000)
    joint_mapping: dict[str,str] = Field(default_factory=dict)
    remote_units: dict[str,str] = Field(default_factory=dict)
    connection: dict[str,str] = Field(default_factory=dict)


def bundle_hash(bundle):
    payload={k:bundle[k] for k in ('translation','adapter_code','sdk_source','joint_mapping','scales','connection','controls','kind','model_id','model_version','initial','sdk_version','documentation','provenance','control_schemes')}
    for key in ('commands','configuration_method','standard_contract'):
        if key in bundle: payload[key]=bundle[key]
    return hashlib.sha256(json.dumps(payload,sort_keys=True).encode()).hexdigest()


class AdapterProcess:
    def __init__(self):
        self.process = None
        self.lock = asyncio.Lock()

    async def start(self,bundle,mode='test',token=''):
        self.process = await asyncio.create_subprocess_exec(sys.executable,'-I','-u',str(WORKER),
            stdin=asyncio.subprocess.PIPE,stdout=asyncio.subprocess.PIPE,stderr=asyncio.subprocess.DEVNULL,
            env={k:v for k,v in os.environ.items() if k in {'PATH','SYSTEMROOT','TMPDIR','TEMP','TMP','LANG'}})
        return await self.request({'bundle':bundle,'mode':mode,'token':token})

    async def request(self,body):
        async with self.lock:
            if not self.process or self.process.returncode is not None:
                raise ValueError('Adapter worker disconnected')
            self.process.stdin.write((json.dumps(body,allow_nan=False)+'\n').encode())
            await self.process.stdin.drain()
            line = await asyncio.wait_for(self.process.stdout.readline(),7)
            if not line:
                raise ValueError('Adapter worker disconnected')
            result = json.loads(line)
            if 'error' in result:
                raise ValueError(result['error'])
            return result['result']

    async def close(self):
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try:
                await asyncio.wait_for(self.process.wait(),2)
            except TimeoutError:
                self.process.kill()
                await self.process.wait()


class AdapterRegistry:
    def __init__(self,store):
        self.store = store
        self.root = store.runtime/'adapter_drafts'
        self.active = store.runtime/'adapters'

    def path(self,key):
        return self.root/safe_id(key)/'bundle.json'

    def get(self,key):
        result = json.loads(self.path(key).read_text())
        if result['hash'] != bundle_hash(result):
            raise ValueError('Adapter contents changed; generate and review a new revision')
        model = load_model(self.store.model_folder(result['model_id']))
        if result['controls'] != model['actuators']['actuators'] or result['model_version'] != model['robot']['version'] or ('standard_contract' in result and result['standard_contract']!=capability_description(model)):
            raise ValueError('Robot model changed; generate and validate a new adapter')
        return result

    def save(self,bundle):
        atomic_json(self.path(bundle['id']),bundle)

    def list(self,model_id):
        result=[]
        for path in sorted(self.root.glob('*/bundle.json'),key=lambda p:p.stat().st_mtime,reverse=True):
            bundle=json.loads(path.read_text())
            if bundle.get('internal') or bundle['model_id']!=model_id:
                continue
            try:
                result.append(self.get(bundle['id']))
            except ValueError:
                result.append({**bundle,'validation_status':'stale','live_eligible':False,'reviewed_hash':None,'test_report':None})
        return result

    async def discover(self,data,initial):
        if not data.documentation.strip() or not data.sdk_version.strip():
            raise ValueError('Provide vendor documentation and its SDK/API version')
        from services.ai_orchestrator.llm import LLMRegistry
        model=load_model(self.store.model_folder(data.model_id))
        schema=AdapterCommand.model_json_schema()
        response=await LLMRegistry(self.store).adapter(data.llm_adapter_id)(json.dumps({'documentation':data.documentation,'version':data.sdk_version,
            'actuators':model['actuators']['actuators'],'initial':initial}),
            'Extract documented robot commands. Include an exact supporting documentation_quote for every command. Return JSON only: {"commands":[...]}. Each entry follows this schema: '+json.dumps(schema)+
            '. Use canonical model units. Bind each command to its vendor function/signature in vendor_command. Simulator recipes may only use move, increment, gripper, wait, feedback, stop; values are numbers or $parameter references. '
            'Only map an API when its documented meaning is clear. Do not invent names, semantics, robot geometry or sensor data. Unsupported operations must have simulation_supported=false, empty steps and an unsupported_reason. '
            'Use task terminology in user-facing names and descriptions. Provide valid defaults within joint limits. Every parameter must be used in its recipe. Return at most 32 commands.')
        try:
            raw=json_answer(response['answer'])
            commands=[AdapterCommand.model_validate(c) for c in raw['commands']]
        except (ValueError,KeyError,TypeError) as error:
            raise ValueError('Provider returned an invalid command catalog; no adapter was created') from error
        document=' '.join(data.documentation.split())
        for command in commands:
            quote=' '.join(command.documentation_quote.split())
            function=re.search(r'[A-Za-z_][A-Za-z0-9_.]*',command.vendor_command)
            if command.simulation_supported and (not quote or quote not in document or not function or function[0].split('.')[-1] not in data.documentation):
                command.simulation_supported=False;command.steps=[]
                command.unsupported_reason='The provider did not supply a verifiable vendor function and documentation quote. Define an explicit custom simulator recipe after checking the API.'
        validate_catalog(commands,model['actuators']['actuators'],initial)
        return commands

    async def generate(self,data,initial):
        model = load_model(self.store.model_folder(data.model_id))
        actuators = model['actuators']['actuators']
        category='physical' if data.kind in {'sdk','ros2'} else 'virtual'
        if data.target and data.target!=category:
            raise ValueError('Adapter transport does not match the selected physical/virtual target')
        commands=data.commands
        if commands is None:
            commands=await self.discover(data,initial) if data.configuration_method=='documentation' else default_commands(actuators,initial)
        # Standard controls remain discoverable alongside custom/vendor commands.
        ids={c.id for c in commands}
        commands=[*commands,*[c for c in default_commands(actuators,initial) if c.id not in ids]]
        validate_catalog(commands,actuators,initial)
        mapping = data.joint_mapping or {k:k for k in actuators}
        if set(mapping) != set(actuators) or len(set(mapping.values())) != len(mapping) or any(not n.strip() or len(n)>120 for n in mapping.values()):
            raise ValueError('Map every actuator to one unique SDK/controller joint')
        if data.kind == 'ros2':
            parsed = urlparse(data.connection.get('bridge_url',''))
            if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password:
                raise ValueError('Provide an HTTP(S) bridge URL without embedded credentials')
            if not re.fullmatch(r'[A-Z][A-Z0-9_]{0,79}',data.connection.get('token_env','ROS_BRIDGE_TOKEN')):
                raise ValueError('Use an environment variable name for the bridge token')
        if not set(data.remote_units).issubset(actuators):
            raise ValueError('Remote units reference an unknown actuator')
        scales = {}
        for key,a in actuators.items():
            remote_unit = data.remote_units.get(key,a['unit'])
            if (a['unit'],remote_unit) not in {('rad','rad'),('rad','deg'),('m','m'),('m','mm')}:
                raise ValueError('Supported remote units: rad/deg for rotation, m/mm for linear joints')
            if data.kind == 'ros2' and remote_unit != a['unit']:
                raise ValueError('ROS 2 controllers use rad/m; configure SDK units only for SDK adapters')
            scales[key] = 180/math.pi if remote_unit == 'deg' else 1000 if remote_unit == 'mm' else 1
        if any(k.lower() in {'password','token','api_key','secret'} for k in data.connection):
            raise ValueError('Store credentials in environment variables, not adapter metadata')
        translation = 'def translate(positions):\n    return {\n'+''.join(f'        {mapping[k]!r}: positions[{k!r}] * {scales[k]!r},\n' for k in actuators)+'    }\n'
        code = translation+'\nclass Adapter:\n    def __init__(self, transport):\n        self.transport = transport\n\n    def command(self, positions):\n        return self.transport.command(translate(positions))\n\n    def get_state(self):\n        return self.transport.get_state()\n\n    def request_stop(self):\n        return self.transport.stop()\n'
        sdk_source = ''
        llm_provenance = {}
        if data.kind == 'sdk' and data.configuration_method!='custom':
            if not data.documentation.strip() or not data.sdk_version.strip():
                raise ValueError('Provide SDK version and documentation before generating a custom SDK draft')
            from services.ai_orchestrator.llm import LLMRegistry
            response = await LLMRegistry(self.store).adapter(data.llm_adapter_id)(json.dumps({'sdk_version':data.sdk_version,'joint_mapping':mapping,'documentation':data.documentation}),
                'Draft a Python SDK transport for human review only. Return exactly one Python class named Transport with methods __init__(self, client), command(self, mapped_positions), get_state(self), stop(self), disconnect(self). '
                'The client is injected: do not connect, print, fabricate feedback, create a fake SDK/client or include example usage. Delegate only to the documented SDK client methods. '
                'command receives a complete joint-name-to-position dictionary. If the documented SDK cannot command that joint set, raise NotImplementedError rather than pretending success. '
                'get_state returns documented measured feedback; missing feedback must raise NotImplementedError, never return placeholder numbers or None positions. '
                'No task planning or automatic motion. Mark every missing vendor API detail with NotImplementedError; never invent API names. '
                'Return Python source only, without Markdown or explanation. This draft will not be executed by the IDE.')
            sdk_source = response['answer']
            llm_provenance = {k:response[k] for k in ('adapter_id','adapter_version','model')}
            if not isinstance(sdk_source,str) or len(sdk_source)>120000:
                raise ValueError('SDK draft response was invalid or too large')
            sdk_source = sdk_source_answer(sdk_source)
        bundle = {'id':uuid.uuid4().hex[:12],'name':data.name.strip(),'model_id':data.model_id,'model_version':model['robot']['version'],
            'kind':data.kind,'category':category,'controls':actuators,
            'standard_contract':capability_description(model),
            'configuration_method':data.configuration_method,'commands':[c.model_dump() for c in commands],'command_tests':[],
            'control_schemes':['joint_position','trajectory_execution'],'joint_mapping':mapping,'scales':scales,
            'connection':data.connection,'initial':initial,'translation':translation,'adapter_code':code,'sdk_source':sdk_source,
            'documentation':data.documentation,'sdk_version':data.sdk_version,'created_at':now(),'reviewed_hash':None,'test_report':None,
            'validation_status':'draft','live_eligible':False,
            'provenance':{'generator':'custom_commands' if data.configuration_method=='custom' else 'template+ai' if data.kind=='sdk' or data.configuration_method=='documentation' else 'template','template_version':'1.0.0','ai_model':llm_provenance.get('model'),'llm_adapter':llm_provenance or None,'command_source':'custom_recipes' if data.configuration_method=='custom' else 'provided_documentation_recipes' if data.commands is not None else 'documentation_ai' if data.configuration_method=='documentation' else 'tested_templates'},
            'contract_tests':"""import unittest
from adapter import Adapter

class FakeTransport:
    def command(self, positions):
        self.sent = positions
        return positions
    def get_state(self):
        return self.sent
    def stop(self):
        return True

class AdapterContract(unittest.TestCase):
    def test_injected_transport(self):
        transport = FakeTransport()
        adapter = Adapter(transport)
        positions = INITIAL
        adapter.command(positions)
        self.assertEqual(set(transport.sent), set(EXPECTED_JOINTS))
        self.assertEqual(adapter.get_state(), transport.sent)
        self.assertTrue(adapter.request_stop())

if __name__ == '__main__':
    unittest.main()
""".replace('INITIAL',repr(initial)).replace('EXPECTED_JOINTS',repr(list(mapping.values())))}
        bundle['hash'] = bundle_hash(bundle)
        self.save(bundle)
        folder=self.path(bundle['id']).parent
        (folder/'adapter.py').write_text(bundle['adapter_code'])
        (folder/'test_adapter.py').write_text(bundle['contract_tests'])
        if sdk_source:
            (folder/'sdk_transport.draft.py').write_text(sdk_source)
        atomic_json(folder/'controls.json',bundle['controls'])
        atomic_json(folder/'commands.json',bundle['commands'])
        atomic_json(folder/'standard_contract.json',bundle['standard_contract'])
        return bundle

    def record_command_test(self,key,report):
        bundle=self.get(key)
        bundle['command_tests']=(bundle.get('command_tests',[])+[report])[-100:]
        self.save(bundle)

    def review(self,key,expected_hash):
        bundle = self.get(key)
        if expected_hash != bundle['hash']:
            raise ValueError('Adapter changed since review')
        bundle['reviewed_hash'] = expected_hash
        bundle['validation_status'] = 'reviewed'
        self.save(bundle)
        return bundle

    async def test(self,key):
        bundle = self.get(key)
        process = AdapterProcess()
        results = []
        try:
            validate_catalog([AdapterCommand.model_validate(c) for c in bundle.get('commands',[])],bundle['controls'],bundle['initial']) if bundle.get('commands') else None
            state = await process.start(bundle)
            q = {k:(a['min']+a['max'])/2 for k,a in bundle['controls'].items()}
            observed = await process.request({'operation':'command','positions':q})
            if any(abs(observed['positions'][k]-v)>1e-9 for k,v in q.items()) or observed['source'] != 'simulation':
                raise ValueError('Mapping round-trip or simulated feedback failed')
            results.append('Joint mappings, units, simulated transport feedback')
            for invalid in [{**q,next(iter(q)):bundle['controls'][next(iter(q))]['max']+1},dict(list(q.items())[1:]),{**q,next(iter(q)):True}]:
                try:
                    await process.request({'operation':'command','positions':invalid})
                except ValueError:
                    continue
                raise ValueError('Adapter accepted an invalid command')
            results.append('Limits, complete joint set and invalid number rejection')
            stopped = await process.request({'operation':'stop'})
            if not stopped['stopped']:
                raise ValueError('Stop did not confirm')
            results.append('Stop request and feedback confirmation')
            if bundle.get('commands'): results.append('Command catalog schemas, parameter units, defaults and bounded recipes')
            bundle['test_report'] = {'passed':True,'hash':bundle['hash'],'tested_at':now(),'checks':results,'scope':'simulated_transport_only','hardware_validated':False}
            bundle['validation_status'] = 'tested' if bundle['reviewed_hash'] == bundle['hash'] else 'tested_unreviewed'
            if bundle['reviewed_hash'] == bundle['hash']:
                atomic_json(self.active/(bundle['id']+'.json'),{'id':bundle['id'],'hash':bundle['hash'],'scope':'test_only'})
            self.save(bundle)
            return bundle
        finally:
            await process.close()
