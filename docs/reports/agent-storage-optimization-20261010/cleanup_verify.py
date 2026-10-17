"""恢复原停机状态，停止本次 GPU 1 辅助进程，记录无凭证验收结果。"""
import datetime
import json
import os
from pathlib import Path
import signal
import subprocess
import time
import urllib.request

ROOT = Path('/tmp/rs-agent-e2e-20261010-storage-opt')
def run(args): return subprocess.check_output(args, text=True).strip()
def inspect(name): return json.loads(run(['docker', 'inspect', name]))[0]
before = json.loads((ROOT / 'state.json').read_text())
assert not before.get('cleaned')
prefix = 'rs-e2e-' + before['suffix'] + '-'
hashes = {module: run(['sha256sum', str(ROOT / (module + '.jar'))]).split()[0]
          for module in ('rs-service-agent', 'rs-service-recommend', 'rs-service-model')}
subprocess.run(['python3', str(ROOT / 'stop_bge.py')], check=True)
record = json.loads((ROOT / 'wire-probe-pid.json').read_text())
pid = record['pid']; process = Path(f'/proc/{pid}/cmdline')
if process.exists():
    assert 'model_wire_probe.py' in process.read_bytes().decode(), '探针 PID 身份不一致'
    os.kill(pid, signal.SIGTERM)
    for _ in range(30):
        if not process.exists(): break
        time.sleep(1)
    else: raise RuntimeError('探针未退出')
subprocess.run(['python3', str(ROOT / 'environment.py'), 'cleanup', '--root', str(ROOT)], check=True)
state = json.loads((ROOT / 'state.json').read_text())
assert state['cleaned'] and state['database_removed'] and state['database_user_removed'] and state['keyspace_removed']
owned = [name for name in run(['docker', 'ps', '-a', '--format', '{{.Names}}']).splitlines() if name.startswith(prefix)]
assert not owned
infra = {name: inspect(name)['State']['Status'] for name in before['started_infra']}
assert all(value == 'exited' for value in infra.values())
private_files = [p.name for p in ROOT.glob('*.env')] + [p.name for p in (ROOT / 'accounts.json', ROOT / 'credentials.json') if p.exists()]
assert not private_files
mysql = inspect('rs-agent-java-mysql')
mounts = {mount['Destination']: mount['Source'] for mount in mysql['Mounts']}
assert mounts['/var/lib/mysql'] == '/var/lib/rs-agent-java/mysql-nvme-20261010'
assert mounts['/var/lib/mysql/rs_agent'] == '/home/luo/RS_agent_java/db/mysql/rs_agent'
with urllib.request.urlopen('http://127.0.0.1:18082/v1/models', timeout=10) as response:
    models = json.load(response)
assert models['data'][0]['max_model_len'] == 16384
gpu = run(['nvidia-smi', '--query-gpu=index,memory.used,memory.total,utilization.gpu', '--format=csv,noheader,nounits'])
gpu_processes = run(['nvidia-smi', '--query-compute-apps=pid,used_memory,gpu_uuid', '--format=csv,noheader,nounits'])
result = {'verified_at': datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'qa_containers_remaining': owned, 'original_infra_status': infra,
          'database_removed': True, 'database_user_removed': True, 'keyspace_removed': True,
          'qa_private_files_remaining': private_files, 'temporary_bge_stopped': True, 'wire_probe_stopped': True,
          'business_jar_sha256': hashes, 'mysql_mounts': mounts,
          'local_qwen': models['data'], 'gpu': gpu, 'gpu_processes': gpu_processes,
          'training_original_pids_present': {str(pid): Path(f'/proc/{pid}').exists() for pid in (3975157, 3975158)},
          'cold_backup_retained': Path('/home/luo/RS_agent_java/db/mysql-cold-backup-20261010234436').is_dir()}
(ROOT / 'restoration.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
print('恢复检查通过：QA 已清理，原基础设施停机，GPU 1 正式模型保留。', flush=True)
