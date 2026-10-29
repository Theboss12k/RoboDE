"""Install a Business App shortcut to an existing RoboDE server; no robot runtime copy."""
import argparse,hashlib,json,os,platform,plistlib,shutil,sys
from pathlib import Path
from urllib.parse import urlsplit,urlunsplit
BASE=Path(__file__).resolve().parent

def workspace_url(value):
    if any(ord(c)<32 or ord(c)==127 for c in value):raise ValueError('The server URL contains invalid characters')
    url=urlsplit(value.strip())
    if url.username or url.password or url.query or url.fragment:raise ValueError('Use the Business App URL without credentials, query parameters or fragments')
    if not url.hostname or url.scheme not in {'https','http'}:raise ValueError('Enter a complete HTTPS Business App URL')
    if url.scheme=='http' and url.hostname not in {'localhost','127.0.0.1','::1'}:raise ValueError('Use HTTPS for a shared server, phone camera and voice support')
    if url.path not in {'','/','/business','/business/','/login','/business/login'}:raise ValueError('Use the Business App server address, ending in /business/ or /login')
    # Accessing .port also validates malformed/non-numeric ports.
    url.port
    return urlunsplit((url.scheme,url.netloc,'/business/','',''))

def install(directory,url):
    url=workspace_url(url);directory=directory.expanduser().resolve()
    manifest=json.loads((BASE/'manifest.json').read_text())
    for name,digest in manifest['files'].items():
        path=BASE/name
        if not path.resolve().is_relative_to(BASE.resolve()) or not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest()!=digest:raise ValueError('Business installer checksum failed: '+name)
    if directory.exists() and any(directory.iterdir()) and not (directory/'business.json').is_file():raise ValueError('Choose an empty directory or an existing RoboDE Business installation')
    directory.mkdir(parents=True,exist_ok=True);directory.chmod(0o700)
    for name in ['room-capture.html','capture-sw.js','app-icon-192.png','START-HERE.html']:
        shutil.copyfile(BASE/name,directory/name)
    if platform.system()=='Darwin':
        shortcut=directory/'RoboDE Business.webloc';shortcut.write_bytes(plistlib.dumps({'URL':url}))
    elif os.name=='nt':
        shortcut=directory/'RoboDE Business.url';shortcut.write_text('[InternetShortcut]\nURL='+url+'\n',encoding='utf-8')
    else:
        shortcut=directory/'RoboDE Business.desktop'
        shortcut.write_text('[Desktop Entry]\nType=Link\nName=RoboDE Business\nURL='+url+'\nIcon='+str(directory/'app-icon-192.png')+'\n');shortcut.chmod(0o755)
    settings=directory/'business.json';settings.write_text(json.dumps({'url':url,'version':manifest['version']},indent=2));settings.chmod(0o600)
    print('Installed: '+str(shortcut)+'\nOpen it and sign in with your workspace access code.\nFor an app window or phone Home Screen icon, use Install app in the Business App.\nOffline room captures: '+str(directory/'room-capture.html'))
    return shortcut

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--url');parser.add_argument('--directory',type=Path,default=Path.home()/'RoboDE-Business');args=parser.parse_args()
    try:install(args.directory,args.url or input('Business App URL (for example https://workspace.example.com): '))
    except (OSError,ValueError) as error:print('Installation failed: '+str(error),file=sys.stderr);sys.exit(1)
