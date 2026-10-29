"""GPU usage heartbeats. Observations/health polls deliberately do not call touch()."""
import os
import time
from pathlib import Path
from services.api.storage import atomic_json


def touch(service):
    directory=os.getenv('ROBOT_IDE_ACTIVITY_DIR')
    if directory:
        atomic_json(Path(directory)/(service+'.json'),{'last_work':time.time()})


def guard_status():
    directory=os.getenv('ROBOT_IDE_ACTIVITY_DIR')
    if not directory or not os.access(directory,os.W_OK):return False
    path=Path(directory)/'guard.json'
    try:return 0<=time.time()-path.stat().st_mtime<45
    except OSError:return False


def idle_seconds():
    import json
    try:return json.loads((Path(os.environ['ROBOT_IDE_ACTIVITY_DIR'])/'guard.json').read_text())['idle_seconds']
    except (OSError,KeyError,ValueError):return None
