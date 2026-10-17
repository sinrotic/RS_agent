"""恢复后的原配置按相同模型、业务与规划顺序对照，核验重启状态的影响。"""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, '/tmp/rs-agent-partial-quantization-20261011')
import deployment_runtime as runtime


def main():
    prior = json.loads((runtime.LIVE / 'partial-quantization-memory50-state.json').read_text())
    failed = json.loads((ROOT / 'production-final-deployment-state.json').read_text())
    assert failed['rollback'] and not failed['promoted'] and failed['health']
    identity = runtime.identity(prior['updates']['MODEL_PATH'], .50, 128)
    assert identity == (prior['api_pid'], prior['launcher_pid'])
    assert runtime.digest(runtime.LIVE / '.env') == prior['deployed_env_sha256']
    for name, digest in prior['baseline_sha256'].items():
        if name != '.env':
            assert runtime.digest(runtime.LIVE / name) == digest
    before = {'api_pid': identity[0], 'launcher_pid': identity[1], 'model_path': prior['updates']['MODEL_PATH'],
        'env_sha256': prior['deployed_env_sha256'], 'gpu_memory': runtime.gpu(),
        'file_sha256': {name: runtime.digest(runtime.LIVE / name) for name in prior['baseline_sha256']}}
    with (ROOT / 'production-control-before-state.json').open('x') as handle:
        handle.write(json.dumps(before, ensure_ascii=False, indent=2) + '\n')
    runtime.wait_idle()
    subprocess.run([sys.executable, str(ROOT / 'serving_benchmark.py'), '--base-url', 'http://127.0.0.1:18082/v1',
                    '--label', 'production_control'], check=True, timeout=420)
    subprocess.run([sys.executable, '/tmp/rs-agent-quantization-retry-20261011/model_direct.py',
                    '--base-url', 'http://127.0.0.1:18082/v1', '--output', str(ROOT / 'production_control-model.json')], check=True, timeout=360)
    subprocess.run([sys.executable, str(ROOT / 'functional_probe.py'), '--base-url', 'http://127.0.0.1:18082/v1',
                    '--label', 'production_control'], check=True, timeout=90)
    subprocess.run([sys.executable, str(ROOT / 'business_validation.py'), '--model-port', '18082',
                    '--label', 'production_control'], check=True, timeout=540)
    subprocess.run([sys.executable, str(ROOT / 'planning_probe.py'), '--port', '18082',
                    '--label', 'production_control'], check=True, timeout=360)
    assert runtime.identity(prior['updates']['MODEL_PATH'], .50, 128) == identity
    for name, digest in before['file_sha256'].items():
        assert runtime.digest(runtime.LIVE / name) == digest
    planning = json.loads((ROOT / 'production_control-planning.json').read_text())
    print('原配置按相同完整顺序对照完成，规划未完成', planning['incomplete_generations'], '个', flush=True)


if __name__ == '__main__':
    main()
