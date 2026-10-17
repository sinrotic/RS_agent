"""采集正式同卡部署前证据，保留原脚本与配置摘要。"""
import json
import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, '/tmp/rs-agent-partial-quantization-20261011')
import deployment_runtime as runtime

def run(retry=False):
    state = json.loads((runtime.LIVE / 'partial-quantization-memory50-state.json').read_text())
    assert state['promoted'] and not state['rollback']
    identity = runtime.identity(state['updates']['MODEL_PATH'], .50, 128)
    assert identity == (state['api_pid'], state['launcher_pid'])
    assert runtime.digest(runtime.LIVE / '.env') == state['deployed_env_sha256']
    before = {'api_pid': identity[0], 'launcher_pid': identity[1], 'model_path': state['updates']['MODEL_PATH'],
        'env_sha256': state['deployed_env_sha256'], 'gpu_memory': runtime.gpu(),
        'file_sha256': {name: runtime.digest(runtime.LIVE / name) for name in state['baseline_sha256']}}
    snapshot = ROOT / ('production-retry-before-state.json' if retry else 'production-before-state.json')
    assert not snapshot.exists()
    snapshot.write_text(json.dumps(before, ensure_ascii=False, indent=2) + '\n')
    runtime.wait_idle()
    subprocess.run([sys.executable, str(ROOT / 'serving_benchmark.py'), '--base-url', 'http://127.0.0.1:18082/v1',
                    '--label', 'production_retry_before' if retry else 'production_before'], check=True, timeout=420)
    assert runtime.identity(state['updates']['MODEL_PATH'], .50, 128) == identity
    assert runtime.digest(runtime.LIVE / '.env') == before['env_sha256']
    print('正式同卡性能基线通过，模型及配置未变', flush=True)

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--retry', action='store_true')
    run(parser.parse_args().retry)
