"""Build versioned, credential-free installers for Desktop, Server and Business."""
import argparse,hashlib,json,os,platform,shutil,subprocess,tempfile,zipfile
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
MODULES={'services','shared','simulation','integrations','web','robot_system','examples','task_library'}

def payload_files(root=ROOT):
    server=root/'SERVER_CLIENT/server'
    for p in sorted(server.rglob('*')):
        rel=p.relative_to(server)
        if not p.is_file() or p.is_symlink() or rel.parts[0] not in MODULES|{'requirements.txt','requirements-worker.txt','pyproject.toml'}:continue
        if any(part in {'runtime','projects','__pycache__','.pytest_cache','node_modules'} for part in rel.parts) and not (rel.parts[0]=='examples' and 'runtime' not in rel.parts and '__pycache__' not in rel.parts):continue
        if p.name.startswith('.') or p.suffix in {'.pyc','.sqlite3','.log'}:continue
        yield p,p.relative_to(root)
    for folder in ['SERVER_CLIENT/client/dist','BUSINESS_APP/dist']:
        for p in sorted((root/folder).rglob('*')):
            if p.is_file() and not p.is_symlink():yield p,p.relative_to(root)
    for folder in ['workers/robotics']:
        for p in sorted((root/folder).rglob('*')):
            if p.is_file() and not p.is_symlink() and '__pycache__' not in p.parts and p.suffix!='.pyc':yield p,p.relative_to(root)
    for filename in ['ELECTRON_APP/electron/main.cjs','ELECTRON_APP/electron/preload.cjs']:
        yield root/filename,Path(filename)
    yield root/'scripts/robotics_worker.py',Path('scripts/robotics_worker.py')

def checksum(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def seal(path):
    digest=checksum(path);path.with_suffix(path.suffix+'.sha256').write_text(digest+'  '+path.name+'\n')
    print(path.resolve(),flush=True)
    return {'filename':path.name,'sha256':digest,'bytes':path.stat().st_size}

def targets():
    for system in ['linux','windows']:
        for mode in ['server','desktop']:yield system,'x64',mode
    for arch in ['arm64','x64']:yield 'macos',arch,'desktop'

def business_bundle(output,version):
    name=f'RoboDE-Business-{version}-all-platforms';dest=output/(name+'.zip')
    files={p.name:p for p in (ROOT/'installers/business').iterdir() if p.is_file()}
    for filename in ['room-capture.html','capture-sw.js','app-icon-192.png']:files[filename]=ROOT/'BUSINESS_APP/dist'/filename
    hashes={rel:checksum(p) for rel,p in sorted(files.items())}
    with zipfile.ZipFile(dest,'w',compression=zipfile.ZIP_DEFLATED) as z:
        for rel,p in sorted(files.items()):z.write(p,f'{name}/{rel}')
        z.writestr(f'{name}/manifest.json',json.dumps({'format':1,'version':version,'mode':'business-companion','files':hashes},indent=2))
    return {**seal(dest),'edition':'business','platform':'all','architecture':'browser'}

def build(output,skip_build=False,dmg=False):
    if not skip_build:
        for task in ['server:build','business:build']:subprocess.run(['npm.cmd' if os.name=='nt' else 'npm','run',task],cwd=ROOT,check=True)
    if not (ROOT/'SERVER_CLIENT/client/dist/index.html').is_file() or not (ROOT/'BUSINESS_APP/dist/index.html').is_file():raise ValueError('Production frontends must be built first')
    output=Path(output);output.mkdir(parents=True,exist_ok=True)
    version=json.loads((ROOT/'package.json').read_text())['version']
    paths=list(payload_files());manifest={rel.as_posix():checksum(p) for p,rel in paths};packages=[]
    docs=['SCENE_RECORDING.md','RELEASE_0.4.0_RECORDING.md','NVIDIA_SCENE_RECORDING_DEMO_20261029.md']
    for system,arch,mode in targets():
        name=f'RoboDE-{mode.title()}-{version}-{system}-{arch}';dest=output/(name+'.zip')
        with zipfile.ZipFile(dest,'w',compression=zipfile.ZIP_DEFLATED) as z:
            for p,rel in paths:z.write(p,str(Path(name)/'payload'/rel))
            for filename in ['setup.py','run.py','README.md']:z.write(ROOT/'installers'/filename,f'{name}/{filename}')
            for filename in docs:z.write(ROOT/'docs'/filename,f'{name}/{filename}')
            wrapper='install-macos.command' if system=='macos' else f'install-{mode}.'+('ps1' if system=='windows' else 'sh')
            z.write(ROOT/'installers'/wrapper,f'{name}/{wrapper}')
            z.writestr(f'{name}/manifest.json',json.dumps({'format':1,'product':'RoboDE','version':version,'features':['native_scene_recording','business_installation'],'mode':mode,'platform':system,'architecture':arch,'files':manifest},indent=2))
        packages.append({**seal(dest),'edition':mode,'platform':system,'architecture':arch})
        if system=='macos' and dmg:
            if platform.system()!='Darwin':raise ValueError('DMG creation requires macOS; ZIP installers can be built anywhere')
            with tempfile.TemporaryDirectory(prefix='robode-dmg-') as tmp:
                # Only the verified, explicitly allowed build contents enter the disk image.
                with zipfile.ZipFile(dest) as z:z.extractall(tmp)
                wrapper_path=Path(tmp)/name/'install-macos.command';wrapper_path.chmod(0o755)
                image=output/(name+'.dmg')
                subprocess.run(['hdiutil','create','-quiet','-ov','-volname',f'RoboDE {version} {arch}','-srcfolder',str(Path(tmp)/name),'-format','UDZO',str(image.resolve())],check=True)
                packages.append({**seal(image),'edition':mode,'platform':system,'architecture':arch})
    packages.append(business_bundle(output,version))
    catalog={'product':'RoboDE','version':version,'kind':'bootstrap-installers','requires_network_at_setup':True,'signed':False,'packages':packages,'payload_files':len(manifest)}
    (output/'release.json').write_text(json.dumps(catalog,indent=2)+'\n')
    shutil.copyfile(ROOT/'installers/README.md',output/'README.md')
    links='\n'.join(f'<tr><td>{p["edition"].title()}</td><td>{p["platform"]} / {p["architecture"]}</td><td><a href="{p["filename"]}">{p["filename"]}</a></td><td><a href="{p["filename"]}.sha256">SHA-256</a></td></tr>' for p in packages)
    (output/'START-HERE.html').write_text('<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>RoboDE installers</title><style>html{color-scheme:dark}body{font:16px/1.6 system-ui;background:#080b10;color:#dce5f3;padding:5vw;max-width:1200px;margin:auto}a{color:#90baff}td,th{padding:12px;text-align:left;border-bottom:1px solid #29374a}table{border-collapse:collapse;width:100%}code{color:#a9caff}.table{overflow:auto}</style><h1>RoboDE '+version+'</h1><p>Plan, control and command your robot.</p><p><strong>Desktop:</strong> Electron IDE with local calculations. Windows/Linux use an RTX GPU for local Isaac; macOS connects to GCP or a remote RTX worker.</p><p><strong>Server:</strong> installs the browser IDE and Business App on one Windows/Linux RTX machine.</p><p><strong>Business:</strong> connects a computer or phone to that server; includes browser installation instructions, optional desktop shortcut setup and offline room capture.</p><p>Extract one ZIP and follow its README.md, or mount the Mac DMG and run install-macos.command. Python 3.12 is required for local Isaac. Mac remote setup accepts Python 3.12 or 3.13. Internet is required during setup. These installers are unsigned; Windows MSI/EXE installers and signing/notarization are not included.</p><div class="table"><table><tr><th>Edition</th><th>Target</th><th>Installer</th><th>Verify</th></tr>'+links+'</table></div><p>Credentials, private projects and cloud settings are never copied into these releases. Configure your own providers and connection after installing. Installing does not boot a GCP VM.</p></html>')
    return manifest

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--output',default=str(ROOT/'dist/releases'/(json.loads((ROOT/'package.json').read_text())['version']+'-installers')));p.add_argument('--skip-build',action='store_true');p.add_argument('--dmg',action='store_true');a=p.parse_args();build(a.output,a.skip_build,a.dmg)
