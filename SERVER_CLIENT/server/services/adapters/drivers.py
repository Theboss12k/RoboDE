"""Model-independent driver drafts and reviewed executable actuator transports.

Generated source has a deliberately small Python grammar. Vendor imports and
connections are owned by the worker, never by generated source. Test clients
have no device, socket or filesystem interface.
"""
import ast
import asyncio
import hashlib
import json
import re
import sys
import uuid
from pathlib import Path
from shared.models.robotics import DriverDraft
from shared.models.domain import now
from services.api.storage import atomic_json, safe_id, fingerprint
from services.ai_orchestrator.llm import json_answer


DRIVER_CONTRACT="bounded-sdk-v2.1"

def source_for(data):
    lines = ['class Transport:', '    def __init__(self, client, setpoints):', '        self.client = client', '        self.setpoints = setpoints']
    for f in data.functions:
        lines += [f'    def {f.id}(self, value):']
        if f.write_style == 'joint_vector':
            lines += [f'        self.setpoints[{f.vendor_method!r}][{f.vendor_joint!r}] = value', f'        return self.client.{f.vendor_method}(dict(self.setpoints[{f.vendor_method!r}]))']
        else:
            lines += [f'        return self.client.{f.vendor_method}(value)']
    for name, method in [('read_feedback', data.feedback_method), ('stop', data.stop_method), ('disconnect', data.disconnect_method)]:
        lines += [f'    def {name}(self):', f'        return self.client.{method}()' if method else '        raise NotImplementedError("Vendor method is not documented")']
    return '\n'.join(lines)+'\n'


def validate_source(source, data):
    tree = ast.parse(source)
    allowed = (ast.Module, ast.ClassDef, ast.FunctionDef, ast.arguments, ast.arg, ast.Assign, ast.Return,
               ast.Expr, ast.Call, ast.Attribute, ast.Name, ast.Load, ast.Store, ast.Subscript, ast.Constant,
               ast.Dict, ast.Raise, ast.Pass)
    if any(not isinstance(n, allowed) for n in ast.walk(tree)):
        raise ValueError('Driver source must use the bounded Transport class interface; imports, loops and arbitrary expressions are unavailable')
    if len(tree.body) != 1 or not isinstance(tree.body[0], ast.ClassDef) or tree.body[0].name != 'Transport' or tree.body[0].bases or tree.body[0].decorator_list:
        raise ValueError('Define exactly one Transport class')
    methods = {n.name:n for n in tree.body[0].body if isinstance(n, ast.FunctionDef)}
    expected = {'__init__', 'read_feedback', 'stop', 'disconnect', *[f.id for f in data.functions]}
    if set(methods) != expected or len(methods) != len(tree.body[0].body):
        raise ValueError('Transport must define the declared actuator functions, __init__, read_feedback, stop and disconnect')
    vendor = {f.vendor_method for f in data.functions} | {data.feedback_method, data.stop_method, data.disconnect_method}
    for name, node in methods.items():
        args = [a.arg for a in node.args.args]
        wanted = ['self', 'client', 'setpoints'] if name == '__init__' else ['self', 'value'] if name not in {'read_feedback', 'stop', 'disconnect'} else ['self']
        if args != wanted or node.decorator_list or node.args.defaults or node.args.kwarg or node.args.vararg or node.args.kwonlyargs or node.args.posonlyargs:
            raise ValueError('Driver method signatures must match their declared contract')
        for n in ast.walk(node):
            if isinstance(n, ast.Name) and n.id not in {'self', 'client', 'setpoints', 'value', 'dict', 'NotImplementedError'}:
                raise ValueError('Driver source references an undeclared variable')
            if isinstance(n, ast.Attribute):
                if isinstance(n.value, ast.Name) and n.value.id == 'self' and n.attr in {'client', 'setpoints'}:
                    continue
                if isinstance(n.value, ast.Attribute) and ast.unparse(n.value) == 'self.client' and n.attr in vendor and n.attr:
                    continue
                raise ValueError('Driver source references an undocumented client attribute')
            if isinstance(n, ast.Call):
                if isinstance(n.func, ast.Name) and n.func.id not in {'dict', 'NotImplementedError'}:
                    raise ValueError('Undeclared driver call')
                if name == '__init__':
                    raise ValueError('Constructors cannot connect or command devices')
    if any(not isinstance(n, ast.Assign) for n in methods['__init__'].body):
        raise ValueError('Constructors only store the injected client and setpoints')
    canonical=ast.parse(source_for(data)).body[0]
    for method in canonical.body:
        if method.name=='__init__' and ast.dump(method,include_attributes=False)!=ast.dump(methods[method.name],include_attributes=False):
            raise ValueError('Constructor must retain the injected client and setpoints unchanged')
        allowed_method=next((f.vendor_method for f in data.functions if f.id==method.name),
            {'read_feedback':data.feedback_method,'stop':data.stop_method,'disconnect':data.disconnect_method}.get(method.name))
        for node in ast.walk(methods[method.name]):
            if isinstance(node,ast.Attribute) and isinstance(node.value,ast.Attribute) and node.attr!=allowed_method:
                raise ValueError('Each driver function may call only its documented vendor method')
    return tree


def validate_documented(data):
    ids = [f.id for f in data.functions]
    if not ids or len(set(ids)) != len(ids) or set(ids) & {'__init__', 'read_feedback', 'stop', 'disconnect'}:
        raise ValueError('Declare unique actuator function IDs')
    doc = ' '.join(data.documentation.split())
    for f in data.functions:
        if ' '.join(f.documentation_quote.split()) not in doc or f.vendor_method not in f.documentation_quote:
            raise ValueError(f'{f.id}: include an exact documentation quote naming the vendor method')
        numbers={float(value) for value in re.findall(r'(?<![A-Za-z0-9_])[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?',f.documentation_quote)}
        if f.minimum not in numbers or f.maximum not in numbers:raise ValueError(f'{f.id}: the documentation quote must substantiate both numeric limits; do not invent missing SDK ranges')
        if f.write_style == 'joint_vector' and not f.vendor_joint:
            raise ValueError('Joint-vector functions require an explicit vendor joint name')
        peers=[p for p in data.functions if p.vendor_method==f.vendor_method]
        if len(peers)>1 and (any(p.write_style!='joint_vector' for p in peers) or len({p.vendor_joint for p in peers})!=len(peers)):
            raise ValueError('Shared SDK setters require distinct explicit joint-vector mappings')
    for method in (data.feedback_method, data.stop_method, data.disconnect_method,data.watchdog_method):
        if method and method not in data.documentation:
            raise ValueError('Connection, feedback and stop methods must be documented')


class IncompleteDriver(ValueError):
    """A failed generation whose valid parts are kept as an editable draft."""
    def __init__(self, message, draft, issues, failure_id, provenance):
        super().__init__(message)
        self.draft, self.issues, self.failure_id, self.provenance = draft, issues, failure_id, provenance


FUNCTION_FIELDS = ('id','vendor_method','argument','mode','unit','minimum','maximum','documentation_quote','write_style','vendor_joint')


def salvage(answer, name, category, sdk_version, documentation):
    """Keep what the model got right and report the rest as field-level issues.

    Virtual transports get their internal defaults; physical SDK modules and factories stay
    unresolved until the user supplies them. Nothing is invented."""
    from pydantic import ValidationError
    from shared.models.robotics import ActuatorFunction
    issues = []
    try:
        raw = json_answer(answer)
    except (ValueError, TypeError):
        raw = {}
        issues.append({'field':'answer','message':'The AI model did not return readable JSON. Add functions in the table or generate again.'})
    raw = raw if isinstance(raw, dict) else {}
    if raw.get('error'):
        issues.append({'field':'answer','message':str(raw['error'])[:500]})
    functions = []
    for i, item in enumerate((raw.get('functions') if isinstance(raw.get('functions'), list) else [])[:128]):
        if not isinstance(item, dict):
            continue
        row = {k: item[k] for k in FUNCTION_FIELDS if item.get(k) not in (None, '')}
        try:
            function = ActuatorFunction.model_validate(row)
            validate_documented(DriverDraft(name=name, category=category, sdk_version=sdk_version, documentation=documentation, functions=[function]))
            row = {**function.model_dump(), 'valid': True}
        except ValueError as error:
            row['valid'] = False
            details = error.errors() if isinstance(error, ValidationError) else [{'loc': (), 'msg': str(error)}]
            issues += [{'field':f"functions[{i}]"+''.join('.'+str(x) for x in e['loc']),'message':e['msg']} for e in details]
        functions.append(row)
    if not functions:
        issues.append({'field':'functions','message':'No actuator functions were recognised. Add them in the table.'})
    draft = {'name':name,'category':category,'sdk_version':sdk_version,'documentation':documentation,'functions':functions}
    for key in ('feedback_method','stop_method','disconnect_method','watchdog_method'):
        value = raw.get(key) if isinstance(raw.get(key), str) else ''
        if value and (not re.fullmatch(r'[a-zA-Z][a-zA-Z0-9_]*', value) or value not in documentation):
            issues.append({'field':key,'message':f'{value} is not a documented method; correct it or leave it empty'})
            value = ''
        draft[key] = value
    for key, pattern in (('sdk_module', r'[a-zA-Z][a-zA-Z0-9_.]*'), ('client_factory', r'[a-zA-Z][a-zA-Z0-9_]*')):
        value = raw.get(key) if isinstance(raw.get(key), str) and re.fullmatch(pattern, raw[key]) else ''
        if not value and category == 'physical':
            issues.append({'field':key,'message':'Required to connect physical hardware. Supply it from the vendor SDK documentation.'})
        draft[key] = value or ('Client' if key == 'client_factory' and category == 'virtual' else '')
    return draft, issues


def driver_hash(bundle):
    return fingerprint({k:bundle[k] for k in ('definition', 'source_code', 'version')})


class DriverProcess:
    def __init__(self):
        self.process = None
        self.lock = asyncio.Lock()

    async def start(self, bundle, mode='test', connection=None, initial_values=None):
        import os
        self.process = await asyncio.create_subprocess_exec(sys.executable, '-I', '-u', str(Path(__file__).with_name('driver_worker.py')),
            stdin=asyncio.subprocess.PIPE, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL,
            env={k:v for k,v in os.environ.items() if k in {'PATH','SYSTEMROOT','TEMP','TMP','TMPDIR','LANG'}})
        try:
            return await self.request({'bundle':bundle, 'mode':mode, 'connection':connection or {},'initial_values':initial_values or {}})
        except BaseException:
            await self.close()
            raise

    async def request(self, body):
        async with self.lock:
            if not self.process or self.process.returncode is not None:
                raise ValueError('Driver worker disconnected')
            self.process.stdin.write((json.dumps(body, allow_nan=False)+'\n').encode()); await self.process.stdin.drain()
            line = await asyncio.wait_for(self.process.stdout.readline(), 8)
            if not line: raise ValueError('Driver worker disconnected')
            result = json.loads(line)
            if not result.get('ok'): raise ValueError(result.get('error', 'Driver worker failed'))
            return result['result']

    async def close(self):
        if self.process and self.process.returncode is None:
            self.process.terminate()
            try: await asyncio.wait_for(self.process.wait(), 2)
            except TimeoutError: self.process.kill(); await self.process.wait()


class DriverRegistry:
    def __init__(self, store, llm):
        self.store, self.llm = store, llm
        self.root = store.runtime/'drivers'

    def path(self, driver_id): return self.root/safe_id(driver_id)/'driver.json'

    def get(self, driver_id):
        b = json.loads(self.path(driver_id).read_text())
        if b['hash'] != driver_hash(b): raise ValueError('Driver contents changed; review and retest')
        return b

    def get_revision(self,driver_id,digest):
        current=self.get(driver_id)
        if current['hash']==digest:return current
        value=json.loads((self.root/safe_id(driver_id)/'revisions'/(safe_id(digest)+'.json')).read_text())
        if value['hash']!=driver_hash(value) or value['hash']!=digest:raise ValueError('Historical driver checksum differs')
        return value

    def list(self): return [self.get(p.parent.name) for p in sorted(self.root.glob('*/driver.json'))]

    def save(self, data, driver_id=None):
        validate_documented(data)
        source = data.source_code.strip() or source_for(data)
        validate_source(source, data)
        old = self.get(driver_id) if driver_id else None
        if old:atomic_json(self.root/safe_id(driver_id)/'revisions'/(old['hash']+'.json'),old)
        value = {'schema_version':2,'id':driver_id or uuid.uuid4().hex[:12], 'version':old['version']+1 if old else 1,
                 'definition':data.model_dump(exclude={'source_code'}), 'source_code':source, 'created_at':now(),
                 'reviewed_hash':None,'test_report':None,'hardware_validations':[],'status':'draft'}
        value['hash'] = driver_hash(value); atomic_json(self.path(value['id']), value)
        return value

    async def generate(self, name, category, sdk_version, documentation, adapter_id=None):
        system=('Extract executable actuator metadata from the supplied SDK documentation. Return a JSON INSTANCE, never a JSON Schema. '
            'The output shape is {"functions":[{"id":"lowercase_name","vendor_method":"documented_method","argument":"value",'
            '"mode":"position","unit":"rad","minimum":-1.0,"maximum":1.0,'
            '"documentation_quote":"exact supporting documentation text","write_style":"single","vendor_joint":""}],'
            '"sdk_module":"documented Python module or empty string","client_factory":"documented factory or Client",'
            '"feedback_method":"documented method or empty string","stop_method":"documented method or empty string",'
            '"disconnect_method":"documented method or empty string","watchdog_method":"documented method or empty string",'
            '"connection":{},"source_code":""}. Each logical function controls one actuator. mode is position or velocity; unit is rad/deg/m/mm or their per-second variants. write_style is single or joint_vector. '
            'A documented joint-vector SDK setter may be shared only with explicit distinct vendor_joint names. '
            'Do not invent methods, ranges, SDK modules, feedback or stop support. Quotes must be exact. '
            'source_code must be empty; a bounded transport is generated deterministically. '
            'If essential details are missing return {"error":"reason"}. No $defs, properties, required, title or type schema keys.')
        payload={'documentation':documentation,'sdk_version':sdk_version,'name':name,'category':category}
        # A flat extraction schema also works with older local Ollama grammar
        # converters; do not send recursive Pydantic $defs to that transport.
        fields={k:{'type':'string'} for k in ('id','vendor_method','argument','mode','unit','documentation_quote','write_style','vendor_joint')}
        fields.update(minimum={'type':'number'},maximum={'type':'number'})
        schema={'type':'object','properties':{'functions':{'type':'array','items':{'type':'object','properties':fields,'required':['id','vendor_method','mode','unit','minimum','maximum','documentation_quote']}}},'required':['functions']}
        schema['properties'].update({k:{'type':'string'} for k in ('feedback_method','stop_method','disconnect_method','sdk_module','client_factory','watchdog_method')})
        matches=list(re.finditer(r'\b([A-Za-z][A-Za-z0-9_]*)\s*\(',documentation))
        methods=sorted({m[1] for m in matches})
        if methods:
            fields['vendor_method']={'type':'string','enum':methods}
            quotes=[]
            for match in matches:
                end=re.search(r'\.(?:\s|$)',documentation[match.start():])
                quote=documentation[match.start():match.start()+end.end() if end else min(len(documentation),match.start()+1800)].rstrip()
                if quote:quotes.append(quote)
            fields['documentation_quote']={'type':'string','enum':list(dict.fromkeys(quotes))}
            for key in ('feedback_method','stop_method','disconnect_method','watchdog_method'):schema['properties'][key]={'type':'string','enum':['',*methods]}
        fields['mode']={'type':'string','enum':['position','velocity']};fields['unit']={'type':'string','enum':['rad','deg','m','mm','rad/s','deg/s','m/s','mm/s']};fields['write_style']={'type':'string','enum':['single','joint_vector']}
        schema['required']+=['feedback_method','stop_method','disconnect_method','sdk_module','client_factory','watchdog_method']
        system+=' Function IDs and metadata methods must be plain identifiers, without parentheses or prose. Unsupported feedback/stop/disconnect/watchdog fields must be empty strings. documentation_quote must include the setter method name.'
        for attempt in range(2):
            options={'response_schema':schema} if self.llm.resolve(adapter_id).get('structured_outputs') else {}
            answer=await self.llm.adapter(adapter_id,**options)(json.dumps(payload),system)
            try:
                raw=json_answer(answer['answer'])
                if 'error' in raw:raise ValueError(raw['error'])
                raw.update(name=name,category=category,sdk_version=sdk_version,documentation=documentation)
                if category=='virtual' and not raw.get('client_factory'):raw['client_factory']='Client'  # internal simulator transport default
                value=self.save(DriverDraft.model_validate(raw));break
            except (ValueError,KeyError,TypeError) as error:
                if attempt==0:
                    payload.update(previous_response=answer['answer'],validation_error=str(error)[:2000]);continue
                failed={'id':uuid.uuid4().hex[:12],'name':name,'category':category,'sdk_version':sdk_version,'documentation':documentation,'answer':answer['answer'],'error':str(error),'created_at':now()}
                atomic_json(self.store.runtime/'driver_generation_failures'/(failed['id']+'.json'),failed)
                draft,issues=salvage(answer['answer'],name,category,sdk_version,documentation)
                raise IncompleteDriver('Driver generation failed validation. The editable draft is retained as '+failed['id']+'. '+str(error),
                    draft,issues,failed['id'],{k:answer.get(k) for k in ('adapter_id','adapter_version','model')}) from error
        value['provenance'] = {k:answer[k] for k in ('adapter_id','adapter_version','model')}
        atomic_json(self.path(value['id']), value); return value

    def review(self, driver_id, expected_hash):
        b = self.get(driver_id)
        if b['hash'] != expected_hash: raise ValueError('Driver changed since review')
        b['reviewed_hash'] = expected_hash; b['status'] = 'reviewed'; atomic_json(self.path(driver_id), b); return b

    async def test(self, driver_id):
        b = self.get(driver_id); p = DriverProcess(); checks = []
        try:
            state=await p.start(b);previous=state.get('positions') or {}
            for f in b['definition']['functions']:
                for value in (f['minimum'],(f['minimum']+f['maximum'])/2,f['maximum']):
                    result = await p.request({'operation':'command','commands':[{'function':f['id'],'value':value}]})
                    if result['source'] != 'simulation' or not result['sdk_calls']: raise ValueError('Generated setter did not exercise the simulated SDK')
                    if any(c['method'] != f['vendor_method'] for c in result['sdk_calls']): raise ValueError('Setter called an unrelated vendor method')
                    observed=result['observed_values']
                    if observed.get(f['id']) != value: raise ValueError('Generated setter changed the wrong actuator or value')
                    if any(observed.get(key)!=v for key,v in previous.items() if key!=f['id']):raise ValueError('Single-actuator function changed another actuator')
                    previous=observed
                checks.append(f['id']+': generated setter, feedback and unchanged peers')
            f = b['definition']['functions'][0]
            invalid = [{'function':f['id'],'value':f['minimum']}, {'function':'missing_function','value':0}]
            before = await p.request({'operation':'trace'})
            try: await p.request({'operation':'command','commands':invalid})
            except ValueError: pass
            else: raise ValueError('Invalid batch was accepted')
            after = await p.request({'operation':'trace'})
            if before != after: raise ValueError('Invalid batch caused partial SDK writes')
            checks.append('Complete preflight rejects invalid batches before any SDK call')
            await p.request({'operation':'stop'}); checks.append('Stop path exercised; simulated feedback explicitly labelled')
            b['test_report'] = {'passed':True,'contract_version':DRIVER_CONTRACT,'scope':'generated_code_with_injected_sdk','hardware_validated':False,'hash':b['hash'],'checks':checks,'tested_at':now()}
            b['status'] = 'tested' if b['reviewed_hash'] == b['hash'] else 'tested_unreviewed'
            atomic_json(self.path(driver_id), b); return b
        finally: await p.close()
