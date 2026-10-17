"""正式 18082 模型的身份检查、原子配置和受控重启；不读取或输出凭据。"""
import hashlib
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import time
import urllib.request

LIVE = Path('/home/luo/RS_agent_java/model_deploy')
READY = Path('/tmp/rs_agent_latency/vllm_qwen35_4b.ready')
STATE = LIVE / 'partial-quantization-memory40-state.json'

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def atomic(path, contents, mode=0o600):
    temporary = path.with_name(path.name + '.partial-quantization-next')
    with temporary.open('xb') as handle:
        handle.write(contents)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.chmod(mode)
    temporary.replace(path)

def closed(port=18082):
    with socket.socket() as connection:
        return connection.connect_ex(('127.0.0.1', port)) != 0

def health():
    try:
        with urllib.request.urlopen('http://127.0.0.1:18082/health', timeout=3) as response:
            return response.status == 200
    except Exception:
        return False

def identity(model, budget, max_seqs=None):
    found = []
    for directory in Path('/proc').iterdir():
        if not directory.name.isdecimal():
            continue
        try:
            args = (directory / 'cmdline').read_bytes().decode().split('\0')
            if 'serve' not in args or model not in args or '--port' not in args:
                continue
            if args[args.index('--port') + 1] != '18082':
                continue
            assert float(args[args.index('--gpu-memory-utilization') + 1]) == budget
            assert args[args.index('--max-model-len') + 1] == '16384'
            if max_seqs is not None:
                assert int(args[args.index('--max-num-seqs') + 1]) == max_seqs
            env = dict(entry.split('=', 1) for entry in (directory / 'environ').read_bytes().decode().split('\0') if '=' in entry)
            assert env['CUDA_VISIBLE_DEVICES'] == '1'
            pid = int(directory.name)
            parent = int((directory / 'stat').read_text().split()[3])
            parent_args = Path(f'/proc/{parent}/cmdline').read_bytes().decode().split('\0')
            assert Path(f'/proc/{parent}/cwd').resolve() == LIVE
            assert parent_args[:2] == ['bash', str(LIVE / 'start_qwen35_4b_vllm.sh')]
            assert os.getpgid(pid) == parent and os.getpgid(parent) == parent
            found.append((pid, parent))
        except (FileNotFoundError, ProcessLookupError, PermissionError):
            continue
    assert len(found) == 1, '正式模型身份不唯一或配置不匹配'
    return found[0]

def gpu():
    output = subprocess.check_output(['nvidia-smi', '-i', '1', '--query-gpu=memory.used,memory.free',
                                      '--format=csv,noheader,nounits'], text=True)
    used, free = [int(value.strip()) for value in output.strip().split(',')]
    rows = subprocess.check_output(['nvidia-smi', '-i', '1', '--query-compute-apps=pid,used_memory',
                                     '--format=csv,noheader,nounits'], text=True)
    return {'used_mib': used, 'free_mib': free,
            'processes': [{'pid': int(a), 'memory_mib': int(b)} for row in rows.splitlines()
                          for a, b in [row.split(',')] if a.strip().isdigit() and b.strip().isdigit()]}

def wait_idle():
    deadline, quiet = time.monotonic() + 60, 0
    while time.monotonic() < deadline:
        with urllib.request.urlopen('http://127.0.0.1:18082/metrics', timeout=5) as response:
            metrics = response.read().decode()
        values = []
        for name in ['running', 'waiting']:
            samples = re.findall(r'^vllm:num_requests_' + name + r'(?:\{[^}]*\})?\s+([0-9.eE+-]+)', metrics, re.M)
            assert samples, '模型负载指标缺失'
            values.extend(float(value) for value in samples)
        quiet = quiet + 1 if all(value == 0 for value in values) else 0
        if quiet >= 2:
            return
        time.sleep(1)
    raise TimeoutError('未取得模型空闲窗口')

def wait_closed(timeout=90):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if closed():
            return
        time.sleep(0.5)
    raise TimeoutError('本次模型端口未关闭，拒绝启动第二个实例')

def stop_identity(expected, model, budget, max_seqs=None):
    assert identity(model, budget, max_seqs) == expected
    os.killpg(expected[1], signal.SIGTERM)
    wait_closed()
    deadline = time.monotonic() + 60
    while time.monotonic() < deadline:
        path = Path(f'/proc/{expected[0]}/cmdline')
        if not path.exists() or not path.read_bytes():
            return
        time.sleep(0.5)
    raise TimeoutError('原模型进程未退出')

def start(log_name):
    assert closed()
    READY.unlink(missing_ok=True)
    with (LIVE / log_name).open('ab', buffering=0) as log:
        return subprocess.Popen(['bash', str(LIVE / 'run_qwen35_4b_vllm.sh')], cwd=LIVE,
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)

def wait_ready(process):
    deadline = time.monotonic() + 660
    while time.monotonic() < deadline:
        assert process.poll() is None, '本次启动器退出；检查对应日志'
        if READY.exists() and health():
            probe = json.loads(Path(str(READY) + '.structured-output.json').read_text())
            assert probe['status'] == 'PASS' and 'named_tool_concurrency_8' in probe['cases']
            return probe
        time.sleep(2)
    raise TimeoutError('模型启动等待超时')

def stop_owned(process):
    if process is None:
        assert closed()
        return
    path = Path(f'/proc/{process.pid}/cmdline')
    if path.exists() and path.read_bytes():
        assert os.getpgid(process.pid) == process.pid
        assert Path(f'/proc/{process.pid}/cwd').resolve() == LIVE
        os.killpg(process.pid, signal.SIGTERM)
        try:
            process.wait(timeout=60)
        except subprocess.TimeoutExpired:
            os.killpg(process.pid, signal.SIGKILL)
            process.wait(timeout=20)
    wait_closed()
