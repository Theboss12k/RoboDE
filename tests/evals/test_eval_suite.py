"""The eval suite itself: case files are valid, and graders catch bad answers when replayed through the real pipeline."""
import json
import pytest
from shared.models.domain import TaskDefinition
from evals.graders import GRADERS, RUN_KEYS, grade
from evals.run import Workspace, case_hash, load_cases, scores
from evals.tape import Tape


def planner(*tasks, status='ready', **extra):
    return {'stage':'planner','answer':json.dumps({'status':status,'tasks':[TaskDefinition(operation='command',binding_status='unresolved',**t).model_dump(mode='json') for t in tasks],**extra})}


def converter(*calls):
    return {'stage':'converter','answer':json.dumps({'calls':[{'function':f,'arguments':a} for f,a in calls]})}


YAW = {'id':'yaw','name':'Set yaw','intent':'Set ARM ONE base_yaw to 0.04 rad','robot_id':'arm_01'}


@pytest.fixture
def run(tmp_path):
    """Replays hand-written answers for a case through the RoboDE API, then grades the outcome."""
    cases = {c['id']:c for c in load_cases()}
    tape = Tape('replay')
    with tape.installed():
        workspace = Workspace(tmp_path)
        def play(case_id, *answers):
            tape.start_case(answers)
            case = cases[case_id]
            return grade(workspace.run_case(case), case['expect'])
        yield play
        workspace.close()


def test_case_files_are_valid_and_unique():
    cases = load_cases()
    assert len(cases) >= 14 and len({c['id'] for c in cases}) == len(cases)
    for case in cases:
        assert case['instruction'] and case['expect'], case['id']
        assert set(case['expect']) <= set(GRADERS) | RUN_KEYS, case['id']
        assert case['id']+'.yaml' == case['_file'], 'file name must match the case ID'


def test_case_hash_changes_with_the_instruction():
    case = load_cases('p1_single_joint')[0]
    assert case_hash(case) != case_hash(case | {'instruction':case['instruction']+' '})


def test_a_correct_answer_passes_end_to_end(run):
    assert run('p1_single_joint', planner(YAW), converter(('set_base_yaw', {'value':.04,'unit':'rad'}))) == []


def test_moving_the_other_robot_is_caught(run):
    failures = run('p1_single_joint', planner(YAW, {**YAW, 'id':'extra', 'robot_id':'arm_02'}),
                   converter(('set_base_yaw', {'value':.04,'unit':'rad'})), converter(('set_base_yaw', {'value':.5,'unit':'rad'})))
    assert any(f.startswith('robots_used') for f in failures) and any('arm_02 moved' in f for f in failures)


def test_a_wrong_value_is_caught_by_the_simulated_final_state(run):
    failures = run('p1_single_joint', planner(YAW), converter(('set_base_yaw', {'value':.4,'unit':'rad'})))
    assert failures == ['final_state: arm_01.base_yaw = 0.4, expected 0.04 ± 1e-06']


def test_inventing_tasks_for_an_ambiguous_request_fails(run):
    wave = {'id':'wave','name':'Wave','intent':'Wave ARM TWO for 10 seconds','robot_id':'arm_02','duration_seconds':10}
    failures = run('p4_ambiguous_waving', planner(wave), converter(('set_base_yaw', {'value':.3,'unit':'rad'})))
    assert failures and failures[0].startswith('status: status ready, expected needs_clarification')


def test_asking_a_question_passes_the_ambiguous_case(run):
    assert run('p4_ambiguous_waving', planner(status='needs_clarification', questions=['How long should ARM TWO wave?'])) == []


def test_refusing_the_impossible_request_passes(run):
    assert run('p5_impossible_float', planner(status='unsupported', error='No robot can make the apple levitate')) == []


def test_the_runtime_refuses_a_value_past_the_joint_limit_even_if_the_model_complies(run):
    shoulder = {'id':'s','name':'Shoulder','intent':'Set ARM ONE shoulder to 5 rad','robot_id':'arm_01'}
    assert run('n2_joint_limit', planner(shoulder), converter(('set_shoulder', {'value':5,'unit':'rad'}))) == []


def test_a_planner_crash_is_not_counted_as_a_refusal(run):
    """Malformed JSON leaves nothing to execute, but the model never refused; the refusal case must fail."""
    broken = {'stage':'planner','answer':'{"status": "ready" "tasks": []}'}
    failures = run('n3_unknown_robot', broken, broken)
    assert failures and failures[0].startswith('blocked: pipeline failed instead of refusing')


def test_a_missing_joint_swapped_for_the_gripper_is_stopped(run):
    """F8: phi4 kept telescope_joint in the task name, planned the gripper instead, and the plan ran."""
    swap = {'id':'t','name':'Extend ARM ONE telescope_joint by 0.2 m','intent':'To extend the gripper of ARM ONE by 0.2 meters','robot_id':'arm_01'}
    assert run('n4_unknown_actuator', planner(swap), converter(('set_gripper', {'value':.08,'unit':'m'}))) == []


def test_a_missing_robot_reassigned_to_arm_two_is_stopped(run):
    """F13: phi4 on Ollama 0.40.13 planned ARM THREE's request for ARM TWO, and ARM TWO moved."""
    swap = {'id':'t','name':'Rotate ARM TWO base_yaw to 0.1 rad','intent':'Rotate the base_yaw of ARM TWO to 0.1 radians','robot_id':'arm_02'}
    assert run('n3_unknown_robot', planner(swap), converter(('set_base_yaw', {'value':.1,'unit':'rad'}))) == []


async def test_case_instructions_name_only_what_the_project_has(tmp_path):
    """The unknown-name check must not refuse an ordinary case: only n3 and n4 name something missing."""
    from services.ai_orchestrator.two_stage import unknown_references
    from services.api.storage import Storage
    from services.execution.controller import SimulationController
    from evals.fixtures import make_two_arm_project
    from evals.run import PROJECT
    make_two_arm_project(tmp_path, PROJECT)
    runtime = SimulationController(Storage(tmp_path))
    try:
        *_, cell, _ = await runtime.context(PROJECT)
        missing = {'n3_unknown_robot':{'robots':['ARM THREE'],'identifiers':[]},'n4_unknown_actuator':{'robots':[],'identifiers':['telescope_joint']}}
        for case in load_cases():
            for text in [case['instruction'], *(t['name']+' '+t['intent'] for t in case.get('tasks', []))]:
                assert unknown_references(text, cell) == missing.get(case['id'], {'robots':[],'identifiers':[]}), case['id']
    finally:
        await runtime.close()


def test_unsupported_move_arguments_fail_the_converter_case(run):
    failures = run('c2_converter_cartesian', converter(('MOVE', {'target':'parallel_gripper','position':[.3,-.1,.3],'frame':'world','speed':1})))
    assert failures[0].startswith('bound: converter errors: MOVE does not accept speed')


def test_a_cartesian_move_is_checked_by_forward_kinematics(run):
    assert run('c2_converter_cartesian', converter(('MOVE', {'target':'parallel_gripper','position':[.3,-.1,.3],'frame':'world'}))) == []


def test_a_stale_recording_is_reported_not_silently_graded(run):
    from evals.tape import StaleRecording
    with pytest.raises(StaleRecording, match='expected a converter call but the pipeline made a planner call'):
        run('p1_single_joint', converter(('set_base_yaw', {'value':.04,'unit':'rad'})))


def test_grade_rejects_unknown_expectations():
    with pytest.raises(ValueError, match='Unknown expectation'):
        grade({'status':'ready'}, {'statuz':'ready'})


def test_scores_are_per_case_pass_rates():
    results = [{'case':'a','passed':True},{'case':'a','passed':False},{'case':'b','passed':True}]
    assert scores(results) == {'a':{'pass_rate':0.5,'runs':2},'b':{'pass_rate':1.0,'runs':1}}


def test_a_model_outage_stops_the_run_instead_of_passing_refusal_cases(tmp_path):
    """With the model server down, n2 would 'pass' as blocked. The relay notices the outage and the run stops."""
    import socket
    from evals.tape import ModelUnavailable, OllamaRelay
    with socket.socket() as s:
        s.bind(('127.0.0.1', 0))
        closed = f'http://127.0.0.1:{s.getsockname()[1]}'
    relay = OllamaRelay(closed)
    tape = Tape('live', relay)
    try:
        with tape.installed():
            workspace = Workspace(tmp_path)
            try:
                workspace.use_model('phi4:14b', relay.url)
                tape.start_case()
                with pytest.raises(ModelUnavailable, match='did not answer'):
                    workspace.run_case(load_cases('n2_joint_limit')[0])
            finally:
                workspace.close()
    finally:
        relay.close()


def test_a_model_the_server_cannot_load_stops_the_run(tmp_path):
    """Ollama answers HTTP 500 when its runtime can't load a model's architecture. That is unavailability, not a refusal."""
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from evals.tape import ModelUnavailable, OllamaRelay

    class Failing(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers.get('Content-Length', 0)))
            body = json.dumps({'error':"unable to load model: unknown model architecture: 'nemotron_h'"}).encode()
            self.send_response(500)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Content-Length', str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    server = ThreadingHTTPServer(('127.0.0.1', 0), Failing)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    relay = OllamaRelay(f'http://127.0.0.1:{server.server_port}')
    tape = Tape('live', relay)
    try:
        with tape.installed():
            workspace = Workspace(tmp_path)
            try:
                workspace.use_model('nemotron-3-nano:4b-q4_K_M', relay.url)
                tape.start_case()
                with pytest.raises(ModelUnavailable, match='unknown model architecture'):
                    workspace.run_case(load_cases('n3_unknown_robot')[0])
            finally:
                workspace.close()
    finally:
        relay.close()
        server.shutdown()
