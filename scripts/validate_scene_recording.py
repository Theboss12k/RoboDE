"""Bounded acceptance check of an already connected native Isaac camera; never boot a VM."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import httpx


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--project',required=True)
    parser.add_argument('--api',default='http://127.0.0.1:8765')
    parser.add_argument('--seconds',type=int,default=5,choices=range(1,61))
    parser.add_argument('--output',type=Path,default=Path('artifacts/native-scene-recording'))
    args=parser.parse_args()
    from services.api.storage import safe_id
    project=safe_id(args.project)
    base=f'/api/projects/{project}'
    # Private runtime API, not the publicly authenticated gateway. Do not put
    # access codes or worker tokens in command arguments or reports.
    from urllib.parse import urlparse
    url=urlparse(args.api)
    if url.scheme!='http' or url.hostname not in {'127.0.0.1','localhost','::1'} or url.username or url.password:
        parser.error('Use the loopback private RoboDE runtime API on this host')
    with httpx.Client(base_url=args.api,timeout=180) as client:
        def request(method,path,**kwargs):
            response=client.request(method,path,**kwargs)
            response.raise_for_status()
            return response.json()
        capability=request('GET',base+'/recordings/capabilities')
        if not capability.get('available'):
            raise SystemExit(capability.get('reason','Native recording is unavailable'))
        detail=request('GET',base)
        worker=detail.get('worker') or {}
        if detail.get('adapter')!='isaac_sim' or not detail.get('environment_connected') or worker.get('engine')!='isaac_sim' or not worker.get('physics_available'):
            raise SystemExit('Acceptance requires a connected native Isaac Sim GPU worker; contract fixtures are rejected')
        record=request('POST',base+'/recordings',json={'resolution':'640x360','fps':5,'duration_seconds':args.seconds})
        rid=record['id']
        deadline=time.monotonic()+args.seconds+150
        while time.monotonic()<deadline:
            time.sleep(1)
            record=request('GET',base+'/recordings/'+rid)
            if record['status'] in {'failed','interrupted'}:
                raise SystemExit(record.get('error','Native capture failed'))
            if record.get('cached'):
                break
        else:
            # Best effort bounded cleanup; never shut down a VM being shared
            # by another session or discard its persisted recording history.
            try:request('POST',base+'/recordings/'+rid+'/stop')
            except httpx.HTTPError:pass
            raise SystemExit('Native MP4 export did not finish within its deadline')
        response=client.get(base+'/recordings/'+rid+'/file')
        response.raise_for_status()
        if response.headers.get('content-type')!='video/mp4':
            raise SystemExit('Server returned a non-video response')
        digest=hashlib.sha256(response.content).hexdigest()
        if digest!=record['sha256']:
            raise SystemExit('Downloaded MP4 checksum mismatch')
        args.output.mkdir(parents=True,exist_ok=True)
        path=args.output/(rid+'.mp4')
        path.write_bytes(response.content)
        import imageio_ffmpeg
        reader=imageio_ffmpeg.read_frames(str(path),pix_fmt='rgb24')
        try:
            video=next(reader)
            first=next(reader)
        finally:reader.close()
        if not first or max(first)==0:
            raise SystemExit('Camera returned a black frame; inspect scene lighting and camera pose')
        report={'status':'passed','scope':'native camera RGB capture and MP4 decode; robot motion was not commanded or certified',
                'recording':record,'worker':{k:worker.get(k) for k in ('engine','simulator_version','asset_sha256')},
                'decoded':video,'first_frame_mean':sum(first)/len(first),'sha256':digest}
        (args.output/(rid+'.json')).write_text(json.dumps(report,indent=2))
        print(path.resolve())
        print('Native camera video captured and decoded. No robot movement was commanded by this check.')


if __name__=='__main__':main()
