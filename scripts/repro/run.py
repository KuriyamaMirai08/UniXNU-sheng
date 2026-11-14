"""One isolated B1 attempt. Errors end execution; final inventory runs in finally."""
import hashlib
import json
import os
import shutil
import signal
import subprocess
import sys
import time
import threading
from pathlib import Path
from preserve import apply

DEVICE='1281f0f4eb010da0b3c2d9f1c5684e9566fe318f'
FRAMEWORK='97437dcf7389484a0eeaa8067725ce743aff18ef'

def main():
    root=Path(os.environ['RUNNER_TEMP'])/'unixnu-repro'/f"{os.environ['GITHUB_RUN_ID']}-{os.environ['GITHUB_RUN_ATTEMPT']}"/'current'
    root.mkdir(parents=True,exist_ok=False)
    evidence=root/'evidence'; evidence.mkdir()
    with open(os.environ['GITHUB_ENV'],'a') as stream: stream.write('REPRO_ATTEMPT='+str(root)+'\n')
    os.environ['REPRO_ROOT']=str(root)
    os.environ['REPRO_EVENTS']=str(evidence/'processes.jsonl')
    os.environ['PYTHONPATH']=str(Path(__file__).parent.resolve())
    os.environ['PYTHONUNBUFFERED']='1'
    os.environ['RUSTUP_TOOLCHAIN']='1.98.0'
    from observe import install
    install()
    states=[]
    deadline=time.monotonic()+300*60
    def step(name,argv,cwd=root):
        print('REPRO stage started: '+name,flush=True)
        row=dict(stage=name,argv=list(map(str,argv)),cwd=str(cwd),start=time.time(),status='running')
        states.append(row)
        (evidence/'stages.json').write_text(json.dumps(states,indent=2))
        try:
            with (evidence/(name+'.log')).open('wb') as stream:
                process=subprocess.Popen(argv,cwd=cwd,stdout=stream,stderr=subprocess.STDOUT,start_new_session=True)
                stop=threading.Event()
                def progress():
                    while not stop.wait(30):
                        path=evidence/(name+'.log')
                        print('REPRO stage running: '+name+' log_bytes='+str(path.stat().st_size),flush=True)
                thread=threading.Thread(target=progress,daemon=True); thread.start()
                try:
                    code=process.wait(timeout=max(1,deadline-time.monotonic()))
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid,signal.SIGTERM)
                    try: process.wait(timeout=10)
                    except subprocess.TimeoutExpired: pass
                    try: os.killpg(process.pid,signal.SIGKILL)
                    except ProcessLookupError: pass
                    process.wait()
                    row['timeout']=True
                    raise RuntimeError('Attempt reached 300-minute build budget: '+name)
                finally:
                    stop.set(); thread.join()
            row.update(returncode=code,status='passed' if code==0 else 'failed')
            if code: raise RuntimeError('First failed stage: '+name)
        except BaseException:
            row['status']='failed'; raise
        finally:
            row['end']=time.time()
            (evidence/'stages.json').write_text(json.dumps(states,indent=2))
            print('REPRO stage ended: '+name+' '+row['status'],flush=True)
    try:
        step('environment',['bash','-c','sw_vers; uname -a; sysctl hw.memsize hw.ncpu; df -k; xcodebuild -version; xcrun clang --version; xcrun --sdk iphoneos --show-sdk-version; brew list --versions; rustc +1.98.0 --version; cargo +1.98.0 --version'])
        tools={}
        for name in ['python3','git','make','clang','ld','ninja','cmake','dtc','ipsw','rustc','cargo']:
            path=shutil.which(name)
            if not path: raise RuntimeError('Missing tool: '+name)
            with open(path,'rb') as stream: value=hashlib.file_digest(stream,'sha256').hexdigest()
            tools[name]=dict(path=path,sha256=value)
        for name in ['clang','ld']:
            path=subprocess.check_output(['xcrun','--find',name],text=True).strip()
            with open(path,'rb') as stream: value=hashlib.file_digest(stream,'sha256').hexdigest()
            tools['xcrun-'+name]=dict(path=path,sha256=value)
        (evidence/'tool-identities.json').write_text(json.dumps(tools,indent=2))
        (evidence/'runner-image.json').write_text(json.dumps({key:os.environ.get(key) for key in ['ImageOS','ImageVersion','RUNNER_ARCH','RUNNER_OS','GITHUB_SHA','GITHUB_RUN_ID','GITHUB_RUN_ATTEMPT']},indent=2))
        if shutil.disk_usage(root).free < 12*1024**3: raise RuntimeError('Less than 12 GiB free before source fetch')
        for key in list(os.environ):
            if key.startswith(('CCACHE_','SCCACHE_')) or key in ['CC','CXX','CFLAGS','CXXFLAGS','LDFLAGS','UNIXNU_UNIQUE_CHIP_ID']:
                os.environ.pop(key,None)
        for key in ['TMPDIR','XDG_CACHE_HOME','CLANG_MODULE_CACHE_PATH','CARGO_TARGET_DIR']:
            path=root/'caches'/key; path.mkdir(parents=True); os.environ[key]=str(path)
        bashenv=evidence/'bash-env.sh'; bashenv.write_text("PS4='+ ${BASH_SOURCE}:${LINENO}: '; set -x\n")
        os.environ['BASH_ENV']=str(bashenv)
        for name,url,sha in [('device','KuriyamaMirai08/UniXNU-sheng',DEVICE),('UniXNU','UniXNU/UniXNU',FRAMEWORK)]:
            dest=root/name
            step('init-'+name,['git','init',str(dest)])
            step('fetch-'+name,['git','-C',str(dest),'fetch','--depth','1','https://github.com/'+url+'.git',sha])
            step('checkout-'+name,['git','-C',str(dest),'checkout','--detach',sha])
            step('submodules-'+name,['git','-C',str(dest),'submodule','update','--init','--recursive'])
            step('pins-'+name,['git','-C',str(dest),'submodule','status','--recursive'])
            if subprocess.check_output(['git','-C',str(dest),'rev-parse','HEAD'],text=True).strip()!=sha: raise RuntimeError('SHA mismatch')
            if any(dest.rglob('local.toml')): raise RuntimeError('Undeclared local.toml')
        device=root/'device'; fw=root/'UniXNU'
        shutil.copyfile(device/'unixnu.lock',evidence/'unixnu.lock.before')
        (root/'build.toml').write_text('[build]\n')
        step('compatibility',['python3','scripts/prepare-package-ci.py','--unixnu',str(fw)],device)
        apply(fw,evidence)
        step('framework-diff',['git','diff','--binary'],fw)
        common=['--os','27','--out',str(root/'out'),'--config',str(root/'build.toml'),'-j','3']
        step('dependencies',['python3',str(fw/'unixnu'),'fetch','-D',str(device),*common])
        shutil.copyfile(device/'unixnu.lock',evidence/'unixnu.lock.resolved')
        step('configuration',['bash','scripts/package.sh',*common,'--no-deps','--check'],device)
        for name,args in [('firmware',['python3','scripts/extract-files.py']),('ath12k',['bash','drivers/Ath12kWifi/tools/fetch-sources.sh']),('bluetooth-source',['python3','drivers/QcaBluetooth/tools/prepare-linux.py']),('bluetooth-firmware',['python3','scripts/stage-bluetooth-firmware.py','.cache/bt-stage','--fetch'])]:
            step(name,args,device)
        tree=root/'out/sheng/ipados-27.0.1-24A446/sheng_ipados27/tree'
        old=[str(p) for p in tree.rglob('*') if p.is_file() and (p.suffix in ['.o','.a'] or p.name=='kernel.macho')]
        (evidence/'precompile-objects.json').write_text(json.dumps(old,indent=2))
        if old: raise RuntimeError('Objects/archives exist before compilation; review required')
        step('kernel',['python3',str(fw/'unixnu'),'build','kernel','-D',str(device),*common])
    finally:
        # Hash every actual non-Git file, including files behind links inside this root.
        inventory=[]
        for base,dirs,files in os.walk(root,followlinks=False):
            dirs[:]=[d for d in dirs if d!='.git']
            for name in dirs:
                p=Path(base)/name
                if p.is_symlink(): inventory.append(dict(path=str(p.relative_to(root)),link=os.readlink(p)))
            for name in files:
                if name=='.git': continue
                p=Path(base)/name
                if p.is_symlink():
                    inventory.append(dict(path=str(p.relative_to(root)),link=os.readlink(p)))
                elif p.is_file():
                    with p.open('rb') as stream: digest=hashlib.file_digest(stream,'sha256').hexdigest()
                    inventory.append(dict(path=str(p.relative_to(root)),bytes=p.stat().st_size,sha256=digest))
        (evidence/'file-inventory.json').write_text(json.dumps(inventory,indent=2))
        # Copy the attempt location for the workflow's final evidence step.
        with open(os.environ['GITHUB_ENV'],'a') as stream: stream.write('REPRO_ATTEMPT='+str(root)+'\n')

if __name__=='__main__': main()
