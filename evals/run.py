"""Run the eval cases against one or more models, record or replay them, and gate on a baseline.

  npm run eval -- --model phi4:14b                         live, against local Ollama
  npm run eval -- --model phi4:14b --record                live, and save answers to evals/recordings
  npm run eval -- --model phi4:14b --replay                offline, from saved answers
  npm run eval -- --model phi4:14b --replay --baseline     fail if any case scores below its baseline
  npm run eval -- --model phi4:14b --update-baseline       accept this run as the new baseline

Every run uses a disposable workspace and the built-in mock simulator: no saved projects, credentials,
cloud compute or hardware are touched.
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import platform
import statistics
import sys
import tempfile
import time
import urllib.request

import yaml

ROOT = Path(__file__).resolve().parent.parent
CASES = ROOT/'evals/cases'
RECORDINGS = ROOT/'evals/recordings'
BASELINES = ROOT/'evals/baselines'
PROJECT = 'two_arm'
STATUS = {'tasks_ready':'ready','commands_ready':'ready','needs_clarification':'needs_clarification','unsupported':'unsupported'}


def slug(model):
    return ''.join(c if c.isalnum() else '-' for c in model).strip('-')


def load_cases(selected=None):
    cases = [yaml.safe_load(p.read_text()) | {'_file':p.name} for p in sorted(CASES.glob('*.yaml'))]
    ids = [c['id'] for c in cases]
    if len(set(ids)) != len(ids):
        raise SystemExit('Duplicate case IDs in evals/cases')
    if selected:
        wanted = set(selected.split(','))
        missing = wanted - set(ids)
        if missing:
            raise SystemExit('Unknown case(s): ' + ', '.join(sorted(missing)))
        cases = [c for c in cases if c['id'] in wanted]
    return cases


def case_hash(case):
    """Recordings are only valid for the exact instruction and predefined tasks they were made with."""
    return hashlib.sha256(json.dumps({'instruction':case['instruction'],'tasks':case.get('tasks')}, sort_keys=True).encode()).hexdigest()[:16]


def adapter_source(model):
    from services.validation.registry import ROOT as SERVER
    source = (SERVER/'examples/llm/ollama_nemotron.py').read_text()
    # The same change scripts/evaluate_local_llms.mjs makes: only Nemotron Nano/Bolt accept the think flag.
    if 'nemotron' not in model:
        source = source.replace("if 'nemotron-mini' not in model:", "if 'nemotron' in model and 'mini' not in model:")
    return source


def ollama_info(url, model):
    try:
        with urllib.request.urlopen(url.rstrip('/')+'/api/tags', timeout=5) as r:
            tags = json.load(r)['models']
        with urllib.request.urlopen(url.rstrip('/')+'/api/version', timeout=5) as r:
            version = json.load(r).get('version')
    except OSError as error:
        raise SystemExit(f'Ollama is not reachable at {url}: {error}') from None
    found = next((m for m in tags if m['name'] == model), None)
    if not found:
        raise SystemExit(f'{model} is not installed at {url}. Pull it first: ollama pull {model}')
    return {'ollama_version':version,'digest':found.get('digest'),'size_bytes':found.get('size'),'details':found.get('details')}


class Workspace:
    """A temporary RoboDE runtime with the two-arm project, driven through its own HTTP API in-process."""

    def __init__(self, root):
        from fastapi.testclient import TestClient
        from services.api.main import create_app
        from services.api.storage import Storage, atomic_json
        from evals.fixtures import make_two_arm_project
        make_two_arm_project(root, PROJECT, 'Evaluation · two arms')
        store = Storage(root)
        # Same isolation as scripts/local_model_evaluation_server.py: built-in motion, not a GPU, cloud or physical worker.
        atomic_json(store.runtime/'connections/motion.json', {'url':'http://127.0.0.1:19129','token_env':'ROBOT_DE_EVALUATION_UNUSED_TOKEN'})
        self.client = TestClient(create_app(store, speed=100))
        self.client.__enter__()

    def close(self):
        self.client.__exit__(None, None, None)

    def call(self, method, path, **kwargs):
        r = self.client.request(method, path, **kwargs)
        body = r.json() if r.content else {}
        return r.status_code, body

    def use_model(self, model, base_url):
        code, profile = self.call('POST', '/api/llm/adapters', json={'name':'Evaluation · '+model,'protocol':'python_function','connection_type':'custom',
            'source_code':adapter_source(model),'base_url':base_url,'model':model,'timeout_seconds':300,'max_tokens':4096})
        if code != 201:
            raise SystemExit(f'Could not register the {model} adapter: {profile}')
        self.call('PUT', '/api/llm/default', json={'adapter_id':profile['id']})
        self.call('PUT', '/api/llm/roles', json={'planner_adapter_id':profile['id'],'binding_adapter_id':profile['id'],'vision_enabled':False})

    def run_case(self, case):
        """Planner -> Converter -> compile -> mock simulation, stopping where the pipeline refuses."""
        from shared.models.domain import TaskDefinition
        base = f'/api/projects/{PROJECT}'
        self.call('POST', base+'/reset')
        outcome = {'status':None,'error':None,'tasks':[],'binding_errors':[],'compiled':None,'executed':None,'final_state':None,'tool_position':None}
        code, d = self.call('POST', base+'/plan-definitions', json={'name':case['id'],'goal':case['instruction']})
        url = f"{base}/plan-definitions/{d['id']}"
        if case.get('tasks'):
            # Converter-only case: the planner is skipped and these tasks are bound as if it had written them.
            tasks = [TaskDefinition(operation='command', binding_status='unresolved', authored_by='planner', **t).model_dump(mode='json') for t in case['tasks']]
            code, d = self.call('PUT', url, json={'name':d['name'],'goal':d['goal'],'version':d['version'],'tasks':tasks})
            if code != 200:
                raise RuntimeError(f"Case {case['id']} has invalid predefined tasks: {d}")
            outcome['status'] = 'ready'
        else:
            code, d = self.call('POST', url+'/decompose', json={'version':d['version'],'instruction':case['instruction'],'replace_tasks':False})
            if code != 200:
                outcome.update(status='error', error=str(d.get('detail', d))[:500])
                return outcome
            outcome['status'] = STATUS.get(d['planning_status'], d['planning_status'])
            outcome['error'] = d.get('planning_error') or ('; '.join(d.get('clarification_questions') or []) or None)
            if outcome['status'] != 'ready':
                outcome['tasks'] = d['tasks']
                return outcome
        code, bound = self.call('POST', url+'/bind-commands', json={'version':d['version']})
        if code != 200:
            outcome.update(status='error', error=str(bound.get('detail', bound))[:500])
            return outcome
        d = bound['definition']
        outcome['tasks'] = [{k:t.get(k) for k in ('id','name','intent','robot_id','repeat_count','duration_seconds','dependencies','function_calls','binding_status','binding_error')} for t in d['tasks']]
        outcome['binding_errors'] = bound['errors']
        if bound['errors'] or not case['expect'].get('execute'):
            return outcome
        code, revision = self.call('POST', url+'/compile')
        outcome['compiled'] = code == 201 and bool(revision.get('valid'))
        if not outcome['compiled']:
            outcome['error'] = str(revision.get('detail') or revision.get('validation_report') or revision)[:500]
            return outcome
        code, run = self.call('POST', f"{base}/plans/{revision['id']}/simulate", json={'fingerprint':revision['fingerprint'],'adapter':'mock'})
        if code != 202:
            outcome.update(executed=False, error=str(run)[:500])
            return outcome
        for _ in range(300):
            _, run = self.call('GET', f"/api/runs/{run['id']}")
            if run.get('finished_at'):
                break
            time.sleep(0.1)
        outcome['executed'] = run.get('status') == 'SIMULATION_PASSED' and bool(run.get('stopped_verified'))
        states = run.get('robot_states') or {}
        outcome['final_state'] = {rid:(s.get('positions') or s) for rid, s in states.items()}
        outcome['tool_position'] = tool_positions(outcome['final_state'])
        return outcome


def tool_positions(final_state):
    """Independent forward kinematics, so a Cartesian case is judged by where the tool ended up, not by a status."""
    from services.planning.kinematics import forward
    from services.validation.registry import MODEL_ROOT, load_model
    from evals.fixtures import BASE_OFFSETS, INITIAL_JOINTS
    model = load_model(MODEL_ROOT/'demo_arm')
    result = {}
    for rid, joints in final_state.items():
        pose = forward(model, {j:joints[j] for j in INITIAL_JOINTS if j in joints})
        offset = BASE_OFFSETS.get(rid, (0, 0, 0))
        result[rid] = [pose.x+offset[0], pose.y+offset[1], pose.z+offset[2]]
    return result


def run_model(workspace, tape, model, cases, repeat, mode, recordings, results):
    """Appends to `results` as it goes, so the caller keeps finished cases if a later one is interrupted."""
    from evals.graders import grade
    for case in cases:
        recording = recordings.get(case['id'])
        runs = len(recording['runs']) if mode == 'replay' else repeat
        saved = []
        for k in range(runs):
            tape.start_case(recording['runs'][k]['calls'] if mode == 'replay' else None)
            started = time.monotonic()
            try:
                outcome = workspace.run_case(case)
            except ValueError as error:
                outcome = {'status':'error','error':str(error)[:500],'tasks':[]}
            seconds = round(time.monotonic()-started, 2)
            failures = grade(outcome, case['expect'])
            calls = tape.calls
            tokens = [sum(v for k2, v in (c.get('usage') or {}).items() if k2 in ('prompt_tokens','completion_tokens') and v) for c in calls]
            results.append({'model':model,'case':case['id'],'repeat':k+1,'passed':not failures,'failures':failures,'seconds':seconds,
                            'llm_calls':len(calls),'planner_repair':sum(c['stage'] == 'planner' for c in calls) > 1,
                            'llm_seconds':round(sum(c.get('duration_seconds') or 0 for c in calls), 2),'tokens':sum(tokens),
                            'status':outcome['status'],'error':outcome.get('error'),'tasks':outcome.get('tasks'),
                            'final_state':outcome.get('final_state'),'tool_position':outcome.get('tool_position')})
            saved.append({'recorded_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),'calls':calls})
            mark = 'PASS' if not failures else 'FAIL'
            print(f"  {case['id']:<26} run {k+1}/{runs}  {mark}  {seconds:>6.1f}s" + (f"  {failures[0]}" if failures else ''), flush=True)
        if mode == 'record':
            path = RECORDINGS/slug(model)/f"{case['id']}.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({'case':case['id'],'case_hash':case_hash(case),'model':model,'runs':saved}, indent=1)+'\n')


def load_recordings(model, cases):
    found = {}
    for case in cases:
        path = RECORDINGS/slug(model)/f"{case['id']}.json"
        if not path.exists():
            raise SystemExit(f"No recording for {case['id']} with {model}. Record it first with --record.")
        data = json.loads(path.read_text())
        if data['case_hash'] != case_hash(case):
            raise SystemExit(f"The recording of {case['id']} with {model} is stale: the case changed. Record it again.")
        found[case['id']] = data
    return found


def scores(results):
    by_case = {}
    for r in results:
        by_case.setdefault(r['case'], []).append(r['passed'])
    return {case:{'pass_rate':round(sum(v)/len(v), 3),'runs':len(v)} for case, v in by_case.items()}


def compare(model, results):
    path = BASELINES/f'{slug(model)}.json'
    if not path.exists():
        return [f'{model}: no baseline at {path.relative_to(ROOT)}; run with --update-baseline first'], []
    baseline = json.loads(path.read_text())['cases']
    current = scores(results)
    regressions = [f"{model} / {c}: pass rate {baseline[c]['pass_rate']:.0%} -> {s['pass_rate']:.0%}"
                   for c, s in current.items() if c in baseline and s['pass_rate'] < baseline[c]['pass_rate']]
    improvements = [f"{model} / {c}: pass rate {baseline[c]['pass_rate']:.0%} -> {s['pass_rate']:.0%}"
                    for c, s in current.items() if c in baseline and s['pass_rate'] > baseline[c]['pass_rate']]
    return regressions, improvements


def write_baseline(model, results, environment):
    BASELINES.mkdir(parents=True, exist_ok=True)
    path = BASELINES/f'{slug(model)}.json'
    path.write_text(json.dumps({'model':model,'updated_at':datetime.now(timezone.utc).isoformat(timespec='seconds'),
                                'environment':environment,'cases':scores(results)}, indent=1, sort_keys=True)+'\n')
    return path


def summary(report):
    lines = [f"# Eval run · {report['started_at']}", '', f"Mode: **{report['mode']}**. {report['scope']}", '']
    lines += ['| Model | Cases passed on every run | Run pass rate | Median case time | Median LLM call | Median tokens per case | Planner repairs |',
              '| --- | ---: | ---: | ---: | ---: | ---: | ---: |']
    models = list(dict.fromkeys(r['model'] for r in report['results']))
    for model in models:
        rs = [r for r in report['results'] if r['model'] == model]
        s = scores(rs)
        calls = [r['llm_seconds']/r['llm_calls'] for r in rs if r['llm_calls']]
        tokens = [r['tokens'] for r in rs if r['tokens']]
        lines.append(f"| `{model}` | {sum(v['pass_rate'] == 1 for v in s.values())}/{len(s)} | {sum(r['passed'] for r in rs)/len(rs):.0%} | "
                     f"{statistics.median(r['seconds'] for r in rs):.1f}s | {(f'{statistics.median(calls):.1f}s' if calls else '–')} | "
                     f"{(f'{statistics.median(tokens):,.0f}' if tokens else '–')} | {sum(r['planner_repair'] for r in rs)} |")
    cases = list(dict.fromkeys(r['case'] for r in report['results']))
    lines += ['', '## Per case', '', '| Case | ' + ' | '.join(f'`{m}`' for m in models) + ' |', '| --- |' + ' --- |'*len(models)]
    for case in cases:
        cells = []
        for model in models:
            rs = [r for r in report['results'] if r['model'] == model and r['case'] == case]
            cells.append(' '.join('✓' if r['passed'] else '✗' for r in rs) or '–')
        lines.append(f'| {case} | ' + ' | '.join(cells) + ' |')
    failures = [r for r in report['results'] if not r['passed']]
    if failures:
        lines += ['', '## First failure reason per case', '']
        seen = set()
        for r in failures:
            if (r['model'], r['case']) not in seen:
                seen.add((r['model'], r['case']))
                lines.append(f"- `{r['model']}` / {r['case']}: {r['failures'][0]}")
    return '\n'.join(lines)+'\n'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument('--model', action='append', required=True, help='Ollama model tag; repeat for several models')
    parser.add_argument('--ollama-url', default='http://127.0.0.1:11434')
    parser.add_argument('--cases', help='comma-separated case IDs (default: all)')
    parser.add_argument('--repeat', type=int, default=3, help='runs per case in live/record mode')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('--record', action='store_true', help='save model answers to evals/recordings')
    mode.add_argument('--replay', action='store_true', help='use saved answers instead of a model')
    parser.add_argument('--baseline', action='store_true', help='exit 1 if any case scores below its baseline')
    parser.add_argument('--update-baseline', action='store_true', help='save this run as the baseline')
    parser.add_argument('--output', type=Path, help='results folder (default: artifacts/evals/<timestamp>)')
    args = parser.parse_args(argv)
    run_mode = 'replay' if args.replay else 'record' if args.record else 'live'

    # An isolated runtime: no production environment provider, and the app module's import-time default
    # workspace is created in the temporary folder too.
    for key in ('AI_BASE_URL','AI_MODEL','AI_API_KEY'):
        os.environ.pop(key, None)
    os.environ['ROBOT_IDE_EDITION'] = 'standard'
    cases = load_cases(args.cases)
    started = datetime.now(timezone.utc)
    output = args.output or ROOT/'artifacts/evals'/started.strftime('%Y%m%d-%H%M%S')
    output.mkdir(parents=True, exist_ok=True)
    report = {'started_at':started.isoformat(timespec='seconds'),'mode':run_mode,
              'scope':('Saved model answers replayed offline.' if run_mode == 'replay' else 'Real model inference.')
                      +' Planner and Converter through the RoboDE API; built-in mock simulation; no hardware, Isaac physics or cloud workers.',
              'machine':{'system':platform.system(),'machine':platform.machine(),'python':platform.python_version()},
              'models':[],'results':[]}
    regressions, improvements, aborted = [], [], None
    with tempfile.TemporaryDirectory(prefix='robode-evals-') as directory:
        os.environ['ROBOT_IDE_DATA_DIR'] = directory
        from evals.tape import ModelUnavailable, OllamaRelay, Tape
        relay = None if run_mode == 'replay' else OllamaRelay(args.ollama_url)
        tape = Tape(run_mode, relay)
        try:
            with tape.installed():
                for model in args.model:
                    info = {'model':model} | ({} if run_mode == 'replay' else ollama_info(args.ollama_url, model))
                    report['models'].append(info)
                    print(f"{model} · {run_mode} · {len(cases)} case(s)", flush=True)
                    workspace = Workspace(Path(directory)/slug(model))
                    results = []
                    try:
                        if run_mode != 'replay':
                            workspace.use_model(model, relay.url)
                        recordings = load_recordings(model, cases) if run_mode == 'replay' else {}
                        run_model(workspace, tape, model, cases, args.repeat, run_mode, recordings, results)
                    finally:
                        workspace.close()
                        report['results'] += results
                    if args.baseline:
                        r, i = compare(model, results)
                        regressions += r
                        improvements += i
                    if args.update_baseline:
                        environment = {k:v for k, v in info.items() if k != 'model'} | {'mode':run_mode}
                        previous = BASELINES/f'{slug(model)}.json'
                        if run_mode == 'replay' and previous.exists():
                            # Regrading saved answers: they still come from the model and runtime that recorded them.
                            environment = json.loads(previous.read_text())['environment'] | {'regraded_by':'replay'}
                        path = write_baseline(model, results, environment)
                        print(f'  baseline saved: {path.relative_to(ROOT)}')
        except ModelUnavailable as error:
            # Nothing from the interrupted case is graded, recorded or used as a baseline.
            aborted = str(error)
        finally:
            if relay:
                relay.close()
            report['finished_at'] = datetime.now(timezone.utc).isoformat(timespec='seconds')
            report['regressions'], report['improvements'], report['aborted'] = regressions, improvements, aborted
            (output/'results.json').write_text(json.dumps(report, indent=1)+'\n')
            if report['results']:
                (output/'summary.md').write_text(summary(report))
    if report['results']:
        print('\n'+summary(report))
    print(f'Results: {output}')
    for line in improvements:
        print('Improved: '+line)
    for line in regressions:
        print('REGRESSION: '+line)
    if aborted:
        print(f'ABORTED: {aborted}. Cases finished before the outage are saved; rerun the rest when the model server is back.')
        return 2
    return 1 if regressions else 0


if __name__ == '__main__':
    sys.exit(main())
