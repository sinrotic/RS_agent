"""只审计服务身份、健康及本任务资源，不输出凭据。"""
import datetime
import json
import os
import socket
import subprocess
import urllib.request
from pathlib import Path

from benchmark import probe, model, ROOT

first = json.loads((ROOT / 'original-bf16-screen.json').read_text())
health = {}
for name, port in (('agent', 18214), ('gateway', 18288), ('recommend', 18213),
                   ('catalog', 18202), ('user', 18201), ('model', 18205)):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/actuator/health', timeout=5) as response:
            health[name] = {'status': response.status, 'health': json.load(response).get('status')}
    except Exception as error:
        health[name] = {'error_type': type(error).__name__}
snapshot = model.gpu_snapshot()
groups = {json.loads(path.read_text())['pid'] for path in ROOT.glob('temporary-*-state.json')}
groups_absent = True
for row in snapshot['processes']:
    try:
        groups_absent &= os.getpgid(row['pid']) not in groups
    except ProcessLookupError:
        pass
ports_closed = {}
for port in (18319, 18096):
    with socket.socket() as connection:
        ports_closed[str(port)] = connection.connect_ex(('127.0.0.1', port)) != 0
state = json.loads(model.STATE.read_text())
report = {'checked_at_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
          'shared_model_unchanged': probe.identity() == first['shared_model_before'],
          'dependencies_unchanged': probe.dependency_snapshot() == first['dependencies_before'],
          'temporary_container_absent': subprocess.run(['docker', 'inspect', probe.NAME], capture_output=True).returncode != 0,
          'private_env_absent': not (ROOT / 'clone.private.env').exists(),
          'temporary_model_stopped': state['stopped'] and not model.owned(state),
          'temporary_gpu_groups_absent': groups_absent,
          'ports_closed': ports_closed, 'health': health, 'gpu_snapshot': snapshot}
(ROOT / 'audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
assert all(report[key] for key in ('shared_model_unchanged', 'dependencies_unchanged', 'temporary_container_absent',
                                   'private_env_absent', 'temporary_model_stopped', 'temporary_gpu_groups_absent'))
assert all(ports_closed.values()) and all(row.get('health') == 'UP' for row in health.values())
print(json.dumps({key: value for key, value in report.items() if key not in ('gpu_snapshot', 'health')}, ensure_ascii=False))
