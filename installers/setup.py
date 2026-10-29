"""RoboDE bootstrap installer: local RTX on Windows/Linux, remote Isaac on macOS."""
import argparse,csv,hashlib,io,json,os,platform,plistlib,secrets,shlex,shutil,stat,subprocess,sys,urllib.request,venv,zipfile
from pathlib import Path
BASE=Path(__file__).resolve().parent
EULA='https://docs.omniverse.nvidia.com/eula'
REQUIREMENTS='https://docs.isaacsim.omniverse.nvidia.com/6.2.0/installation/requirements.html'

def run(args,**kw):subprocess.run([str(a) for a in args],check=True,**kw)
def private(path,data):
    path.parent.mkdir(parents=True,exist_ok=True);path.write_text(json.dumps(data,indent=2));path.chmod(0o600)

def check_gpu():
    if platform.system() not in {'Linux','Windows'} or platform.machine().lower() not in {'x86_64','amd64'}:raise ValueError('These installers require Ubuntu x64 or Windows 11 x64. macOS uses the existing remote/GCP configuration.')
    if platform.system()=='Windows' and sys.getwindowsversion().build<22000:raise ValueError('Windows 11 is required')
    if platform.system()=='Linux':
        osinfo=platform.freedesktop_os_release()
        if osinfo.get('ID')!='ubuntu' or osinfo.get('VERSION_ID') not in {'22.04','24.04'}:raise ValueError('Use supported Ubuntu 22.04/24.04; 24.04 is recommended. '+REQUIREMENTS)
    try:
        text=subprocess.check_output(['nvidia-smi','--query-gpu=name,memory.total,driver_version','--format=csv,noheader,nounits'],text=True)
    except (OSError,subprocess.CalledProcessError) as e:raise ValueError('Install the NVIDIA production graphics driver first; nvidia-smi must work. '+REQUIREMENTS) from e
    rows=list(csv.reader(io.StringIO(text)));supported=[]
    for name,memory,driver in rows:
        if any(part in name.upper() for part in ['A100','H100','H200','B200']):continue
        if ('RTX' in name.upper() or 'L4' in name.upper() or 'L40' in name.upper()) and float(memory)>=15000:supported.append(name.strip())
    if not supported:raise ValueError('Isaac 6.2 needs supported RT cores and a suitable GPU (published baseline: RTX 4080, 16 GB VRAM). Older/smaller RTX cards are not guaranteed. '+REQUIREMENTS)
    print('GPU detected: '+', '.join(supported)+'. NVIDIA compatibility checks still apply; this is not a physics certification.')

def verify_payload(manifest):
    for relative,digest in manifest['files'].items():
        p=(BASE/'payload'/relative).resolve()
        if not p.is_relative_to((BASE/'payload').resolve()) or not p.is_file() or hashlib.sha256(p.read_bytes()).hexdigest()!=digest:raise ValueError('Installer payload checksum failed: '+relative)

def current_target():
    system={'Darwin':'macos','Windows':'windows','Linux':'linux'}.get(platform.system())
    arch={'arm64':'arm64','aarch64':'arm64','x86_64':'x64','amd64':'x64'}.get(platform.machine().lower())
    if not system or not arch:raise ValueError('Unsupported operating system or architecture')
    return system,arch

def extract_electron(archive,target):
    """Preserve macOS framework symlinks without allowing archive path escapes."""
    target.mkdir(parents=True,exist_ok=True)
    with zipfile.ZipFile(archive) as z:
        links=[]
        for item in z.infolist():
            dest=target/item.filename
            if not dest.resolve().is_relative_to(target.resolve()):raise ValueError('Unsafe Electron archive path')
            mode=item.external_attr>>16
            if stat.S_ISLNK(mode):
                link=z.read(item).decode()
                if Path(link).is_absolute() or not (dest.parent/link).resolve().is_relative_to(target.resolve()):raise ValueError('Unsafe Electron archive symlink')
                links.append((dest,link));continue
            if item.is_dir():dest.mkdir(parents=True,exist_ok=True);continue
            dest.parent.mkdir(parents=True,exist_ok=True)
            with z.open(item) as src,dest.open('wb') as out:shutil.copyfileobj(src,out)
            if os.name!='nt' and mode:dest.chmod(mode&0o777)
        for dest,link in links:
            dest.parent.mkdir(parents=True,exist_ok=True)
            # Never replace files/directories or write through another link.
            if dest.exists() or dest.is_symlink():raise ValueError('Conflicting Electron archive symlink')
            if not dest.parent.resolve().is_relative_to(target.resolve()):raise ValueError('Unsafe Electron archive symlink')
            dest.symlink_to(link)

def electron_install(folder,archive_source=None):
    version='45.0.0';system,arch=current_target()
    electron_platform={'windows':'win32','macos':'darwin','linux':'linux'}[system]
    name=f'electron-v{version}-{electron_platform}-{arch}.zip'
    origin=f'https://github.com/electron/electron/releases/download/v{version}/'
    print('Verifying official Electron '+version+' checksums…',flush=True)
    checks=urllib.request.urlopen(origin+'SHASUMS256.txt',timeout=30).read().decode()
    expected=next((parts[0] for line in checks.splitlines() if len(parts:=line.split())==2 and parts[-1].lstrip('*')==name),None)
    if not expected:raise ValueError('Official Electron checksum is missing for '+name)
    archive=folder/'electron.zip'
    try:
        # Existing Electron download caches are useful on developer machines; every
        # candidate is still checked against the official release checksum.
        cached=Path(archive_source).expanduser() if archive_source else None
        if not cached:
            cache_root=Path.home()/('Library/Caches/electron' if system=='macos' else '.cache/electron')
            if system=='windows':cache_root=Path(os.getenv('LOCALAPPDATA',str(Path.home())))/'electron/Cache'
            cached=next((p for p in cache_root.glob('*/'+name) if p.is_file()),None)
        if cached:
            print('Using Electron archive: '+str(cached),flush=True)
            if cached.resolve()==archive.resolve():raise ValueError('Choose an Electron archive outside the installation directory')
            shutil.copyfile(cached,archive)
        else:
            print('Downloading '+name+'…',flush=True)
            with urllib.request.urlopen(origin+name,timeout=30) as r,archive.open('wb') as f:shutil.copyfileobj(r,f)
        if hashlib.sha256(archive.read_bytes()).hexdigest()!=expected:raise ValueError('Electron download checksum mismatch')
        # Keep the current installation intact until its replacement is verified.
        target=folder/'electron-new'
        if target.exists():shutil.rmtree(target)
        extract_electron(archive,target)
        previous=folder/'electron'
        if previous.exists():shutil.rmtree(previous)
        target.rename(previous)
        executable=previous/({'windows':'electron.exe','macos':'Electron.app/Contents/MacOS/Electron','linux':'electron'}[system])
        if os.name!='nt':
            for p in [executable,previous/'chrome-sandbox',previous/'chrome_crashpad_handler']:
                if p.exists():p.chmod(0o755)
        return executable
    finally:archive.unlink(missing_ok=True)

def mac_app(directory,python,version):
    # User-owned application; no administrator privileges or system Python changes.
    app=directory/'RoboDE.app';contents=app/'Contents';(contents/'MacOS').mkdir(parents=True,exist_ok=True)
    (contents/'Info.plist').write_bytes(plistlib.dumps({'CFBundleName':'RoboDE','CFBundleDisplayName':'RoboDE','CFBundleIdentifier':'com.robode.desktop','CFBundleVersion':version,'CFBundleShortVersionString':version,'CFBundlePackageType':'APPL','CFBundleExecutable':'RoboDE','NSHighResolutionCapable':True}))
    launcher=contents/'MacOS/RoboDE'
    logs=directory/'data/desktop-logs'
    launcher.write_text('#!/bin/sh\numask 077\nexport PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"\nmkdir -p '+shlex.quote(str(logs))+'\n'+shlex.quote(str(python))+' '+shlex.quote(str(directory/'run.py'))+' >> '+shlex.quote(str(logs/'startup.log'))+' 2>&1\nstatus=$?\nif [ "$status" -ne 0 ]; then\n  /usr/bin/osascript -e \'display alert "RoboDE could not start" message "Another installation may already be running. Open start.sh in your RoboDE installation to see the error, or check data/desktop-logs/startup.log." as critical\'\nfi\nexit "$status"\n')
    launcher.chmod(0o755)
    return app

def main():
    p=argparse.ArgumentParser();p.add_argument('--mode',choices=['server','desktop'],required=True);p.add_argument('--directory',type=Path,default=Path.home()/'RobotIDE');p.add_argument('--isaac-python',type=Path);p.add_argument('--install-isaac',action='store_true');p.add_argument('--accept-nvidia-eula',action='store_true');p.add_argument('--service',action='store_true');p.add_argument('--configure-sandbox',action='store_true');p.add_argument('--check',action='store_true');p.add_argument('--electron-archive',type=Path,help='Use a cached official Electron ZIP, checked against its published checksum');p.add_argument('--remote-isaac',action='store_true',help='Use built-in simulation and configure a remote/GCP Isaac worker in the IDE');a=p.parse_args()
    system,arch=current_target()
    remote=a.remote_isaac or system=='macos'
    manifest=json.loads((BASE/'manifest.json').read_text());verify_payload(manifest)
    if a.mode!=manifest['mode'] or system!=manifest['platform'] or arch!=manifest['architecture']:raise ValueError('Download the matching installer edition, OS and CPU architecture')
    if a.service and (a.mode!='server' or system!='linux'):raise ValueError('--service requires the Linux server edition')
    if a.configure_sandbox and (a.mode!='desktop' or system!='linux'):raise ValueError('--configure-sandbox requires the Linux desktop edition')
    if remote and (a.install_isaac or a.isaac_python):raise ValueError('Remote mode cannot install or configure a local Isaac runtime')
    if not remote:check_gpu()
    if a.check:
        print('Payload verified. '+('Remote/GCP Isaac mode: no local NVIDIA runtime required.' if remote else 'Local RTX mode.'));return
    if (not remote and sys.version_info[:2]!=(3,12)) or (remote and sys.version_info[:2] not in {(3,12),(3,13)}):raise ValueError('Use Python 3.12 for local RTX; Python 3.12 or 3.13 for remote mode.')
    if not remote and not a.accept_nvidia_eula:raise ValueError('Review '+EULA+' then rerun with --accept-nvidia-eula if you agree. No license acceptance is assumed.')
    if not remote and not a.install_isaac and not a.isaac_python:raise ValueError('Choose --isaac-python PATH to Isaac 6.2 Python or --install-isaac to install its dedicated environment.')
    directory=a.directory.expanduser().resolve()
    if any(ch in str(directory) for ch in '\r\n\0'):raise ValueError('Installation paths cannot contain control characters')
    if directory.exists() and any(directory.iterdir()) and not any((directory/name).exists() for name in ['installation.json','.robot-ide-installing']):raise ValueError('Choose an empty directory or an existing Robot IDE installation')
    directory.mkdir(parents=True,exist_ok=True)
    (directory/'.robot-ide-installing').touch(mode=0o600)
    if os.name=='nt':
        # Limit the installation and generated credentials to this Windows user.
        run(['icacls',directory,'/reset'])
        run(['icacls',directory,'/inheritance:r','/grant:r',os.environ['USERNAME']+':(OI)(CI)F'])
    directory.chmod(0o700)
    # Versioned code lets upgrades keep the prior release; data is never overwritten.
    release=directory/'releases'/hashlib.sha256((BASE/'manifest.json').read_bytes()).hexdigest()[:12]
    release.mkdir(parents=True,exist_ok=True)
    for rel in manifest['files']:
        target=release/rel;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(BASE/'payload'/rel,target)
    runtime=directory/'environment';venv.EnvBuilder(with_pip=True).create(runtime)
    python=runtime/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
    run([python,'-m','pip','install','--upgrade','pip']);run([python,'-m','pip','install','-r',release/'SERVER_CLIENT/server/requirements.txt'])
    # Do not resolve the venv Python symlink to the system interpreter.
    isaac=Path(os.path.abspath(a.isaac_python.expanduser())) if a.isaac_python else None
    if a.install_isaac:
        if shutil.disk_usage(directory).free<60*1024**3:raise ValueError('Allow at least 60 GiB free for Isaac installation and caches')
        env=directory/'isaac-environment';venv.EnvBuilder(with_pip=True).create(env);isaac=env/('Scripts/python.exe' if os.name=='nt' else 'bin/python')
        run([isaac,'-m','pip','install','--upgrade','pip']);run([isaac,'-m','pip','install','torch==2.11.0','--index-url','https://download.pytorch.org/whl/cu128']);run([isaac,'-m','pip','install','isaacsim[all,extscache]==6.2.0.0','--extra-index-url','https://pypi.nvidia.com'])
    if not remote:
        if not isaac or not isaac.is_file():raise ValueError('Isaac Python launcher does not exist')
        # The local launcher supports .bat, while installer subprocess execution is
        # intentionally argv-only. Use Isaac's Python executable for installation.
        if isaac.suffix.lower() in {'.bat','.cmd','.sh'}:raise ValueError('For setup provide the Isaac environment Python executable, not its shell/batch wrapper')
        run([isaac,'-m','pip','install','-r',release/'SERVER_CLIENT/server/requirements-worker.txt'])
        versions=subprocess.check_output([isaac,'-c',"import importlib.metadata as m;print(m.version('isaacsim-kernel'))"],text=True).strip()
        if not versions.startswith('6.2.'):raise ValueError('This bridge requires Isaac Sim 6.2.x')
    data=directory/'data';data.mkdir(exist_ok=True)
    if not (data/'projects').exists():
        (data/'projects').mkdir()
        for example in ['apple_transfer','dual_arm_cell']:
            shutil.copytree(release/'SERVER_CLIENT/server/examples/projects'/example,data/'projects'/example)
    configuration=data/'robot_system/runtime/connections/isaac.json'
    if not remote and not configuration.exists():private(configuration,{'deployment':'local','url':'http://127.0.0.1:9100','token':secrets.token_urlsafe(32),'load_scene':True,'on_demand':False,'local_launcher':str(isaac),'local_source_kind':'automatic','local_source':'','local_gui':a.mode=='desktop'})
    access=directory/'access.json'
    if not access.exists():private(access,{'access_code':secrets.token_urlsafe(24)})
    executable=electron_install(directory,a.electron_archive) if a.mode=='desktop' else None
    if executable and system=='linux' and a.configure_sandbox:
        run(['sudo','chown','root:root',executable.parent/'chrome-sandbox']);run(['sudo','chmod','4755',executable.parent/'chrome-sandbox'])
    if executable:
        app=release/'ELECTRON_APP';(app/'package.json').write_text(json.dumps({'name':'robot-ide','version':manifest['version'],'main':'electron/main.cjs'}))
    shutil.copyfile(BASE/'run.py',directory/'run.py')
    settings={'mode':a.mode,'release':str(release),'data':str(data),'isaac_python':str(isaac) if isaac else None,'python':str(python),'electron':str(executable) if executable else None,'host':'0.0.0.0' if a.mode=='server' else '127.0.0.1','nvidia_eula_accepted':not remote and a.accept_nvidia_eula,'version':manifest['version'],'simulation':'remote' if remote else 'local'}
    private(directory/'installation.json',settings)
    if os.name=='nt':
        (directory/'Start Robot IDE.cmd').write_text('@echo off\r\n"'+str(python)+'" "'+str(directory/'run.py')+'"\r\n pause\r\n')
    else:
        launcher=directory/'start.sh';launcher.write_text('#!/bin/sh\nexec '+shlex.quote(str(python))+' '+shlex.quote(str(directory/'run.py'))+'\n');launcher.chmod(0o755)
        if system=='macos':print('Desktop app: '+str(mac_app(directory,python,manifest['version'])))
        if a.service:
            if a.mode!='server':raise ValueError('--service is for the hosted server; desktop starts in the graphical session')
            unit=Path.home()/'.config/systemd/user/robot-ide.service';unit.parent.mkdir(parents=True,exist_ok=True)
            # systemd has its own quoting/specifier rules, separate from shell quoting.
            def unitarg(value):return '"'+str(value).replace('\\','\\\\').replace('"','\\"').replace('%','%%')+'"'
            unit.write_text('[Unit]\nDescription=Robot IDE and Business server\nAfter=network-online.target\n[Service]\nExecStart='+unitarg(python)+' '+unitarg(directory/'run.py')+'\nRestart=on-failure\nRestartSec=5\nTimeoutStopSec=75\n[Install]\nWantedBy=default.target\n')
            run(['systemctl','--user','daemon-reload']);run(['systemctl','--user','enable','--now','robot-ide.service'])
            print('For service startup without login, an administrator can enable user lingering with loginctl enable-linger USER.')
    (directory/'.robot-ide-installing').unlink(missing_ok=True)
    print('Installed at '+str(directory)+'\nLogin code: '+str(access)+'\nIDE: http://localhost:8081'+('\nBusiness: http://SERVER_IP:8080 (configure HTTPS for phone camera/voice)' if a.mode=='server' else '\nDesktop mode: no LAN listener. Import phone room capture files in Environment.'))

if __name__=='__main__':
    try:main()
    except (ValueError,OSError,subprocess.CalledProcessError) as error:print('Installation failed: '+str(error),file=sys.stderr);sys.exit(1)
