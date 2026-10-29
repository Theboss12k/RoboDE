"""Authenticated same-origin gateways; calculations run on the private Python server."""
import argparse
import contextlib
import hashlib
import hmac
import os
from pathlib import Path
import re
import secrets
import time
import httpx
from fastapi import FastAPI,Request,HTTPException
from fastapi.responses import HTMLResponse,RedirectResponse,Response,StreamingResponse,FileResponse,JSONResponse
from fastapi.staticfiles import StaticFiles

LOGIN='''<!doctype html><html lang="en"><meta name="viewport" content="width=device-width, initial-scale=1"><title>RoboDE Workspace · Sign in</title><style>*{box-sizing:border-box}html{color-scheme:dark}body{font:16px system-ui;background:#080b10;color:#d9e0eb;display:grid;place-items:center;min-height:100dvh;margin:0;padding:20px}form{background:#111722;border:1px solid #2d394c;padding:32px;border-radius:12px;width:100%;max-width:414px}h1{font-size:27px;margin:0 0 12px}p{line-height:1.5}label{display:block;margin-top:24px}input,button{width:100%;font:inherit;min-height:48px;padding:12px 16px;border:1px solid #2d394c;border-radius:8px;margin-top:12px}input{background:#0b111b;color:#d9e0eb}button{background:#90baff;color:#0a1525;font-weight:600;cursor:pointer}small{color:#a3b0c3}input:focus-visible,button:focus-visible{outline:2px solid #90baff;outline-offset:3px}[role=alert]{color:#ffb4ad;background:#301c24;border:1px solid #ffb4ad66;padding:12px;border-radius:8px;margin-top:16px;line-height:1.5}</style><form method="post" action="/login"><h1>RoboDE Workspace</h1><p>Your workspace, ready to work.</p><label>Workspace access code<input name="code" type="password" autocomplete="current-password" required autofocus></label><button>Open workspace</button><!--feedback--><p><small>Ask your workspace administrator for access.</small></p></form></html>'''

LOGO_PATH=Path(__file__).parent/'static/robot-logo.svg'
LOGIN=LOGIN.replace('<title>','<link rel="icon" type="image/svg+xml" href="/branding/robot-logo.svg"><title>',1).replace('<style>','<style>.login-logo{display:block;width:72px;height:auto;margin-bottom:20px}',1).replace('<h1>','<img class="login-logo" src="/branding/robot-logo.svg" alt=""><h1>',1)

def create_gateway(upstream='http://127.0.0.1:8765',dist=None,code=None,scope='business',transport=None):
    if scope not in {'business','ide'}:raise ValueError('Unknown gateway scope')
    home='/' if scope=='ide' else '/business/'
    login_path='/login' if scope=='ide' else '/business/login'
    cookie_name='robot_ide_session' if scope=='ide' else 'workspace_session'
    login_html=LOGIN.replace('RoboDE Workspace','RoboDE').replace('Your workspace, ready to work.','Connect to your shared team workspace.') if scope=='ide' else LOGIN
    if scope=='business':login_html=login_html.replace('action="/login"','action="/business/login"')
    if scope=='ide':
        login_html=login_html.replace('Ask your workspace administrator for access.','In the local desktop app, use Workspace → Show workspace access code, or Configuration → Workspace access. Otherwise, ask your workspace administrator.')
    code=code if code is not None else os.getenv('ROBOT_IDE_ACCESS_CODE' if scope=='ide' else 'BUSINESS_ACCESS_CODE','')
    if code and len(code)<12:raise ValueError(('ROBOT_IDE_ACCESS_CODE' if scope=='ide' else 'BUSINESS_ACCESS_CODE')+' must be at least 12 characters')
    secret=secrets.token_bytes(32);failed={}
    @contextlib.asynccontextmanager
    async def lifespan(app):
        app.state.client=httpx.AsyncClient(base_url=upstream,timeout=180,transport=transport)
        yield
        await app.state.client.aclose()
    app=FastAPI(title='RoboDE Workspace gateway',lifespan=lifespan,docs_url=None,openapi_url=None)
    def cookie():
        until=str(int(time.time())+8*3600)
        return until+'.'+hmac.new(secret,until.encode(),hashlib.sha256).hexdigest()
    def signed(value):
        try:
            until,signature=value.split('.')
            return int(until)>time.time() and hmac.compare_digest(signature,hmac.new(secret,until.encode(),hashlib.sha256).hexdigest())
        except (ValueError,AttributeError):return False
    @app.middleware('http')
    async def boundary(request,call_next):
        host=request.url.hostname
        if not code and host not in {'127.0.0.1','localhost','testserver','::1'}:return Response('Configure access before exposing this gateway.',status_code=403)
        if request.method not in {'GET','HEAD'} and request.headers.get('origin'):
            from urllib.parse import urlsplit
            origin=urlsplit(request.headers['origin'])
            if origin.netloc!=request.url.netloc:return Response('Untrusted origin',status_code=403)
        if code and request.url.path not in ({'/login',login_path,'/branding/robot-logo.svg'} | ({'/business/manifest.webmanifest','/business/app-icon-192.png','/business/app-icon-512.png'} if scope=='business' else set())) and not signed(request.cookies.get(cookie_name,'')):
            return Response('Sign in to your workspace.',status_code=401) if request.url.path.startswith('/api/') else RedirectResponse(login_path,status_code=303)
        response=await call_next(request)
        response.headers['X-Content-Type-Options']='nosniff';response.headers['Referrer-Policy']='same-origin'
        return response
    @app.get('/login',response_class=HTMLResponse)
    async def login():return login_html
    @app.get('/branding/robot-logo.svg')
    async def brand_logo():return FileResponse(LOGO_PATH,media_type='image/svg+xml',headers={'Cache-Control':'public, max-age=3600'})
    @app.post('/login')
    async def sign_in(request:Request):
        from urllib.parse import parse_qs
        ip=request.client.host;now=time.monotonic();attempts=[t for t in failed.get(ip,[]) if now-t<60]
        if len(attempts)>=10:raise HTTPException(429,'Wait a minute before trying again.')
        raw=bytearray()
        async for chunk in request.stream():
            raw.extend(chunk)
            if len(raw)>4096:raise HTTPException(413,'Request too large')
        entered=parse_qs(raw.decode()).get('code',[''])[0]
        if code and not hmac.compare_digest(entered,code):
            failed[ip]=attempts+[now]
            return HTMLResponse(login_html.replace('<!--feedback-->','<div role="alert">That code did not match. Please try again.</div>'),status_code=401)
        response=RedirectResponse(home,status_code=303);response.set_cookie(cookie_name,cookie(),max_age=8*3600,httponly=True,secure=request.url.scheme=='https',samesite='strict');return response
    if scope=='business':
        # Keep installed PWA authentication inside its /business/ navigation scope.
        app.add_api_route('/business/login',login,methods=['GET'],response_class=HTMLResponse)
        app.add_api_route('/business/login',sign_in,methods=['POST'])
    @app.post('/logout')
    async def logout():
        response=RedirectResponse(login_path,status_code=303);response.delete_cookie(cookie_name);return response
    @app.api_route('/api/business/{path:path}',methods=['GET','POST','PUT','DELETE'])
    async def api(path:str,request:Request):
        # Only the purpose-built business API is proxied; no registry, credentials,
        # adapter generation, model editing, live arming or IDE execution endpoints.
        if not re.fullmatch(r'[A-Za-z0-9_-]+(?:/[A-Za-z0-9_-]+)*',path):raise HTTPException(404)
        return await proxy('/api/business/'+path,request)
    @app.get('/api/projects/{project}/assets/{digest}')
    async def asset(project:str,digest:str,request:Request):
        if not re.fullmatch(r'[a-zA-Z0-9_-]{1,80}',project) or not re.fullmatch('[a-f0-9]{64}',digest):raise HTTPException(404)
        return await proxy(f'/api/projects/{project}/assets/{digest}',request)
    if scope=='ide':
        @app.post('/api/workspace/access')
        async def workspace_access():
            # The gateway's session boundary runs first; never proxy this credential
            # through the private runtime or expose it on the limited Business API.
            return JSONResponse({'access_code':code or None},headers={'Cache-Control':'no-store','Pragma':'no-cache'})

        @app.api_route('/api/{path:path}',methods=['GET','POST','PUT','PATCH','DELETE'])
        async def ide_api(path:str,request:Request):
            if not re.fullmatch(r'[A-Za-z0-9_.:-]+(?:/[A-Za-z0-9_.:-]+)*',path) or any(p in {'.','..'} for p in path.split('/')):raise HTTPException(404)
            return await proxy('/api/'+path,request)

    async def proxy(path,request):
        async def body():
            count=0
            async for chunk in request.stream():
                count+=len(chunk)
                if count>1024*1024*1024:raise HTTPException(413,'Upload exceeds 1 GB')
                yield chunk
        try:
            upstream_request=app.state.client.build_request(request.method,path,params=request.query_params,content=body(),headers={'Content-Type':request.headers.get('content-type','application/json'), **{name:request.headers[name] for name in ('range','if-range') if name in request.headers}},
                timeout=900 if request.method=='PUT' and path.endswith('/simulation') else 180)
            response=await app.state.client.send(upstream_request,stream=True)
        except httpx.HTTPError:return Response('{"detail":"The workspace runtime is unavailable. Ask the operator to start RoboDE."}',status_code=503,media_type='application/json')
        async def output():
            try:
                async for chunk in response.aiter_bytes():yield chunk
            finally:await response.aclose()
        return StreamingResponse(output(),status_code=response.status_code,headers={'Content-Type':response.headers.get('content-type','application/json'),'Cache-Control':'no-store', **{name:response.headers[name] for name in ('content-disposition','x-content-sha256','content-length','content-range','accept-ranges') if name in response.headers}})
    from services.validation.registry import REPOSITORY_ROOT
    dist=Path(dist or (REPOSITORY_ROOT/'SERVER_CLIENT/client/dist' if scope=='ide' else REPOSITORY_ROOT/'BUSINESS_APP/dist'))
    if scope=='ide':
        if not dist.is_dir():raise ValueError('Build the React IDE first: npm run server:build')
        app.mount('/',StaticFiles(directory=dist,html=True),name='react-ide')
    else:
        @app.get('/')
        async def home_page():return RedirectResponse('/business/')
        if dist.exists():app.mount('/business',StaticFiles(directory=dist,html=True),name='business')
    return app
