"""Process-wide ownership shared by plan execution and manual controls."""
import os


class ResourceLeases:
    def __init__(self):
        self.owners = {}

    def acquire(self, resources, owner):
        if any(self.owners.get(key) not in {None,owner} for key in resources):
            raise ValueError('This device or simulation cell is already controlled by another session')
        self.owners.update(dict.fromkeys(resources,owner))

    def release(self, owner):
        for key in [k for k,v in self.owners.items() if v == owner]:
            del self.owners[key]

    def ensure_free(self, resources):
        if any(key in self.owners for key in resources):
            raise ValueError('Close the active manual control session or stop the plan before changing this environment')


def environment_resource(project_id, backend):
    if backend == 'isaac_sim':
        return 'isaac:' + os.getenv('ISAAC_WORKER_URL','http://127.0.0.1:9100').rstrip('/')
    return 'environment:' + project_id
