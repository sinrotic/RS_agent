"""对照结束后的公开审计：既有服务身份/容量与临时资源清理，不输出环境凭据。"""
import datetime
import hashlib
import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from temporary_model import gpu_snapshot, owned, STATE
from compare_live import identity, inspect, SOURCE, NAME, CURRENT_SHA, JARS, FLAGS

first = json.loads((ROOT / 'original-latency-r1.json').read_text())
source = inspect(SOURCE)
env = dict(item.split('=', 1) for item in source['Config']['Env'] if '=' in item)
health = {}
for name, port in (('agent', 18214), ('gateway', 18288), ('recommend', 18213), ('catalog', 18202),
                   ('user', 18201), ('model', 18205)):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/actuator/health', timeout=5) as response:
            health[name] = {'status': response.status, 'health': json.load(response).get('status')}
    except Exception as error:
        health[name] = {'error_type': type(error).__name__}
with JARS['current'].open('rb') as stream:
    sha = hashlib.file_digest(stream, 'sha256').hexdigest()
state = json.loads(STATE.read_text()) if STATE.exists() else None
snapshot = gpu_snapshot()
task_groups = {json.loads(path.read_text())['pid'] for path in
    (ROOT / 'temporary-bf16-state.json', ROOT / 'temporary-quant-state.json') if path.exists()}
task_gpu_groups_absent = True
for process in snapshot['processes']:
    try:
        task_gpu_groups_absent &= os.getpgid(process['pid']) not in task_groups
    except ProcessLookupError:
        pass
report = {'checked_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'shared_agent_id': source['Id'], 'shared_agent_running': source['State']['Running'],
    'shared_agent_unchanged': source['Id'] == first['dependencies_before'][SOURCE]['id'],
    'shared_model_unchanged': identity() == first['model_before'], 'shared_model': identity(),
    'current_jar_sha256': sha, 'current_jar_matches': sha == CURRENT_SHA,
    'shared_agent_flags': {key: env.get(key, '(默认值)') for key in FLAGS},
    'test_container_absent': subprocess.run(['docker', 'inspect', NAME], capture_output=True).returncode != 0,
    'private_clone_env_absent': not (ROOT / 'clone.private.env').exists(),
    'temporary_model_stopped': state is None or (state.get('stopped') and not owned(state)),
    'temporary_gpu_process_groups_absent': task_gpu_groups_absent,
    'gpu_snapshot': snapshot, 'health': health}
try:
    with urllib.request.urlopen('http://127.0.0.1:18096/health', timeout=2):
        report['temporary_model_port_closed'] = False
except OSError:
    report['temporary_model_port_closed'] = True
assert report['shared_agent_unchanged'] and report['shared_model_unchanged'] and report['current_jar_matches']
assert report['test_container_absent'] and report['private_clone_env_absent']
assert report['temporary_model_stopped'] and report['temporary_model_port_closed']
assert report['temporary_gpu_process_groups_absent']
assert env['RS_AGENT_MAX_MODEL_STREAMS'] == '16' and env['RS_AGENT_MAX_RECOMMENDATION_CALLS'] == '4'
assert env['RS_AGENT_MODEL_STREAM_ACQUIRE_TIMEOUT_MS'] == '15000'
(ROOT / 'audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
print(json.dumps({key: report[key] for key in ('shared_agent_unchanged', 'shared_model_unchanged',
    'current_jar_matches', 'test_container_absent', 'private_clone_env_absent', 'temporary_model_stopped',
    'temporary_model_port_closed')}, ensure_ascii=False))
