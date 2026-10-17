"""GPU 2 比较两种原 BF16 敏感模块方案；仅关闭本脚本创建的模型。"""
import argparse
import fcntl
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import time

ROOT = Path('/tmp/rs-agent-partial-quantization-20261011')
OLD = Path('/tmp/rs-agent-quantization-retry-20261011')

def memory():
    return int(subprocess.check_output(['nvidia-smi', '-i', '2', '--query-gpu=memory.used',
                                      '--format=csv,noheader,nounits'], text=True).strip())

def atomic(path, value):
    temporary = path.with_name(path.name + '.partial-next')
    with temporary.open('x') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    temporary.chmod(0o600)
    temporary.replace(path)

def wait_control():
    deadline = time.monotonic() + 480
    while time.monotonic() < deadline:
        path = ROOT / 'control-business.json'
        if path.exists() and len(json.loads(path.read_text())['business_regression']) == 8:
            return
        time.sleep(2)
    raise TimeoutError('控制阶段未完成，不切换捕获代理')

def run(mode, label=None, budget=0.50, max_seqs=128):
    label = label or mode
    source = json.loads((ROOT / (mode + '-source.json')).read_text())
    with socket.socket() as connection:
        assert connection.connect_ex(('127.0.0.1', 18092)) != 0
    deadline = time.monotonic() + 180
    while memory() >= 512 and time.monotonic() < deadline:
        time.sleep(2)
    assert memory() < 512, 'GPU 2 已有其他任务，不启动候选'
    ready = ROOT / (label + '.ready')
    assert not ready.exists()
    env = {**os.environ, 'CUDA_VISIBLE_DEVICES': '2', 'VLLM_PORT': '18092', 'MODEL_PATH': source['path'],
           'VLLM_MAX_MODEL_LEN': '16384', 'VLLM_GPU_MEMORY_UTILIZATION': str(budget),
           'VLLM_QUANTIZATION': 'auto', 'VLLM_QUANTIZATION_CONFIG': '', 'VLLM_TEST_FORCE_FP8_MARLIN': '0',
           'VLLM_JSON_COMPACT_OUTPUT': 'true', 'VLLM_READY_FILE': str(ready),
           'VLLM_CACHE_ROOT': str(ROOT / 'cache' / mode), 'VLLM_PREFIX_KEEPALIVE': 'false',
           'VLLM_WARMUP_PAYLOAD_FILE': str(OLD / 'replay-payloads.private.json'),
           'VLLM_WARMUP_MAX_TOKENS': '1', 'VLLM_WARMUP_CONCURRENCY': '8', 'VLLM_DELAY_AFTER_WARMUP_SEC': '0',
           'VLLM_READY_TIMEOUT_SEC': '600', 'VLLM_STRUCTURED_OUTPUT_PROBE': 'true',
           'VLLM_ENFORCE_STRICT_TOOL_CALLING': 'true', 'VLLM_SPECULATIVE_CONFIG': '',
           'VLLM_LANGUAGE_MODEL_ONLY': 'false', 'VLLM_MAX_NUM_SEQS': str(max_seqs), 'VLLM_MAX_NUM_BATCHED_TOKENS': '',
           'PYTHON_BIN': sys.executable}
    report = {'mode': mode, 'label': label, 'model_path': source['path'], 'gpu': 2, 'gpu_memory_utilization': budget,
              'max_num_seqs': max_seqs, 'model_passed': False, 'business_completed': False}
    with (ROOT / (label + '.log')).open('w') as log:
        process = subprocess.Popen(['bash', str(OLD / 'model/start_qwen35_4b_vllm.sh')],
            cwd=OLD / 'model', env=env, stdout=log, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True)
    print('启动候选', mode, flush=True)
    try:
        deadline = time.monotonic() + 660
        while not ready.exists():
            assert process.poll() is None, '候选启动器退出'
            if time.monotonic() > deadline:
                raise TimeoutError('候选模型启动超时')
            time.sleep(2)
        report['probe'] = json.loads(Path(str(ready) + '.structured-output.json').read_text())
        subprocess.run([sys.executable, str(OLD / 'model_direct.py'), '--base-url', 'http://127.0.0.1:18092/v1',
            '--output', str(ROOT / (label + '-model.json'))], check=True, timeout=360)
        report['model_passed'] = True
        wait_control()
        atomic(ROOT / 'proxy-phase.json', {'port': 18092, 'label': label})
        subprocess.run([sys.executable, str(ROOT / 'business_compare.py'), '--label', label], check=True, timeout=480)
        report['business_completed'] = True
        report['gpu_memory_mib'] = memory()
        print('候选检查完成', mode, flush=True)
    except Exception as error:
        report.update(failure_type=type(error).__name__, failure=str(error))
        print('候选未完成', mode, type(error).__name__, flush=True)
    finally:
        atomic(ROOT / 'proxy-phase.json', {'port': 18082, 'label': 'control'})
        if process.poll() is None:
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=20)
        atomic(ROOT / (label + '-state.json'), report)
        deadline = time.monotonic() + 60
        while True:
            with socket.socket() as connection:
                closed = connection.connect_ex(('127.0.0.1', 18092)) != 0
            if closed:
                break
            assert time.monotonic() < deadline, '本次模型端口仍开放'
            time.sleep(0.2)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--mode', choices=['mlp_only', 'gdn_bf16'])
    parser.add_argument('--label', choices=['winner_low_memory'])
    parser.add_argument('--budget', type=float, default=0.50)
    parser.add_argument('--max-seqs', type=int, default=128)
    args = parser.parse_args()
    assert 0.35 <= args.budget <= 0.50 and 8 <= args.max_seqs <= 128
    assert not args.label or args.mode
    with open('/tmp/rs-serving-tuning-gpu2.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        for mode in ([args.mode] if args.mode else ['mlp_only', 'gdn_bf16']):
            run(mode, args.label, args.budget, args.max_seqs)
