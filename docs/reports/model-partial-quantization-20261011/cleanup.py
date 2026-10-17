"""核验正式服务后，清理本次拥有的 Java 克隆、代理与凭据副本。"""
import json
import os
from pathlib import Path
import signal
import socket
import stat
import subprocess
import sys
import time
import urllib.request

ROOT = Path('/tmp/rs-agent-partial-quantization-20261011')
OLD = Path('/tmp/rs-agent-quantization-retry-20261011')

def closed(port):
    with socket.socket() as connection:
        return connection.connect_ex(('127.0.0.1', port)) != 0

assert closed(18092), '候选模型仍运行，暂不清理'
subprocess.run([sys.executable, str(OLD / 'audit_memory.py')], check=True)
(ROOT / 'production-live-state.json').write_bytes((OLD / 'memory-live-state.json').read_bytes())
subprocess.run([sys.executable, str(OLD / 'cleanup.py'), '--state-file', str(OLD / 'memory-deployment-state.json'),
                '--output', str(OLD / 'partial-cleanup-state.json')], check=True)
state = json.loads((ROOT / 'proxy-state.json').read_text())
pid = state['pid']
assert state['port'] == 18094
path = Path('/proc') / str(pid) / 'cmdline'
if path.exists():
    arguments = path.read_bytes().split(bytes([0]))
    assert str(ROOT / 'capture_proxy.py').encode() in arguments
    assert os.getpgid(pid) == pid
    os.killpg(pid, signal.SIGTERM)
    deadline = time.monotonic() + 30
    while not closed(18094) and time.monotonic() < deadline:
        time.sleep(0.2)
assert closed(18094) and closed(18314)
account = ROOT / 'accounts.json'
if account.exists():
    assert stat.S_IMODE(account.stat().st_mode) == 0o600
    account.unlink()
with urllib.request.urlopen('http://127.0.0.1:18082/health', timeout=5) as response:
    assert response.status == 200
report = json.loads((OLD / 'partial-cleanup-state.json').read_text())
report.update(own_capture_proxy_removed=True, partial_account_copy_removed=True,
              capture_proxy_port_closed=True, own_agent_port_closed=True,
              production_precision='INT4 weights / BF16 activations', production_unchanged=True)
(ROOT / 'cleanup-state.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print('本次候选、代理、Java 克隆与账号副本已清理；正式 INT4 配置及进程身份核验通过', flush=True)
