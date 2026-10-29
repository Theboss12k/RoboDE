"""Real MP4 encoder tests with synthetic pixels; these do not certify RTX rendering."""
import json
import subprocess
import time
from types import SimpleNamespace
import pytest
from shared.models.recording import RecordingRequest
from simulation.isaac_sim.recording import SceneRecorder, encoder_binary


class Pixels:
    closed = 0
    def __init__(self, backend, settings, rid):
        self.width, self.height = map(int, settings.resolution.split('x'))
    def frame(self):
        return bytes((25, 100, 180)) * self.width * self.height
    def close(self):
        Pixels.closed += 1


def recorder(tmp_path, factory=Pixels):
    return SceneRecorder(SimpleNamespace(metadata={'engine':'synthetic_test','simulator_version':'fixture'}),
                         root=tmp_path, camera_factory=factory)


@pytest.mark.parametrize('body', [
    {'fps':60}, {'duration_seconds':0}, {'duration_seconds':301}, {'resolution':'4096x4096'},
    {'position':[0,0,0], 'look_at':[0,0,0]},
    {'position':[float('nan'),0,0]}, {'position':[1001,0,0]}, {'output':'/tmp/unsafe.mp4'},
])
def test_recording_contract_rejects_unbounded_or_invalid_settings(body):
    with pytest.raises(ValueError):
        RecordingRequest.model_validate(body)


def test_real_mp4_encoding_and_project_ownership(tmp_path):
    assert encoder_binary(), 'Install the pinned imageio-ffmpeg dependency'
    capture = recorder(tmp_path)
    record = capture.start('project', 'lease', {'resolution':'640x360','fps':5,'duration_seconds':1})
    assert 'session_id' not in record
    with pytest.raises(ValueError, match='Stop and finish'):
        capture.start('project', 'lease', {})
    with pytest.raises(ValueError, match='another project'):
        capture.get('other', record['id'])
    while capture.current['status']=='recording':
        capture.tick()
        time.sleep(.025)
    capture.close()
    result = capture.get('project', record['id'])
    assert result['status']=='ready', result
    assert 4 <= result['frames'] <= 6
    assert result['physics_advanced_by_recording'] is False
    assert result['engine']=='synthetic_test'
    path = capture.file('project', record['id'])
    assert path.stat().st_size == result['byte_length'] > 32
    probe = subprocess.run([encoder_binary(),'-i',str(path),'-f','null','-'], capture_output=True)
    assert probe.returncode==0
    assert b'640x360' in probe.stderr and b'5 fps' in probe.stderr and b'h264' in probe.stderr
    assert Pixels.closed
    reopened = recorder(tmp_path)
    assert reopened.listing('project')[0]['status']=='ready'


def test_bad_frames_fail_visibly_without_publishing_video(tmp_path):
    class Bad(Pixels):
        def frame(self): return b'wrong-size'
    capture = recorder(tmp_path, Bad)
    with pytest.raises(ValueError, match='frame size'):
        capture.start('project', 'lease', {})
    assert capture.current['status']=='failed'
    assert not list(tmp_path.glob('*/scene.mp4'))


def test_explicit_stop_and_worker_restart_recovery(tmp_path):
    capture = recorder(tmp_path)
    record = capture.start('project','lease',{'resolution':'640x360'})
    capture.stop('Lease expired')
    capture.close()
    assert capture.get('project',record['id'])['status']=='ready'
    path = tmp_path/record['id']/'metadata.json'
    saved = json.loads(path.read_text())
    saved['status']='recording'
    path.write_text(json.dumps(saved))
    restarted = recorder(tmp_path)
    assert restarted.get('project',record['id'])['status']=='interrupted'
    with pytest.raises(ValueError, match='not ready'):
        restarted.file('project',record['id'])
    with pytest.raises(ValueError, match='Invalid recording'):
        restarted.get('project','../../secret')


def test_encoder_error_and_capture_backpressure_do_not_publish_invalid_mp4(tmp_path):
    capture = SceneRecorder(SimpleNamespace(metadata={'engine':'synthetic_test'}),root=tmp_path,camera_factory=Pixels,binary='/missing/ffmpeg')
    capture.start('project','lease',{'resolution':'640x360'})
    capture.thread.join(5)
    capture.tick()  # Main thread releases the camera after encoder failure.
    assert capture.current['status']=='failed'
    assert capture.source is None
    assert not list(tmp_path.glob('*/scene.mp4'))


def test_slow_rendering_fails_instead_of_inventing_motion(tmp_path):
    capture = recorder(tmp_path)
    capture.start('project','lease',{'resolution':'640x360','fps':5})
    capture.next_frame=time.monotonic()-2
    capture.tick()
    capture.close()
    assert capture.current['status']=='failed'
    assert 'too slow' in capture.current['error']


def test_native_camera_uses_session_layer_and_renders_without_physics(monkeypatch):
    """Real USD camera transforms, fake annotator/renderer; no RTX certification."""
    import sys
    from types import ModuleType
    import numpy as np
    from pxr import Usd
    from simulation.isaac_sim.recording import NativeCamera
    stage=Usd.Stage.CreateInMemory()
    original=stage.GetRootLayer().ExportToString()
    counts={'render':0,'destroy':0,'detach':0}
    def render():counts['render']+=1
    def destroy():counts['destroy']+=1
    def detach():counts['detach']+=1
    data=np.full((360,640,4),125,dtype=np.uint8)
    annotator=SimpleNamespace(attach=lambda product:None,get_data=lambda:data,detach=detach)
    core=ModuleType('omni.replicator.core')
    enabled=[]
    core.create=SimpleNamespace(render_product=lambda path,size:SimpleNamespace(destroy=destroy,hydra_texture=SimpleNamespace(set_updates_enabled=enabled.append)))
    core.annotators=SimpleNamespace(get=lambda name:annotator)
    omni=ModuleType('omni');replicator=ModuleType('omni.replicator')
    omni.replicator=replicator;replicator.core=core
    for name,module in [('omni',omni),('omni.replicator',replicator),('omni.replicator.core',core)]:
        monkeypatch.setitem(sys.modules,name,module)
    backend=SimpleNamespace(world=SimpleNamespace(stage=stage,render=render))
    settings=RecordingRequest(resolution='640x360',position=(0,0,2),look_at=(0,0,0))
    camera=NativeCamera(backend,settings,'a'*32)
    assert stage.GetPrimAtPath(camera.path)
    assert stage.GetRootLayer().ExportToString()==original
    assert len(camera.frame())==360*640*3
    assert counts['render']==4
    camera.close()
    # Finalizing one video must preserve the live articulation's graph.
    assert stage.GetPrimAtPath(camera.path)
    assert counts['detach']==counts['destroy']==0
    assert enabled==[False]
    camera.resume(settings)
    assert enabled==[False,True]
    camera.destroy()
    assert not stage.GetPrimAtPath(camera.path)
    assert counts['detach']==counts['destroy']==1
    assert stage.GetRootLayer().ExportToString()==original


def test_frame_queue_is_bounded_and_reports_backpressure(tmp_path):
    import queue
    capture=recorder(tmp_path)
    capture.settings=RecordingRequest(resolution='640x360')
    capture.frames=queue.Queue(maxsize=1)
    frame=bytes(640*360*3)
    capture._enqueue(frame)
    with pytest.raises(ValueError,match='cannot keep up'):
        capture._enqueue(frame)


def test_native_camera_pool_reuses_paused_products_until_scene_unload(tmp_path,monkeypatch):
    import simulation.isaac_sim.recording as module
    counters={'created':0,'resumed':0,'destroyed':0}
    class PooledPixels(Pixels):
        def __init__(self,*args):
            super().__init__(*args);counters['created']+=1
        def resume(self,settings):counters['resumed']+=1
        def destroy(self):counters['destroyed']+=1
    monkeypatch.setattr(module,'NativeCamera',PooledPixels)
    capture=SceneRecorder(SimpleNamespace(metadata={'engine':'synthetic_test'}),root=tmp_path,camera_factory=PooledPixels)
    for _ in range(2):
        capture.start('project','lease',{'resolution':'640x360'})
        capture.stop()
        capture.thread.join(5)
        assert capture.current['status']=='ready'
    assert counters=={'created':1,'resumed':1,'destroyed':0}
    capture.cleanup_cameras()
    assert counters['destroyed']==1 and not capture.camera_cache
