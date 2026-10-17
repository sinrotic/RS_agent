"""核验本次部署；--apply 恢复切换前 INT4 / 50% 配置。"""
import argparse
import importlib.util
import json
from pathlib import Path

LIVE = Path('/home/luo/RS_agent_java/model_deploy')
spec = importlib.util.spec_from_file_location('partial_runtime', LIVE / 'partial_quantization_runtime_20261011.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    report = json.loads(runtime.STATE.read_text())
    assert report['promoted'] and not report['rollback']
    assert runtime.digest(LIVE / '.env') == report['deployed_env_sha256']
    for name, digest in report['baseline_sha256'].items():
        if name != '.env':
            assert runtime.digest(LIVE / name) == digest
    expected = runtime.identity(report['updates']['MODEL_PATH'], 0.40, 64)
    assert expected == (report['api_pid'], report['launcher_pid'])
    backup = Path(report['backup'])
    assert backup.resolve().parent == LIVE and backup.name.startswith('backup-partial-quantization-')
    assert runtime.digest(backup / '.env') == report['baseline_sha256']['.env']
    print('本次部分量化进程、40% 配置及前一版 INT4 备份核验通过', flush=True)
    if not args.apply:
        return
    runtime.wait_idle()
    runtime.stop_identity(expected, report['updates']['MODEL_PATH'], 0.40, 64)
    runtime.atomic(LIVE / '.env', (backup / '.env').read_bytes())
    process = runtime.start('partial-quantization-memory40-restore.log')
    runtime.wait_ready(process)
    api, launcher = runtime.identity(report['previous_model_path'], 0.50)
    report.update(promoted=False, rollback=True, restored_api_pid=api,
                  restored_launcher_pid=launcher, health=runtime.health())
    previous_file = LIVE / 'quantization-memory50-state.json'
    previous = json.loads(previous_file.read_text())
    assert previous['updates']['MODEL_PATH'] == report['previous_model_path']
    assert previous['deployed_env_sha256'] == runtime.digest(LIVE / '.env')
    previous.update(api_pid=api, launcher_pid=launcher, restored_by_partial_memory40=True)
    runtime.atomic(previous_file, (json.dumps(previous, ensure_ascii=False, indent=2) + '\n').encode())
    runtime.atomic(runtime.STATE, (json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode())
    print('切换前 INT4 / 50% 已恢复，健康及结构化探针通过', flush=True)

if __name__ == '__main__':
    main()
