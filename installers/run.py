"""Installed process supervisor. One API authority; separate authenticated web scopes."""
import argparse,json,os,signal,socket,subprocess,sys,time,urllib.request
from pathlib import Path
BASE=Path(__file__).resolve().parent

def environment(settings,port_offset=0):
    release=Path(settings['release'])
    return {**os.environ,'PYTHONPATH':os.pathsep.join([str(release/'SERVER_CLIENT/server'),str(release)]),
            'ROBOT_IDE_ACCESS_CODE_FILE':str(BASE/'access.json'),
            'ROBOT_IDE_DATA_DIR':settings['data'],'ROBOT_IDE_UPSTREAM':f'http://127.0.0.1:{8765+port_offset}',
            'OMNI_KIT_ACCEPT_EULA':'yes' if settings.get('nvidia_eula_accepted') else '',
            'ROBOT_IDE_DEPLOYMENT':'installed','ROBOT_IDE_ELECTRON_USER_DATA':str(Path(settings['data'])/'desktop')}

def main():
    p=argparse.ArgumentParser();p.add_argument('--component',choices=['api','ide','business']);p.add_argument('--check',action='store_true');p.add_argument('--port-offset',type=int,default=0,help='Offset all three ports for an isolated installation');args=p.parse_args()
    if not 0<=args.port_offset<=56000:raise ValueError('Port offset must be between 0 and 56000')
    ports={'api':8765+args.port_offset,'ide':8081+args.port_offset,'business':8080+args.port_offset}
    settings=json.loads((BASE/'installation.json').read_text());release=Path(settings['release'])
    env=environment(settings,args.port_offset)
    if args.check:
        assert (release/'SERVER_CLIENT/client/dist/index.html').is_file()
        assert (release/'BUSINESS_APP/dist/index.html').is_file()
        assert Path(settings['python']).is_file()
        print('Installation paths and production web assets verified. Native GPU validation requires starting Isaac.');return
    if args.component:
        import uvicorn
        if args.component=='api':
            from services.api.main import create_app
            app=create_app();port=ports['api'];host='127.0.0.1'
        else:
            from web.gateway import create_gateway
            code=json.loads((BASE/'access.json').read_text())['access_code']
            app=create_gateway(upstream=env['ROBOT_IDE_UPSTREAM'],code=code,scope=args.component)
            port=ports[args.component];host=settings['host']
        uvicorn.run(app,host=host,port=port,workers=1);return
    # No installation starts if one of its authority/entrypoint ports is occupied.
    for port in ports.values():
        with socket.socket() as s:
            try:s.bind(('0.0.0.0',port))
            except OSError as e:raise ValueError(f'Port {port} is already in use. Stop the other Robot IDE installation first.') from e
    children=[];stopping=False
    def stop(*_):
        nonlocal stopping
        stopping=True
    for sig in [signal.SIGINT,signal.SIGTERM]:signal.signal(sig,stop)
    if os.name=='nt':signal.signal(signal.SIGBREAK,stop)
    def spawn(command):
        child=subprocess.Popen(command,cwd=release,env=env,**({'creationflags':subprocess.CREATE_NEW_PROCESS_GROUP} if os.name=='nt' else {'start_new_session':True}))
        children.append(child);return child
    def ready(url):
        deadline=time.monotonic()+45
        while not stopping and time.monotonic()<deadline:
            if any(c.poll() is not None for c in children):raise ValueError('A runtime exited during startup. See the service log.')
            try:
                with urllib.request.urlopen(url,timeout=1) as r:
                    if r.status==200:return
            except OSError:pass
            time.sleep(.25)
        raise ValueError('Runtime did not become ready: '+url)
    try:
        command=[settings['python'],str(BASE/'run.py'),'--port-offset',str(args.port_offset)]
        spawn(command+['--component','api']);ready(f'http://127.0.0.1:{ports["api"]}/api/health')
        for component,port in [('ide',ports['ide']),('business',ports['business'])]:spawn(command+['--component',component]);ready(f'http://127.0.0.1:{port}/login')
        print(f'IDE: http://localhost:{ports["ide"]} | Business: http://localhost:{ports["business"]}\nAccess code file: '+str(BASE/'access.json'),flush=True)
        if settings['mode']=='desktop':
            env['ROBOT_IDE_ORIGIN']=f'http://127.0.0.1:{ports["ide"]}';env['ROBOT_IDE_DEV']='0'
            desktop=spawn([settings['electron'],str(release/'ELECTRON_APP')])
        else:
            desktop=None
            print('LAN service active. Configure HTTPS before exposing it to the internet or using mobile camera/microphone.',flush=True)
        while not stopping:
            exited=[c for c in children if c.poll() is not None]
            if exited:
                if desktop in exited and desktop.returncode==0:break
                raise ValueError('A supervised process exited; stopping the remaining services.')
            time.sleep(.5)
    finally:
        # Web gateways first, then API: its lifespan closes adapter/Isaac workers.
        for c in reversed(children):
            if c.poll() is None:
                try:c.send_signal(signal.CTRL_BREAK_EVENT if os.name=='nt' else signal.SIGTERM)
                except OSError:pass
        deadline=time.monotonic()+65
        for c in children:
            try:c.wait(timeout=max(0,deadline-time.monotonic()))
            except subprocess.TimeoutExpired:
                if os.name=='nt':subprocess.run(['taskkill','/PID',str(c.pid),'/T','/F'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                else:os.killpg(c.pid,signal.SIGKILL)

if __name__=='__main__':
    # Child components inherit the data/code environment set by the supervisor.
    try:main()
    except (OSError,ValueError) as e:print('Robot IDE: '+str(e),file=sys.stderr);sys.exit(1)
