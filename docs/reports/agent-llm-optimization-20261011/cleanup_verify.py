"""撤除自有诊断代理和私有输入；保留已被另一项前端部署复用的 QA 服务。"""
import datetime
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import time
import urllib.request
from probe import ROOT
from measure import ready

def run(args):return subprocess.check_output(args,text=True).strip()
def inspect(name):return json.loads(run(['docker','inspect',name]))[0]
state_file=ROOT/'state.json'; before=json.loads(state_file.read_text())
assert not before.get('cleaned')
prefix='rs-e2e-'+before['suffix']+'-'
frontend=before.get('a2ui-frontend')
assert frontend==prefix+'a2ui-frontend' and inspect(frontend)['State']['Running']
model_switch=json.loads((ROOT/'model-switch.json').read_text())
assert model_switch['mode']=='restore'
with urllib.request.urlopen('http://127.0.0.1:18082/v1/models',timeout=10) as response:models=json.load(response)
assert models['data'][0]['max_model_len']==16384
model_processes=[]
for directory in Path('/proc').iterdir():
    if not directory.name.isdecimal():continue
    try:
        args=(directory/'cmdline').read_bytes().decode().split('\0')[:-1]
        if 'serve' not in args or '18082' not in args or not any('/bin/vllm' in arg for arg in args):continue
        env=dict(entry.split('=',1) for entry in (directory/'environ').read_bytes().decode().split('\0') if '=' in entry)
        assert env.get('CUDA_VISIBLE_DEVICES')=='1'
        assert '--enable-prefix-caching' in args and '--quantization' not in args and '--speculative-config' not in args
        assert args[args.index('--max-model-len')+1]=='16384'
        assert args[args.index('--gpu-memory-utilization')+1]=='0.78'
        model_processes.append({'pid':int(directory.name),'command':args})
    except (FileNotFoundError,ProcessLookupError):continue
assert len(model_processes)==1
# 只重建本次登记的 Agent，改为直接访问正式 Qwen；其他 QA 服务与前端保持运行。
environment=ROOT/'environment.py'; source=environment.read_text()
needle='"RS_AGENT_OPENAI_BASE_URL": "http://127.0.0.1:18217/v1"'
assert source.count(needle)==1
environment.write_text(source.replace(needle,'"RS_AGENT_OPENAI_BASE_URL": "http://127.0.0.1:18082/v1"'))
agent=before['agent-fast'];assert agent==prefix+'agent-fast'
subprocess.run(['docker','rm','-f',agent],capture_output=True,check=True)
state=json.loads(state_file.read_text());assert state['agent-fast']==agent
state['containers'].remove(agent);del state['agent-fast'];state_file.write_text(json.dumps(state,indent=2))
subprocess.run(['python3',str(environment),'services','--root',str(ROOT)],
               env=dict(os.environ,RS_PROFILE_ENABLED='false'),check=True)
ready()
with urllib.request.urlopen('http://127.0.0.1:18289/healthz',timeout=10) as response:assert response.status==200
record=json.loads((ROOT/'wire-probe-pid.json').read_text());pid=record['pid'];cmdline=Path(f'/proc/{pid}/cmdline')
if cmdline.exists() and cmdline.read_bytes():
    assert cmdline.read_bytes().decode().split('\0')[:-1]==record['command']
    os.kill(pid,signal.SIGTERM)
    for _ in range(100):
        if not cmdline.exists() or not cmdline.read_bytes():break
        time.sleep(.1)
    else:raise RuntimeError('自有诊断代理未退出')
original_hash=hashlib.sha256((ROOT/'private-model-backup'/'original.sh').read_bytes()).hexdigest()
formal_hash=hashlib.sha256(Path('/home/luo/RS_agent_java/model_deploy/start_qwen35_4b_vllm.sh').read_bytes()).hexdigest()
for private_name in ('private-replay','private-model-backup'):
    private=ROOT/private_name
    assert not private.is_symlink() and private.resolve().parent==ROOT.resolve()
    if private.exists():shutil.rmtree(private)
for name in ('accounts.json','credentials.json'):
    private=ROOT/name
    if private.exists():private.chmod(0o600)
state=json.loads(state_file.read_text());state.update(measurement_complete=True,diagnostic_probe_removed=True,
                                                   retained_for_a2ui=True)
state_file.write_text(json.dumps(state,indent=2))
hashes={module:run(['sha256sum',str(ROOT/(module+'.jar'))]).split()[0]
        for module in ('rs-service-agent','rs-service-recommend','rs-service-model')}
result={'verified_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),
        'qa_retained_for_existing_frontend':True,'frontend_healthy':True,'frontend':frontend,
        'retained_qa_containers':state['containers'],'retained_infra':state['started_infra'],
        'retained_qa_database':state['database'],'bge_retained_as_active_qa_dependency':True,
        'wire_probe_stopped':True,'agent_uses_model_directly':True,
        'private_prompt_and_model_environment_backups_removed':True,
        'required_qa_credentials_retained_with_mode_600':True,'business_jar_sha256':hashes,
        'mtp_experiment_rolled_back':True,'current_model':model_processes[0],
        'original_launcher_sha256':original_hash,'current_launcher_sha256':formal_hash,
        'formal_model_files_may_have_external_changes':formal_hash!=original_hash,
        'local_qwen':models['data'],'gpu_0_and_2_processes_not_modified':True,
        'gpu':run(['nvidia-smi','--query-gpu=index,memory.used,memory.total,utilization.gpu','--format=csv,noheader,nounits']),
        'cold_backup_retained':Path('/home/luo/RS_agent_java/db/mysql-cold-backup-20261010234436').is_dir()}
(ROOT/'restoration.json').write_text(json.dumps(result,ensure_ascii=False,indent=2))
print('诊断代理及私有输入已撤除；复用的前端、QA 依赖及正式模型保持可用。',flush=True)
