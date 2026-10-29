"""Keep every Isaac/Kit call on the standalone process's main thread."""
from concurrent.futures import Future
from queue import Queue,Empty


class MainThreadBridge:
    def __init__(self,backend):
        self.backend=backend
        self.models=backend.models
        self.metadata=backend.metadata
        self.room_root=getattr(backend,'room_root',None)
        self.mesh_root=getattr(backend,'mesh_root',None)
        self.queue=Queue()
    def call(self,name,*args):
        result=Future()
        self.queue.put((name,args,result))
        try:
            return result.result(timeout=180 if name in {"load_scene", "recording_start"} else 30)
        except TimeoutError:
            result.cancel()
            raise RuntimeError('Isaac main thread did not process the worker request in time')
    def pump(self,timeout=.05):
        try:
            name,args,result=self.queue.get(timeout=timeout)
        except Empty:
            return
        if not result.set_running_or_notify_cancel():
            return
        try:
            result.set_result(getattr(self.backend,name)(*args))
        except BaseException as error:
            result.set_exception(error)
    def validate_scene(self,request):return self.call('validate_scene',request)
    def load_scene(self,request):
        result=self.call('load_scene',request)
        self.models=self.backend.models
        self.metadata=self.backend.metadata
        return result
    def sync_objects(self,objects):return self.call('sync_objects',objects)
    def observe(self):return self.call('observe')
    def advance(self,positions,dt):return self.call('advance',positions,dt)
    def reset(self,positions,objects):return self.call('reset',positions,objects)
    def stop(self):return self.call('stop')
    def inventory(self):return self.call('inventory')
    def register_room(self,path,digest):return self.call('register_room',path,digest)
    def register_mesh(self,path,digest):return self.call('register_mesh',path,digest)

    def recording_start(self,project,session,body):return self.call('recording_start',project,session,body)
    def recording_get(self,project,rid):return self.call('recording_get',project,rid)
    def recording_list(self,project):return self.call('recording_list',project)
    def recording_file(self,project,rid):return self.call('recording_file',project,rid)
    def recording_stop(self):return self.call('recording_stop')
    def recording_end_session(self):return self.call('recording_end_session')
