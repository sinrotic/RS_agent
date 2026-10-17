"""审计本任务清理及原有服务健康；不输出环境变量或业务内容。"""
import json
import os
import socket
import urllib.request
from reproduce import ROOT, live, model

first = json.loads((ROOT / 'reproduction.json').read_text())
state = json.loads(model.STATE.read_text())
health = {}
for name, port in (('agent', 18214), ('gateway', 18288), ('recommend', 18213),
                   ('catalog', 18202), ('user', 18201), ('model', 18205)):
    with urllib.request.urlopen(f'http://127.0.0.1:{port}/actuator/health', timeout=5) as response:
        health[name] = json.load(response)['status']
snapshot = model.gpu_snapshot()
groups = {json.loads(path.read_text())['pid'] for path in ROOT.glob('temporary-*-state.json')}
groups |= {json.loads(path.read_text())['gpu_after'].get('task_pid', -1)
           for path in ROOT.glob('reproduction-*.json') if 'gpu_after' in json.loads(path.read_text())}
groups_absent = all(os.getpgid(row['pid']) not in groups for row in snapshot['processes'])
with socket.socket() as connection:
    closed = connection.connect_ex(('127.0.0.1', model.PORT)) != 0
report = {'shared_model_unchanged': live.identity() == first['shared_model_before'],
          'dependencies_unchanged': live.dependency_snapshot() == first['dependencies_before'],
          'temporary_model_stopped': state['stopped'] and not model.owned(state),
          'temporary_port_closed': closed, 'temporary_gpu_groups_absent': groups_absent,
          'health': health, 'gpu_snapshot': snapshot}
(ROOT / 'audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
assert all(report[key] for key in ('shared_model_unchanged', 'dependencies_unchanged', 'temporary_model_stopped',
                                   'temporary_port_closed', 'temporary_gpu_groups_absent'))
assert all(value == 'UP' for value in health.values())
print(json.dumps({key: value for key, value in report.items() if key != 'gpu_snapshot'}, ensure_ascii=False))
