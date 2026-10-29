"""Guest watchdog: keeps working without the web app or a connection to the Mac.
Install as root systemd service. Shutdown is OS poweroff, never delete/suspend.
"""
import argparse
import json
from pathlib import Path
import subprocess
import time
from services.api.storage import atomic_json


def should_stop(directory,started,now,idle_seconds):
    last=started
    for path in Path(directory).glob('*.json'):
        if path.name=='guard.json':continue
        try:
            stamp=float(json.loads(path.read_text())['last_work'])
            # Reject future timestamps and stale heartbeat files from a previous boot.
            if started<=stamp<=now:last=max(last,stamp)
        except (OSError,ValueError,KeyError,TypeError):pass
    return now-last>=idle_seconds


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--directory',default='/var/lib/robot-ide/activity');parser.add_argument('--idle-seconds',type=int,default=600);args=parser.parse_args()
    if args.idle_seconds<60:parser.error('Idle timeout must be at least 60 seconds')
    directory=Path(args.directory);directory.mkdir(parents=True,exist_ok=True);started=time.time()
    while True:
        now=time.time()
        if should_stop(directory,started,now,args.idle_seconds):
            # With Type=exec systemd does not restart this on a successful poweroff.
            subprocess.run(['systemctl','poweroff'],check=True)
            return
        atomic_json(directory/'guard.json',{'checked_at':now,'idle_seconds':args.idle_seconds})
        time.sleep(15)

if __name__=='__main__':main()
