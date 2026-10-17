"""独立 Java 容器连接指定模型，受控清理本次凭据副本和容器。"""
import argparse
import json
from pathlib import Path
import socket
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
OLD = Path('/tmp/rs-agent-quantization-retry-20261011')
sys.path.insert(0, str(OLD))
from promote import wait_clone_ready

def run(port, label):
    accounts = ROOT / 'accounts.json'
    private_env = OLD / 'agent-clone.private.env'
    assert not accounts.exists() and not private_env.exists()
    name = 'rs-quantization-20261011-agent'
    assert subprocess.run(['docker', 'inspect', name], capture_output=True).returncode != 0
    with socket.socket() as connection:
        assert connection.connect_ex(('127.0.0.1', 18314)) != 0
    descriptor = accounts.open('xb')
    accounts.chmod(0o600)
    with descriptor:
        descriptor.write(Path('/tmp/rs-agent-e2e-20261010-llm-opt-20261011/accounts.json').read_bytes())
    owned = None
    try:
        subprocess.run([sys.executable, str(OLD / 'clone.py'), '--model-port', str(port)], check=True)
        owned = json.loads(subprocess.check_output(['docker', 'inspect', name], text=True))[0]['Id']
        wait_clone_ready()
        subprocess.run([sys.executable, str(ROOT / 'business_regression.py'), '--label', label], check=True, timeout=480)
    finally:
        current = subprocess.run(['docker', 'inspect', name], capture_output=True, text=True)
        if current.returncode == 0:
            info = json.loads(current.stdout)[0]
            assert owned and info['Id'] == owned
            assert info['Config']['Labels']['rsagent.quantization-task'] == '20261011'
            env = dict(row.split('=', 1) for row in info['Config']['Env'] if '=' in row)
            assert env['SERVER_PORT'] == '18314' and env['SERVER_ADDRESS'] == '127.0.0.1'
            subprocess.run(['docker', 'stop', name], check=True, stdout=subprocess.DEVNULL)
            subprocess.run(['docker', 'rm', name], check=True, stdout=subprocess.DEVNULL)
        for path in [accounts, private_env]:
            if path.exists():
                assert stat.S_IMODE(path.stat().st_mode) == 0o600
                path.unlink()
        with socket.socket() as connection:
            assert connection.connect_ex(('127.0.0.1', 18314)) != 0
        (ROOT / (label + '-business-cleanup.json')).write_text(json.dumps({'own_container_removed': True,
            'credential_copies_removed': True, 'validation_port_closed': True}) + '\n')

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--model-port', type=int, choices=[18082, 18092], required=True)
    parser.add_argument('--label', required=True)
    args = parser.parse_args()
    run(args.model_port, args.label)
