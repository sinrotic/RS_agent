"""GPU 2 单变量批次试验，只停止本次创建的进程。"""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request

ROOT = Path(__file__).resolve().parent
LIVE = Path('/home/luo/RS_agent_java/model_deploy')
PARTIAL = Path('/tmp/rs-agent-partial-quantization-20261011')
OLD = Path('/tmp/rs-agent-quantization-retry-20261011')

def memory():
    return int(subprocess.check_output(['nvidia-smi', '-i', '2', '--query-gpu=memory.used', '--format=csv,noheader,nounits'], text=True).strip())

def closed():
    with socket.socket() as connection:
        return connection.connect_ex(('127.0.0.1', 18092)) != 0

def save(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n')

def run(label, budget=None, speculative=False, business=False, prewarm16=False, expanded=False, prefix=False):
    assert memory() < 512 and closed(), 'GPU 2 或候选端口已有其他任务'
    assert not (ROOT / (label + '-state.json')).exists(), '不覆盖试验记录'
    prior = json.loads((LIVE / 'partial-quantization-memory50-state.json').read_text())
    assert prior['promoted'] and not prior['rollback']
    model = prior['updates']['MODEL_PATH']
    env = {**os.environ, 'VLLM_VENV': '/mnt/data/luo/venvs/rsagent-vllm', 'PYTHON_BIN': sys.executable,
        'MODEL_PATH': model, 'CUDA_VISIBLE_DEVICES': '2', 'VLLM_PORT': '18092', 'VLLM_HOST': '127.0.0.1',
        'VLLM_MAX_MODEL_LEN': '16384', 'VLLM_GPU_MEMORY_UTILIZATION': '0.50', 'VLLM_MAX_NUM_SEQS': '128',
        'VLLM_MAX_NUM_BATCHED_TOKENS': str(budget) if budget else '',
        'VLLM_SPECULATIVE_CONFIG': json.dumps({'method': 'mtp', 'num_speculative_tokens': 1}) if speculative else '',
        'VLLM_QUANTIZATION': 'auto', 'VLLM_QUANTIZATION_CONFIG': '', 'VLLM_JSON_COMPACT_OUTPUT': 'true',
        'VLLM_LANGUAGE_MODEL_ONLY': 'false', 'VLLM_STRUCTURED_OUTPUT_PROBE': 'true',
        'VLLM_ENFORCE_STRICT_TOOL_CALLING': 'true', 'VLLM_READY_FILE': str(ROOT / (label + '.ready')),
        'VLLM_PREFIX_KEEPALIVE': 'false', 'VLLM_DELAY_AFTER_WARMUP_SEC': '0',
        'VLLM_WARMUP_PAYLOAD_FILE': str(OLD / 'replay-payloads.private.json'),
        'VLLM_WARMUP_MAX_TOKENS': '1', 'VLLM_WARMUP_CONCURRENCY': '8', 'VLLM_READY_TIMEOUT_SEC': '660',
        'VLLM_CACHE_ROOT': str(ROOT / 'cache'), 'VLLM_SERVER_DEV_MODE': '1'}
    env['VLLM_EXTRA_WARMUP_CONCURRENCY'] = '16' if prewarm16 else '0'
    if prewarm16:
        env['WARMUP_SCRIPT'] = str(ROOT / 'model/warmup_optimized.py')
    if expanded:
        from prefix_probe import build
        env['VLLM_WARMUP_PAYLOAD_FILE'] = str(build())
    report = {'label': label, 'model_path': model, 'budget': .50, 'max_num_seqs': 128,
        'max_num_batched_tokens_requested': budget, 'mtp': speculative, 'prewarm16': prewarm16,
        'expanded_prefixes': expanded, 'final_prefix_refresh': prewarm16, 'passed': False}
    ready = Path(env['VLLM_READY_FILE'])
    assert not ready.exists()
    with (ROOT / (label + '.log')).open('w') as log:
        script = ROOT / 'model' / ('start_optimized.sh' if prewarm16 else 'start_qwen35_4b_vllm.sh')
        process = subprocess.Popen(['bash', str(script)], env=env, cwd=ROOT / 'model',
            stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    report['launcher_pid'] = process.pid
    print('启动隔离候选', label, flush=True)
    try:
        deadline = time.monotonic() + 720
        while not ready.exists():
            assert process.poll() is None, '候选启动失败'
            assert time.monotonic() < deadline, '候选启动超时'
            time.sleep(2)
        report['probe'] = json.loads(Path(str(ready) + '.structured-output.json').read_text())
        assert report['probe']['status'] == 'PASS'
        if prewarm16:
            report['extra_probe'] = json.loads(Path(str(ready) + '.extra-warmup.json').read_text())
            assert report['extra_probe']['status'] == 'PASS' and 'named_tool_concurrency_16' in report['extra_probe']['cases']
        try:
            with urllib.request.urlopen('http://127.0.0.1:18092/server_info?config_format=json', timeout=60) as response:
                info = json.load(response)['vllm_config']
            report['resolved_scheduler'] = {k: info['scheduler_config'].get(k) for k in
                ['max_num_batched_tokens', 'max_num_seqs', 'async_scheduling', 'enable_chunked_prefill']}
            report['resolved_cache'] = {k: info['cache_config'].get(k) for k in ['block_size', 'mamba_cache_mode', 'cache_dtype']}
        except Exception as error:
            report['resolved_unavailable'] = type(error).__name__
        save(ROOT / (label + '-state.json'), report)
        if prefix:
            subprocess.run([sys.executable, str(ROOT / 'prefix_probe.py'), '--base-url', 'http://127.0.0.1:18092/v1',
                            '--label', label], check=True, timeout=120)
        subprocess.run([sys.executable, str(ROOT / 'serving_benchmark.py'), '--base-url', 'http://127.0.0.1:18092/v1',
                        '--label', label], check=True, timeout=420)
        subprocess.run([sys.executable, str(OLD / 'model_direct.py'), '--base-url', 'http://127.0.0.1:18092/v1',
                        '--output', str(ROOT / (label + '-model.json'))], check=True, timeout=360)
        if business:
            subprocess.run([sys.executable, str(ROOT / 'functional_probe.py'), '--base-url', 'http://127.0.0.1:18092/v1',
                            '--label', label], check=True, timeout=90)
            subprocess.run([sys.executable, str(ROOT / 'business_validation.py'), '--model-port', '18092',
                            '--label', label], check=True, timeout=540)
            if speculative or expanded or prewarm16:
                subprocess.run([sys.executable, str(ROOT / 'planning_probe.py'), '--port', '18092',
                                '--label', label], check=True, timeout=360)
        report.update(passed=True, gpu_used_mib=memory())
        print('隔离性能和模型回归通过', label, flush=True)
    except Exception as error:
        report.update(failure_type=type(error).__name__, failure=str(error))
        print('候选未通过', label, type(error).__name__, flush=True)
    finally:
        if process.poll() is None:
            assert os.getpgid(process.pid) == process.pid
            assert Path(f'/proc/{process.pid}/cwd').resolve() == ROOT / 'model'
            os.killpg(process.pid, signal.SIGTERM)
            try:
                process.wait(timeout=60)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
                process.wait(timeout=15)
        deadline = time.monotonic() + 60
        while not closed() or memory() >= 512:
            assert time.monotonic() < deadline, '候选退出后资源未释放，不清理其他进程'
            time.sleep(1)
        report['owned_cleanup_passed'] = True
        save(ROOT / (label + '-state.json'), report)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--extra-label')
    parser.add_argument('--batch', type=int, choices=[2048, 4096, 8192])
    parser.add_argument('--mtp', action='store_true')
    parser.add_argument('--business', action='store_true')
    parser.add_argument('--prewarm16', action='store_true')
    parser.add_argument('--expanded-prefixes', action='store_true')
    parser.add_argument('--prefix', action='store_true')
    args = parser.parse_args()
    with open('/tmp/rs-serving-tuning-gpu2.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        model_dir = ROOT / 'model'
        model_dir.mkdir(exist_ok=True)
        for name in ['start_qwen35_4b_vllm.sh', 'vllm_prefix_warmup.py', 'vllm_structured_output_probe.py']:
            target = model_dir / name
            if not target.exists():
                shutil.copy2(LIVE / name, target)
            assert hashlib.sha256(target.read_bytes()).digest() == hashlib.sha256((LIVE / name).read_bytes()).digest()
        cache = ROOT / 'cache'
        if not cache.exists():
            shutil.copytree(LIVE / 'quantization-cache/20261011-mlp-int4-bf16-memory50', cache)
        if args.extra_label:
            run(args.extra_label, args.batch, args.mtp, args.business, args.prewarm16, args.expanded_prefixes, args.prefix)
        else:
            for label, budget in [('default_before', None), ('batch4096', 4096), ('batch8192', 8192), ('default_after', None)]:
                run(label, budget)
