import importlib.util,json,subprocess,sys,zipfile
from pathlib import Path
import pytest
ROOT=Path(__file__).resolve().parents[2]
def module(name):
    spec=importlib.util.spec_from_file_location(name,ROOT/'installers'/f'{name}.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def test_release_allowlist_excludes_private_runtime_and_saved_projects():
    m=module('build');files=list(m.payload_files())
    assert files
    for _,relative in files:
        parts=relative.parts
        assert 'runtime' not in parts and '.env' not in parts and 'node_modules' not in parts
        assert 'projects' not in parts or 'examples' in parts
    assert any(str(p).endswith('web/static/robot-logo.svg') for _,p in files)
    assert any(str(p).endswith('task_library/manipulation/pick_place.yaml') for _,p in files)

def test_installer_preflight_rejects_non_rt_and_low_memory(monkeypatch):
    m=module('setup');monkeypatch.setattr(m.platform,'system',lambda:'Linux');monkeypatch.setattr(m.platform,'machine',lambda:'x86_64');monkeypatch.setattr(m.platform,'freedesktop_os_release',lambda:{'ID':'ubuntu','VERSION_ID':'24.04'})
    for gpu in ['NVIDIA A100, 40960, 595.99','NVIDIA RTX 3060, 8192, 595.99']:
        monkeypatch.setattr(m.subprocess,'check_output',lambda *a,**kw:gpu)
        with pytest.raises(ValueError,match='RT cores'):m.check_gpu()
    monkeypatch.setattr(m.subprocess,'check_output',lambda *a,**kw:'NVIDIA L4, 23034, 595.99')
    m.check_gpu()

def test_installed_runtime_data_override_is_used(tmp_path,monkeypatch):
    from services.api.storage import Storage
    monkeypatch.setenv('ROBOT_IDE_DATA_DIR',str(tmp_path/'data'))
    assert Storage().root==tmp_path/'data'
    assert Storage(tmp_path/'explicit').root==tmp_path/'explicit'

def test_installer_payload_verifies_digest_and_path(tmp_path,monkeypatch):
    m=module('setup');monkeypatch.setattr(m,'BASE',tmp_path)
    (tmp_path/'payload').mkdir();(tmp_path/'payload/file').write_text('x')
    with pytest.raises(ValueError,match='checksum'):m.verify_payload({'files':{'file':'wrong'}})
    with pytest.raises(ValueError,match='checksum'):m.verify_payload({'files':{'../../private':'wrong'}})

def test_desktop_download_accepts_official_binary_checksum_format(tmp_path,monkeypatch):
    import hashlib,io
    m=module('setup');monkeypatch.setattr(m,'current_target',lambda:('windows' if m.os.name=='nt' else 'linux','x64'));name='electron-v45.0.0-'+('win32' if m.os.name=='nt' else 'linux')+'-x64.zip'
    buf=io.BytesIO()
    with zipfile.ZipFile(buf,'w') as z:z.writestr('electron.exe' if m.os.name=='nt' else 'electron',b'program')
    raw=buf.getvalue();checks=(hashlib.sha256(raw).hexdigest()+' *'+name+'\n').encode()
    monkeypatch.setattr(m.urllib.request,'urlopen',lambda url,**kw:io.BytesIO(checks if url.endswith('SHASUMS256.txt') else raw))
    executable=m.electron_install(tmp_path)
    assert executable.read_bytes()==b'program'
    assert not (tmp_path/'electron.zip').exists()


def test_new_release_matrix_covers_both_macs_and_rtx_editions():
    m=module('build');targets=list(m.targets())
    assert set(targets)=={('macos','arm64','desktop'),('macos','x64','desktop'),('windows','x64','server'),('windows','x64','desktop'),('linux','x64','server'),('linux','x64','desktop')}


def test_remote_installer_preflight_skips_gpu_but_rejects_wrong_arch(tmp_path,monkeypatch):
    m=module('setup');monkeypatch.setattr(m,'BASE',tmp_path)
    monkeypatch.setattr(m.platform,'system',lambda:'Darwin');monkeypatch.setattr(m.platform,'machine',lambda:'arm64')
    monkeypatch.setattr(m,'check_gpu',lambda:pytest.fail('Remote setup must never probe or require a GPU'))
    manifest={'mode':'desktop','platform':'macos','architecture':'arm64','files':{}}
    (tmp_path/'manifest.json').write_text(json.dumps(manifest))
    monkeypatch.setattr(sys,'argv',['setup.py','--mode','desktop','--check'])
    m.main()
    manifest['architecture']='x64';(tmp_path/'manifest.json').write_text(json.dumps(manifest))
    with pytest.raises(ValueError,match='architecture'):m.main()


def test_electron_framework_symlinks_and_archive_escape(tmp_path):
    import stat
    m=module('setup');archive=tmp_path/'electron.zip'
    with zipfile.ZipFile(archive,'w') as z:
        z.writestr('Framework/Versions/A/program',b'executable')
        info=zipfile.ZipInfo('Framework/Versions/Current');info.create_system=3;info.external_attr=(stat.S_IFLNK|0o777)<<16;z.writestr(info,'A')
    m.extract_electron(archive,tmp_path/'good')
    assert (tmp_path/'good/Framework/Versions/Current/program').read_bytes()==b'executable'
    with zipfile.ZipFile(archive,'w') as z:
        info=zipfile.ZipInfo('escape');info.create_system=3;info.external_attr=(stat.S_IFLNK|0o777)<<16;z.writestr(info,'../../outside')
    with pytest.raises(ValueError,match='symlink'):m.extract_electron(archive,tmp_path/'bad')


def test_business_companion_installs_only_link_and_offline_capture(tmp_path,monkeypatch):
    import hashlib,plistlib
    spec=importlib.util.spec_from_file_location('business_setup',ROOT/'installers/business/setup.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    source=tmp_path/'source';source.mkdir();monkeypatch.setattr(m,'BASE',source);monkeypatch.setattr(m.platform,'system',lambda:'Darwin')
    files={}
    for name in ['room-capture.html','capture-sw.js','app-icon-192.png','START-HERE.html']:
        (source/name).write_bytes(b'fixture');files[name]=hashlib.sha256(b'fixture').hexdigest()
    (source/'manifest.json').write_text(json.dumps({'version':'0.4.0','files':files}))
    link=m.install(tmp_path/'installed','https://workspace.example.com/login')
    assert plistlib.loads(link.read_bytes())['URL']=='https://workspace.example.com/business/'
    assert not (tmp_path/'installed/access.json').exists()
    assert not (tmp_path/'installed/data').exists()
    for url in ['http://example.com','https://user:secret@example.com','file:///etc/passwd','https://example.com/?code=secret','https://example.com/\nInjected']:
        with pytest.raises(ValueError):m.workspace_url(url)
    assert m.workspace_url('http://127.0.0.1:8080')=='http://127.0.0.1:8080/business/'
    (source/'room-capture.html').write_text('changed')
    with pytest.raises(ValueError,match='checksum'):m.install(tmp_path/'installed','https://workspace.example.com')


def test_clean_checkout_seeds_examples_once_without_publishing_saved_projects(tmp_path,monkeypatch):
    import services.api.storage as storage
    monkeypatch.delenv('ROBOT_IDE_DATA_DIR',raising=False)
    monkeypatch.setattr(storage,'ROOT',tmp_path/'source')
    example=storage.ROOT/'examples/projects/apple_transfer';example.mkdir(parents=True)
    (example/'project.yaml').write_text('name: Clean example')
    store=storage.Storage()
    saved=store.projects/'apple_transfer/project.yaml'
    assert saved.read_text()=='name: Clean example'
    saved.write_text('name: Private edited project')
    storage.Storage()
    assert saved.read_text()=='name: Private edited project'
    explicit=storage.Storage(tmp_path/'explicit')
    assert not explicit.projects.exists()
