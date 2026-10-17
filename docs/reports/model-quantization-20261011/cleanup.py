"""验收结束后只清理本次独立容器与凭据副本。"""
import argparse
import hashlib
import importlib.util
import json
from pathlib import Path
import socket
import stat
import subprocess
import urllib.request

root = Path(__file__).resolve().parent
parser = argparse.ArgumentParser()
parser.add_argument('--state-file', type=Path, default=root / 'deployment-state.json')
parser.add_argument('--output', type=Path, default=root / 'cleanup-state.json')
args = parser.parse_args()
assert args.state_file.resolve().parent == root and args.output.resolve().parent == root
state = json.loads(args.state_file.read_text())
assert state['promoted'] or state.get('rollback'), '未部署或未恢复，保留验收环境'
if not state['promoted']:
    live = Path('/home/luo/RS_agent_java/model_deploy')
    expected = json.loads((root / 'baseline-deployment.json').read_text())['sha256']
    for filename, digest in expected.items():
        assert hashlib.sha256((live / filename).read_bytes()).hexdigest() == digest
    spec = importlib.util.spec_from_file_location('runtime', '/tmp/rs-serving-tuning-20261011/deploy.py')
    runtime = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(runtime)
    runtime.canonical_process()
with urllib.request.urlopen('http://127.0.0.1:18082/health', timeout=5) as response:
    assert response.status == 200
name = 'rs-quantization-20261011-agent'
inspection = subprocess.run(['docker', 'inspect', name], capture_output=True, text=True)
if inspection.returncode == 0:
    container = json.loads(inspection.stdout)[0]
    env = dict(row.split('=', 1) for row in container['Config']['Env'] if '=' in row)
    assert container['Config']['Labels']['rsagent.quantization-task'] == '20261011'
    assert env['SERVER_PORT'] == '18314' and env['SERVER_ADDRESS'] == '127.0.0.1'
    assert json.loads((root / 'agent-clone-state.json').read_text())['name'] == name
    subprocess.run(['docker', 'stop', name], check=True, stdout=subprocess.DEVNULL)
    subprocess.run(['docker', 'rm', name], check=True, stdout=subprocess.DEVNULL)
removed = []
for filename in ['accounts.json', 'agent-clone.private.env']:
    path = root / filename
    if path.exists():
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
        path.unlink()
        removed.append(filename)
with socket.socket() as connection:
    port_closed = connection.connect_ex(('127.0.0.1', 18092)) != 0
assert port_closed
source = json.loads(subprocess.check_output(['docker', 'inspect', 'rs-e2e-857e8b14-agent-fast'], text=True))[0]
report = {'own_container_removed': True, 'private_credential_copies_removed': removed,
          'isolated_model_port_closed': port_closed, 'shared_agent_running': source['State']['Running']}
args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print('本次验收容器和凭据副本已清理；正式模型保持运行', flush=True)
