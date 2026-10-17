"""启动本次私有捕获代理及控制阶段；仅本次验收容器使用它。"""
import importlib.util
import json
from pathlib import Path
import socket
import subprocess
import sys
import time

ROOT = Path('/tmp/rs-agent-partial-quantization-20261011')
OLD = Path('/tmp/rs-agent-quantization-retry-20261011')
spec = importlib.util.spec_from_file_location('runtime', '/tmp/rs-serving-tuning-20261011/deploy.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)
with socket.socket() as connection:
    assert connection.connect_ex(('127.0.0.1', 18094)) != 0
runtime.atomic_write(ROOT / 'accounts.json', Path('/tmp/rs-agent-e2e-20261010-llm-opt-20261011/accounts.json').read_bytes(), 0o600)
runtime.atomic_write(ROOT / 'proxy-phase.json', b'{"port":18082,"label":"control"}\n', 0o600)
with (ROOT / 'capture-proxy.private.log').open('ab') as log:
    log_path = ROOT / 'capture-proxy.private.log'
    log_path.chmod(0o600)
    proxy = subprocess.Popen([sys.executable, str(ROOT / 'capture_proxy.py')], stdout=log,
                stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL, start_new_session=True)
runtime.atomic_write(ROOT / 'proxy-state.json', (json.dumps({'pid': proxy.pid, 'port':18094})+'\n').encode(), 0o600)
time.sleep(1)
assert proxy.poll() is None
subprocess.run([sys.executable, str(OLD / 'clone.py'), '--model-port', '18094'], check=True)
sys.path.insert(0, str(OLD))
from promote import wait_clone_ready
wait_clone_ready()
subprocess.run([sys.executable, str(ROOT / 'business_compare.py'), '--label', 'control'], check=True, timeout=480)
