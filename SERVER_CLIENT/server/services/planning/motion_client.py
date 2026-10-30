"""Authenticated Linux motion service; unavailable workers never qualify hardware."""
import json
import os
from pathlib import Path
import base64
import httpx


class MotionUnavailable(ValueError): pass


class MotionClient:
    def __init__(self,store):self.store=store
    def configuration(self):
        path=self.store.runtime/'connections/motion.json'
        value=json.loads(path.read_text()) if path.exists() else {}
        return {'url':value.get('url','http://127.0.0.1:9120'),'token_env':value.get('token_env','ROBOT_DE_MOTION_TOKEN'),'version':value.get('version',1)}
    async def request(self,path,body=None):
        c=self.configuration();token=os.getenv(c['token_env'],'')
        token_path=self.store.runtime/'connections/motion.token'
        if not token and token_path.exists():token=token_path.read_text().strip()
        try:
            async with httpx.AsyncClient(timeout=120,trust_env=False) as client:
                r=await client.request('GET' if body is None else 'POST',c['url'].rstrip('/')+path,
                    json=body,headers={'Authorization':'Bearer '+token} if token else {})
                if r.is_error:
                    error='Motion worker: '+str(r.json().get('detail','request failed'))
                    if r.status_code in (422,409):raise ValueError(error)
                    raise MotionUnavailable(error)
                return r.json()
        except (httpx.HTTPError,OSError) as error:raise MotionUnavailable('Linux motion worker unavailable; start the MoveIt/Nav2 worker to qualify physical execution') from error
    async def health(self):
        try:return await self.request('/v2/health')
        except MotionUnavailable as error:return {'available':False,'message':str(error)}
    def model_payload(self,model):
        folder=self.store.model_folder(model['robot']['id']);metadata=model.get('source_import',{})
        source=folder/'source/package'
        files={}
        if source.is_dir():
            files={str(p.relative_to(source)):base64.b64encode(p.read_bytes()).decode() for p in source.rglob('*') if p.is_file()}
        return {'model':model,'urdf_path':metadata.get('urdf_path'),'files':files}
    async def plan(self,model,q,base,goal,objects):
        if not model.get('source_import') and goal['kind']!='base':raise MotionUnavailable('This model has no retained URDF; portable preview only, physical coverage incomplete')
        return await self.request('/v2/plan',{'robot':self.model_payload(model),'positions':q,'base_pose':base,'goal':goal,'objects':[o.model_dump(mode='json') for o in objects]})
    async def validate(self,models,frames,objects):
        return await self.request('/v2/validate',{'robots':{rid:self.model_payload(m) for rid,m in models.items()},
            'frames':[f.model_dump(mode='json') for f in frames],'objects':[o.model_dump(mode='json') for o in objects]})
