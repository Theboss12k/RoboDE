"""Wake the configured cloud VM, discover current HTTPS app links, then release SSH."""
import argparse,asyncio,json,os,time
from pathlib import Path
import httpx
from services.api.storage import Storage,atomic_json
from integrations.gcp.lifecycle import GpuLifecycle

async def main():
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['start','status']);args=parser.parse_args()
    os.environ.setdefault('CLOUDSDK_CORE_HTTP_TIMEOUT','30');os.environ.setdefault('CLOUDSDK_CORE_MAX_RETRIES','0')
    store=Storage();lifecycle=GpuLifecycle(store)
    path=store.runtime/'connections/cloud-access.json'
    try:
        if args.command=='status':
            status=await lifecycle.snapshot(refresh=True)
            print(json.dumps({'status':status['status'],'message':status['message'],'access_file':str(path)}));return
        await lifecycle.ensure_running()
        if lifecycle.state['status']!='ready':raise ValueError(lifecycle.state['message'])
        config=lifecycle.configuration();deadline=time.monotonic()+90;apps={}
        async with httpx.AsyncClient(timeout=15) as client:
            while time.monotonic()<deadline:
                r=await client.get(config['url']+'/v1/health',headers={'Authorization':'Bearer '+config['token']});r.raise_for_status();apps=r.json().get('cloud_apps',{})
                if all(apps.get(k,'').startswith('https://') for k in ('ide','business')):
                    responses=await asyncio.gather(*(client.get(apps[k]+'/login') for k in ['ide','business']))
                    if all(r.status_code==200 for r in responses):break
                await asyncio.sleep(3)
            else:raise ValueError('VM started, but protected HTTPS apps are not ready. Check the cloud tunnel services. The idle shutdown remains enabled.')
        data=json.loads(path.read_text()) if path.exists() else {}
        data.update(ide_url=apps['ide'],business_url=apps['business'],vm=config['gcp_instance'],zone=config['gcp_zone'])
        atomic_json(path,data);path.chmod(0o600)
        print(json.dumps({'status':'ready','ide':apps['ide'],'business':apps['business'],'access_file':str(path),'idle_minutes':config['idle_minutes'],'maximum_minutes':config['max_session_minutes']}))
    finally:await lifecycle.close()

if __name__=='__main__':asyncio.run(main())
