"""核验已恢复的原模型、训练卡与初始停机服务；删除验收凭据。"""
import json
import subprocess
import urllib.request
from pathlib import Path

root=Path('/tmp/rs-agent-e2e-20261010-1247')
state=json.loads((root/'state.json').read_text()); model=json.loads((root/'vllm-private.json').read_text())
parent=model['restored_pid']
assert Path(f'/proc/{parent}/cmdline').read_bytes().decode().split('\0')[:-1] == model['parent_command']
children=Path(f'/proc/{parent}/task/{parent}/children').read_text().split()
commands=[Path(f'/proc/{pid}/cmdline').read_bytes().decode().split('\0')[:-1] for pid in children]
assert model['original_command'] in commands, 'original model command not restored'
keepalive=any('vllm_prefix_warmup.py' in ' '.join(command) and '--keepalive' in command for command in commands)
assert keepalive,'prefix keepalive not restored'
ready=model['original_env'].get('VLLM_READY_FILE','/tmp/rs_agent_latency/vllm_qwen35_4b.ready')
assert Path(ready).exists(),'original model readiness marker missing'
with urllib.request.urlopen('http://127.0.0.1:18082/health',timeout=5) as response:
    assert response.status==200
infra={}
for name in state['started_infra']:
    info=json.loads(subprocess.check_output(['docker','inspect',name]))[0]
    infra[name]=info['State']['Status']; assert not info['State']['Running']
running=subprocess.check_output(['docker','ps','--format','{{.Names}}'],text=True).splitlines()
assert not any(name.startswith('rs-e2e-'+state['suffix']+'-') for name in running)
gpu=subprocess.check_output(['nvidia-smi','--query-gpu=index,memory.used,utilization.gpu','--format=csv,noheader'],text=True)
formal_bge=subprocess.run(['systemctl','--user','is-active','rs-bge-runtime.service'],capture_output=True,text=True).stdout.strip()
assert formal_bge == 'inactive'
report={'cleaned':state['cleaned'],'original_infra_restored_to_stopped':infra,
        'original_vllm_command_restored':model['original_command'],'model_health':200,
        'original_start_script_restored':True,'prefix_keepalive_restored':keepalive,
        'readiness_marker_exists':True,'gpu_status':gpu.strip(),'formal_bge_status':formal_bge,
        'owned_test_containers_removed':True}
for name in ['accounts.json','credentials.json','vllm-private.json']:
    (root/name).unlink(missing_ok=True)
report['private_test_credentials_removed']=True
(root/'restoration.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print('RESTORATION VERIFIED',gpu.strip(),flush=True)
