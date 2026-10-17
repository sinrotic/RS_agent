"""核验本次预热优化；显式 --apply 恢复前一版 50% / 128 的配置与脚本。"""
import argparse
import importlib.util
import json
from pathlib import Path

LIVE = Path('/home/luo/RS_agent_java/model_deploy')
STATE = LIVE / 'model-serving-next-state-20261011.json'
PRIOR = LIVE / 'partial-quantization-memory50-state.json'
spec = importlib.util.spec_from_file_location('runtime', LIVE / 'partial_quantization_runtime_20261011.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    report = json.loads(STATE.read_text())
    assert report['promoted'] and not report['rollback']
    assert runtime.digest(LIVE / '.env') == report['deployed_env_sha256']
    for name, digest in report['deployed_file_sha256'].items():
        assert runtime.digest(LIVE / name) == digest
    expected = runtime.identity(report['model_path'], .50, 128)
    assert expected == (report['api_pid'], report['launcher_pid'])
    backup = Path(report['backup'])
    assert backup.resolve().parent == LIVE and backup.name.startswith('backup-serving-next-')
    for name in ['.env', 'start_qwen35_4b_vllm.sh', 'vllm_prefix_warmup.py']:
        assert runtime.digest(backup / name) == report['baseline_sha256'][name]
    prior = json.loads((backup / 'previous-state.json').read_text())
    assert prior['promoted'] and not prior['rollback']
    assert prior['deployed_env_sha256'] == report['baseline_sha256']['.env']
    print('正式预热优化的配置、进程及前一版 50% / 128 备份核验通过', flush=True)
    if not args.apply:
        return
    runtime.wait_idle()
    runtime.stop_identity(expected, report['model_path'], .50, 128)
    runtime.atomic(LIVE / 'start_qwen35_4b_vllm.sh', (backup / 'start_qwen35_4b_vllm.sh').read_bytes(), report['previous_start_mode'])
    runtime.atomic(LIVE / 'vllm_prefix_warmup.py', (backup / 'vllm_prefix_warmup.py').read_bytes(), report['previous_warmup_mode'])
    runtime.atomic(LIVE / '.env', (backup / '.env').read_bytes())
    process = runtime.start('model-serving-next-restore50-20261011.log')
    runtime.wait_ready(process)
    api, launcher = runtime.identity(report['model_path'], .50, 128)
    prior.update(api_pid=api, launcher_pid=launcher, restored_by_next_optimization=True)
    runtime.atomic(PRIOR, (json.dumps(prior, ensure_ascii=False, indent=2) + '\n').encode())
    report.update(promoted=False, rollback=True, restored_api_pid=api,
                  restored_launcher_pid=launcher, health=runtime.health())
    runtime.atomic(STATE, (json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode())
    print('前一版部分量化 / 50% / 128 已恢复，原启动探针及健康通过', flush=True)


if __name__ == '__main__':
    main()
