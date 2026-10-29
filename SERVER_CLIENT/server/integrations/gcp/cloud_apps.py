"""Non-secret public session links, discovered from the VM's tunnel logs."""
import json,os,re,time
from pathlib import Path

def links():
    path=os.getenv('ROBOT_IDE_CLOUD_LINKS','')
    if not path:return {}
    try:
        value=json.loads(Path(path).read_text())
        return {k:v for k,v in value.items() if k in {'ide','business'} and isinstance(v,str) and re.fullmatch(r'https://[a-z0-9-]+\.trycloudflare\.com',v)}
    except (OSError,ValueError):return {}

def main():
    root=Path('/var/lib/robot-ide-cloud');path=root/'links.json'
    from services.api.storage import atomic_json
    while True:
        result={}
        for mode in ['ide','business']:
            log=root/(mode+'-tunnel.log')
            try:
                matches=re.findall(r'https://[a-z0-9-]+\.trycloudflare\.com',log.read_text()[-100000:])
                if matches:result[mode]=matches[-1]
            except OSError:pass
        atomic_json(path,result)
        time.sleep(3)

if __name__=='__main__':main()
