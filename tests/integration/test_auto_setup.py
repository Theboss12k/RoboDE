"""One-step robot setup: a URDF and vendor documentation become a reviewable robot, adapter and mapping."""
import json
import math
import re
import time

import httpx
from fastapi.testclient import TestClient
from services.api.main import create_app
from services.ai_orchestrator.llm import LLMRegistry, ProviderConfiguration
from services.adapters.bindings import propose_mapping, unit_scale
from services.imports.autofill import from_documentation, from_urdf
from services.imports.urdf import parse_urdf
from services.validation.registry import ROOT

URDF = (ROOT/'examples/robots/gantry_rover.urdf').read_bytes()
MANUAL = (ROOT/'examples/robots/gantry_rover_sdk_manual.md').read_text()
BASE = '/api/registry/urdf/drafts'


def line(text):
    """The complete manual line (sentence or table row) containing text."""
    return next(l.strip() for l in MANUAL.splitlines() if text in l)


def sentence(method):
    return re.search(re.escape(method)+r'\(.*?\.(?=\s)', MANUAL)[0]


PREFILL = {'robot': {'name': 'Tarnwick TR-GR40 Kestrel', 'manufacturer': 'Tarnwick Robotics',
                     'manufacturer_quote': line('Tarnwick Robotics designs mobile handling platforms'),
                     'description': 'A differential-drive rover carrying a three-axis gantry and a three-joint arm with a jaw.'},
           'values': [
               {'target': 'gantry_x', 'field': 'acceleration', 'value': 400, 'unit': 'mm/s²', 'quote': line('| X rail shuttle |')},
               {'target': 'shoulder_yaw', 'field': 'acceleration', 'value': 115, 'unit': 'deg/s²', 'quote': line('| J1 yaw (shoulder) |')},
               {'target': 'left_wheel', 'field': 'acceleration', 'value': 6, 'unit': 'rad/s²', 'quote': line('Maximum wheel acceleration')},
               {'target': 'elbow_pitch', 'field': 'acceleration', 'value': 999, 'unit': 'deg/s²', 'quote': 'J2 accelerates at 999 deg/s².'},
               {'target': 'wrist_pitch', 'field': 'acceleration', 'value': 140, 'unit': 'mm/s²', 'quote': line('| J3 pitch (wrist) |')},
               {'target': 'payload', 'field': 'value', 'value': 1.5, 'unit': 'kg', 'quote': line('Rated payload at the jaw')},
               {'target': 'max_linear_speed', 'field': 'value', 'value': 0.6, 'unit': 'm/s', 'quote': line('Maximum linear speed')}]}
SETTERS = [('set_rail_x', 'mm', 'position', -120, 120), ('set_beam_y', 'mm', 'position', -180, 180), ('set_lift_z', 'mm', 'position', 0, 320),
           ('set_j1_yaw', 'deg', 'position', -149, 149), ('set_j2_pitch', 'deg', 'position', -115, 115), ('set_j3_pitch', 'deg', 'position', -104, 104),
           ('set_jaw_opening', 'mm', 'position', 0, 45), ('set_drive_left', 'rad/s', 'velocity', -12, 12), ('set_drive_right', 'rad/s', 'velocity', -12, 12)]
DRIVER = {'functions': [{'id': m, 'vendor_method': m, 'argument': 'value', 'mode': mode, 'unit': unit, 'minimum': lo, 'maximum': hi,
                         'documentation_quote': sentence(m), 'write_style': 'single', 'vendor_joint': ''} for m, unit, mode, lo, hi in SETTERS],
          'sdk_module': 'tarnwick_rover', 'client_factory': 'RoverClient', 'feedback_method': 'read_state', 'stop_method': 'halt',
          'disconnect_method': 'close', 'watchdog_method': 'heartbeat', 'connection': {}, 'source_code': ''}
JOINT_FUNCTIONS = {'left_wheel': 'set_drive_left', 'right_wheel': 'set_drive_right', 'gantry_x': 'set_rail_x', 'gantry_y': 'set_beam_y',
                   'gantry_z': 'set_lift_z', 'shoulder_yaw': 'set_j1_yaw', 'elbow_pitch': 'set_j2_pitch', 'wrist_pitch': 'set_j3_pitch',
                   'gripper_jaw': 'set_jaw_opening'}
# The AI's scales are deliberately wrong or rough: code must derive them from the units.
MAPPING = {'description': 'Gantry rover with arm', 'joints': [{'joint_id': j, 'alias': j.replace('_', ' '), 'role': 'independent', 'function_id': f,
           'scale': 57.3 if f.startswith('set_j') else 1, 'offset': 5 if j == 'gripper_jaw' else 0} for j, f in JOINT_FUNCTIONS.items()]}


class Stub:
    """An LLM registry stand-in that answers each setup prompt with a fixed reply."""
    def __init__(self, replies):
        self.replies, self.calls = replies, []

    def adapter(self, adapter_id=None, **options):
        async def invoke(input, system_prompt='', images=None):
            self.calls.append((input, system_prompt))
            return {'answer': json.dumps(self.replies(system_prompt)), 'adapter_id': 'stub', 'adapter_version': 1, 'model': 'stub-model'}
        return invoke


def reply_for(system_prompt):
    if 'URDF joints' in system_prompt:
        return PREFILL
    if 'Extract executable actuator metadata' in system_prompt:
        return DRIVER
    if 'Map each URDF joint' in system_prompt:
        return MAPPING
    raise AssertionError('unexpected prompt')


def test_the_urdf_alone_fills_every_review_value():
    result = from_urdf(parse_urdf(URDF))
    review, mobility, provenance = result['review'], result['mobility'], result['provenance']
    assert not result['issues'] and review['tool_link'] == 'tool_tip'
    assert review['joints']['left_wheel'] == {'min': -1000., 'max': 1000., 'velocity': 12., 'acceleration': 24., 'initial': 0.}
    assert provenance['joints.left_wheel.min']['source'] == 'default' and provenance['joints.gantry_x.min']['source'] == 'urdf'
    assert all(s['initial'] is not None and s['acceleration'] > 0 for s in review['joints'].values())
    assert (review['gripper_actuator'], review['gripper_closed'], review['gripper_open']) == ('gripper_jaw', 0., .045)
    assert mobility['classification'] == 'BOTH' and (mobility['left_wheel'], mobility['right_wheel']) == ('left_wheel', 'right_wheel')
    assert (mobility['wheel_radius_m'], mobility['track_width_m']) == (.08, .46)
    assert mobility['footprint'] == [[-.3, -.22], [.3, -.22], [.3, .22], [-.3, .22]]


async def test_documented_values_are_checked_against_their_quote_and_converted():
    llm = Stub(reply_for)
    result = await from_documentation(parse_urdf(URDF), MANUAL, llm)
    joints, provenance, notes = result['review']['joints'], result['provenance'], ' '.join(result['notes'])
    assert math.isclose(joints['gantry_x']['acceleration'], .4) and provenance['joints.gantry_x.acceleration']['as_written'] == '400 mm/s²'
    assert math.isclose(joints['shoulder_yaw']['acceleration'], math.radians(115))
    assert joints['left_wheel']['acceleration'] == 6
    # A quote that isn't in the manual, and a length unit for an angle, are both rejected; the defaults stay.
    assert joints['elbow_pitch']['acceleration'] == 3.2 and 'elbow_pitch acceleration' in notes and 'not in the documentation' in notes
    assert joints['wrist_pitch']['acceleration'] == 4. and 'wrist_pitch acceleration' in notes
    assert result['review']['payload_kg'] == 1.5 and result['mobility']['max_linear_m_s'] == .6
    assert result['review']['manufacturer'] == 'Tarnwick Robotics'
    sent = json.loads(llm.calls[0][0])
    assert sent['documentation'] == MANUAL and 'gantry_x' in {j['name'] for j in sent['urdf_joints']}


async def test_mapping_scale_comes_from_the_units_not_the_model():
    assert unit_scale('m', 'mm') == 1000 and math.isclose(unit_scale('rad', 'deg'), 180/math.pi) and unit_scale('rad', 'rad/s') == 1
    assert unit_scale('m', 'deg') is None
    filled = from_urdf(parse_urdf(URDF))['review']['joints']
    kinds = {j['name']: j['type'] for j in parse_urdf(URDF)['joints']}
    actuators = {j: {'unit': 'm' if kinds[j] == 'prismatic' else 'rad', **s} for j, s in filled.items()}
    replies = dict(MAPPING, joints=MAPPING['joints']+[{'joint_id': 'made_up', 'function_id': 'set_rail_x'}])
    replies['joints'][3] = {**replies['joints'][3], 'function_id': 'set_speed_scale'}
    result = await propose_mapping(Stub(lambda _: replies), None, {'name': 'rover'}, actuators, DRIVER, ['left_wheel', 'right_wheel'])
    by = {j['joint_id']: j for j in result['joints']}
    assert set(by) == set(actuators)
    assert by['gantry_x']['scale'] == 1000 and math.isclose(by['shoulder_yaw']['scale'], 180/math.pi) and by['left_wheel']['scale'] == 1
    assert by['gripper_jaw']['offset'] == 0 and by['gantry_y']['function_id'] is None
    messages = ' '.join(i['message'] for i in result['issues'])
    assert 'set_speed_scale' in messages and 'gantry_y: choose the function' in messages
    assert any('gantry_x: scale set to 1000' in n for n in result['notes'])


def test_a_review_lists_every_problem_at_once(store):
    with TestClient(create_app(store)) as client:
        draft = client.post(BASE+'?filename=rover.urdf', content=URDF, headers={'content-type': 'application/octet-stream'}).json()
        review = client.post(f"{BASE}/{draft['id']}/autofill", json={}).json()['review']
        review['joints']['left_wheel'].update(min=2, max=3, initial=1)
        review['joints']['gripper_jaw']['acceleration'] = -1
        response = client.post(f"{BASE}/{draft['id']}/validate", json=review)
        assert response.status_code == 422
        fields = {e['field'] for e in response.json()['errors']}
        assert fields == {'joints.left_wheel.initial', 'joints.gripper_jaw.acceleration'}
        assert 'left_wheel' in response.json()['detail'] and 'gripper_jaw' in response.json()['detail']


def test_one_job_configures_the_rover_and_every_function_can_be_tried(store, monkeypatch):
    stub = Stub(reply_for)
    provider = LLMRegistry(store).save(ProviderConfiguration(name='Setup LLM', base_url='http://llm.local/v1', model='stub'))
    monkeypatch.setattr(LLMRegistry, 'adapter', lambda self, adapter_id=None, **options: stub.adapter(adapter_id))
    with TestClient(create_app(store)) as client:
        draft = client.post(BASE+'?filename=rover.urdf', content=URDF, headers={'content-type': 'application/octet-stream'}).json()
        job = client.post('/api/library/auto-setup', json={'draft_id': draft['id'], 'documentation': MANUAL, 'adapter_id': provider['id']})
        assert job.status_code == 202, job.text
        for _ in range(200):
            job = client.get(f"/api/library/auto-setup/{job.json()['id']}")
            if job.json()['status'] != 'running':
                break
            time.sleep(.05)
        result = job.json()
        assert result['status'] == 'done', result
        assert {s['status'] for s in result['stages'].values()} == {'done'}
        prefill, driver, mapping = result['result']['prefill'], result['result']['adapter']['driver'], result['result']['mapping']
        assert {f['id'] for f in driver['definition']['functions']} == {m for m, *_ in SETTERS}
        assert not mapping['issues'] and all(j['function_id'] == JOINT_FUNCTIONS[j['joint_id']] for j in mapping['joints'])
        # Accepting uses the existing endpoints: save the model, review and test the adapter, save the mapping.
        model = client.post(f"{BASE}/{draft['id']}/commit", json={**prefill['review'], 'reviewed': True})
        assert model.status_code == 201, model.text
        reviewed = client.post(f"/api/library/drivers/{driver['id']}/review", json={'expected_hash': driver['hash']})
        assert reviewed.status_code == 200, reviewed.text
        tested = client.post(f"/api/library/drivers/{driver['id']}/test").json()
        assert tested['test_report']['passed']
        binding = client.post('/api/library/robot-bindings', json={
            'physical_description': prefill['review']['description'], 'model_id': prefill['review']['id'], 'driver_id': driver['id'],
            'joints': mapping['joints'], 'end_effectors': {'tool': {'link': 'tool_tip', 'xyz': [0, 0, 0], 'rpy': [0, 0, 0]}},
            'mobility': prefill['mobility']})
        assert binding.status_code == 201, binding.text
        tried = client.post(f"/api/library/robot-bindings/{binding.json()['id']}/test-actuators", json={'joint_id': 'gantry_x', 'value': .1})
        assert tried.status_code == 200, tried.text
        evidence = tried.json()['test_evidence']['actuators']
        assert math.isclose(evidence['positions']['gantry_x'], .1)
        # The vendor saw millimetres: 0.1 m × 1000.
        assert any(call['method'] == 'set_rail_x' and math.isclose(call['value'], 100) for call in evidence['sdk_calls']), evidence['sdk_calls']


def test_a_saved_robot_id_is_not_proposed_again_and_is_flagged_on_review(store):
    with TestClient(create_app(store)) as client:
        first = client.post(BASE+'?filename=rover.urdf', content=URDF, headers={'content-type': 'application/octet-stream'}).json()
        review = client.post(f"{BASE}/{first['id']}/autofill", json={}).json()['review']
        assert client.post(f"{BASE}/{first['id']}/commit", json={**review, 'reviewed': True}).status_code == 201
        second = client.post(BASE+'?filename=rover.urdf', content=URDF, headers={'content-type': 'application/octet-stream'}).json()
        again = client.post(f"{BASE}/{second['id']}/autofill", json={}).json()['review']
        assert again['id'] == review['id']+'_2'
        clash = client.post(f"{BASE}/{second['id']}/validate", json={**again, 'id': review['id']})
        assert clash.status_code == 422 and [e['field'] for e in clash.json()['errors']] == ['id']


def test_without_documentation_a_simulator_adapter_drives_the_wheels(store):
    with TestClient(create_app(store)) as client:
        draft = client.post(BASE+'?filename=rover.urdf', content=URDF, headers={'content-type': 'application/octet-stream'}).json()
        job = client.post('/api/library/auto-setup', json={'draft_id': draft['id']}).json()
        for _ in range(100):
            job = client.get(f"/api/library/auto-setup/{job['id']}").json()
            if job['status'] != 'running':
                break
            time.sleep(.05)
        assert job['status'] == 'done' and job['result']['adapter'] == {'status': 'simulator'} and job['stages']['adapter']['status'] == 'skipped'
        prefill = job['result']['prefill']
        model = client.post(f"{BASE}/{draft['id']}/commit", json={**prefill['review'], 'reviewed': True}).json()
        driver = client.post(f"/api/library/drivers/simulator/{model['robot']['id']}").json()
        functions = {f['id']: f for f in driver['definition']['functions']}
        # The wheels keep a ±1000 rad control window, but they are still driven by speed.
        assert functions['set_left_wheel']['mode'] == 'velocity' and functions['set_left_wheel']['unit'] == 'rad/s'
        assert functions['set_gantry_x']['mode'] == 'position'
        joints = [{'joint_id': j, 'function_id': 'set_'+j, 'alias': j, 'role': 'independent', 'scale': 1, 'offset': 0} for j in prefill['review']['joints']]
        binding = client.post('/api/library/robot-bindings', json={'model_id': model['robot']['id'], 'driver_id': driver['id'], 'joints': joints,
            'end_effectors': {'tool': {'link': 'tool_tip', 'xyz': [0, 0, 0], 'rpy': [0, 0, 0]}}, 'mobility': prefill['mobility']})
        assert binding.status_code == 201, binding.text
