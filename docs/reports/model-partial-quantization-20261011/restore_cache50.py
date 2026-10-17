"""核验本次缓存扩容；显式 --apply 恢复部分量化 / 40% 配置。"""
import argparse
import importlib.util
import json
from pathlib import Path

LIVE = Path('/home/luo/RS_agent_java/model_deploy')
STATE = LIVE / 'partial-quantization-memory50-state.json'
spec = importlib.util.spec_from_file_location('partial_runtime', LIVE / 'partial_quantization_runtime_20261011.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    report = json.loads(STATE.read_text())
    assert report['promoted'] and not report['rollback']
    assert runtime.digest(LIVE / '.env') == report['deployed_env_sha256']
    for name, digest in report['baseline_sha256'].items():
        if name != '.env':
            assert runtime.digest(LIVE / name) == digest
    expected = runtime.identity(report['updates']['MODEL_PATH'], 0.50, 128)
    assert expected == (report['api_pid'], report['launcher_pid'])
    backup = Path(report['backup'])
    assert backup.resolve().parent == LIVE and backup.name.startswith('backup-partial-cache50-')
    assert runtime.digest(backup / '.env') == report['baseline_sha256']['.env']
    print('部分量化 50% / 128 配置、进程及前一版 40% 备份核验通过', flush=True)
    if not args.apply:
        return
    runtime.wait_idle()
    runtime.stop_identity(expected, report['updates']['MODEL_PATH'], 0.50, 128)
    runtime.atomic(LIVE / '.env', (backup / '.env').read_bytes())
    process = runtime.start('partial-quantization-memory50-restore40.log')
    runtime.wait_ready(process)
    api, launcher = runtime.identity(report['updates']['MODEL_PATH'], 0.40, 64)
    prior = json.loads(runtime.STATE.read_text())
    assert prior['updates']['MODEL_PATH'] == report['updates']['MODEL_PATH']
    assert prior['deployed_env_sha256'] == runtime.digest(LIVE / '.env')
    prior.update(api_pid=api, launcher_pid=launcher, restored_by_cache50=True)
    runtime.atomic(runtime.STATE, (json.dumps(prior, ensure_ascii=False, indent=2) + '\n').encode())
    report.update(promoted=False, rollback=True, health=runtime.health(), restored_api_pid=api, restored_launcher_pid=launcher)
    runtime.atomic(STATE, (json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode())
    print('部分量化 / 40% / 64 已恢复，启动探针及健康通过', flush=True)

if __name__ == '__main__':
    main()
