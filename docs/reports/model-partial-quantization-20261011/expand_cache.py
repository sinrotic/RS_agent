"""按用户授权扩大 KV / 状态预算；模型精度保持原部分量化。"""
import importlib.util
import json
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import time

import deployment_runtime as runtime
from deploy_production import cleanup_clone

ROOT = Path('/tmp/rs-agent-partial-quantization-20261011')
OLD = Path('/tmp/rs-agent-quantization-retry-20261011')
LIVE = runtime.LIVE
STATE = LIVE / 'partial-quantization-memory50-state.json'
sys.path.insert(0, str(OLD))
from promote import wait_clone_ready

def main():
    assert not STATE.exists() and not (ROOT / 'cache50-deployment-state.json').exists()
    prior = json.loads(runtime.STATE.read_text())
    assert prior['promoted'] and not prior['rollback']
    assert prior['updates']['VLLM_GPU_MEMORY_UTILIZATION'] == '0.40'
    model = prior['updates']['MODEL_PATH']
    candidate = json.loads((ROOT / 'mlp_only-state.json').read_text())
    assert candidate['model_path'] == model and candidate['gpu_memory_utilization'] == 0.50
    assert candidate['max_num_seqs'] == 128 and candidate['model_passed'] and candidate['business_completed']
    rows = json.loads((ROOT / 'mlp_only-business.json').read_text())['business_regression']
    assert len(rows) == 8 and all(row['passed'] and row['failed_tools'] == 0 for row in rows)
    baseline = dict(prior['baseline_sha256'])
    baseline['.env'] = prior['deployed_env_sha256']
    for name, digest in baseline.items():
        assert runtime.digest(LIVE / name) == digest
    initial = runtime.identity(model, 0.40, 64)
    assert initial == (prior['api_pid'], prior['launcher_pid']) and runtime.health()
    assert all(runtime.closed(port) for port in [18314, 18092, 18094])
    helper_spec = importlib.util.spec_from_file_location('old_runtime', '/tmp/rs-serving-tuning-20261011/deploy.py')
    helper = importlib.util.module_from_spec(helper_spec)
    helper_spec.loader.exec_module(helper)
    helper.wait_external_validation()
    runtime.wait_idle()
    cache_target = LIVE / 'quantization-cache/20261011-mlp-int4-bf16-memory50'
    assert not cache_target.exists()
    shutil.copytree(Path(prior['updates']['VLLM_CACHE_ROOT']), cache_target)
    backup = LIVE / ('backup-partial-cache50-' + time.strftime('%Y%m%d-%H%M%S'))
    backup.mkdir(mode=0o700)
    original = (LIVE / '.env').read_bytes()
    runtime.atomic(backup / '.env', original)
    runtime.atomic(backup / 'previous-state.json', (json.dumps(prior, ensure_ascii=False, indent=2) + '\n').encode())
    updates = {'MODEL_PATH': model, 'VLLM_GPU_MEMORY_UTILIZATION': '0.50',
               'VLLM_MAX_NUM_SEQS': '128', 'VLLM_CACHE_ROOT': str(cache_target)}
    lines = original.decode().splitlines()
    for key in updates:
        assert sum(line.startswith(key + '=') for line in lines) <= 1
    contents = '\n'.join(line for line in lines if line.split('=', 1)[0] not in updates) + '\n'
    contents += '\n'.join(key + '=' + shlex.quote(value) for key, value in updates.items()) + '\n'
    restore = LIVE / 'restore_qwen35_4b_partial_memory50.py'
    assert not restore.exists()
    runtime.atomic(restore, (ROOT / 'restore_cache50.py').read_bytes(), 0o700)
    report = {'authorization': '用户要求扩大缓存，以支持更多并发；选择已验收的 50% / 128 档',
              'precision': prior['precision'], 'updates': updates, 'previous_budget': 0.40,
              'previous_max_num_seqs': 64, 'previous_api_pid': initial[0], 'previous_launcher_pid': initial[1],
              'baseline_sha256': baseline, 'backup': str(backup), 'restore_script': str(restore),
              'gpu_before': runtime.gpu(), 'promoted': False, 'rollback': False,
              'known_limitations': ['保留已有规划稳定性限制，不把缓存扩容称为工具可靠性修复',
                                    '16 路短工具探针不能代表满 16K 或持续负载吞吐']}
    def save():
        data = (json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode()
        runtime.atomic(ROOT / 'cache50-deployment-state.json', data)
        runtime.atomic(STATE, data)
    save()
    owned, stopped = None, False
    try:
        runtime.wait_idle()
        assert runtime.digest(LIVE / '.env') == baseline['.env']
        print('原部分量化 / 40% 已备份，开始扩大到 50% / 128', flush=True)
        stopped = True
        runtime.stop_identity(initial, model, 0.40, 64)
        runtime.atomic(LIVE / '.env', contents.encode())
        owned = runtime.start('partial-quantization-memory50-20261011.log')
        report['launcher_pid'] = owned.pid
        save()
        report['probe'] = runtime.wait_ready(owned)
        api, launcher = runtime.identity(model, 0.50, 128)
        assert launcher == owned.pid
        report.update(api_pid=api, deployed_env_sha256=runtime.digest(LIVE / '.env'))
        save()
        runtime.wait_idle()
        subprocess.run([sys.executable, str(OLD / 'model_direct.py'), '--base-url', 'http://127.0.0.1:18082/v1',
                        '--output', str(ROOT / 'cache50-production-model.json')], check=True, timeout=360)
        report['model_regression_passed'] = True
        subprocess.run([sys.executable, str(ROOT / 'concurrency_probe.py'), '--label', 'cache50_after'], check=True, timeout=180)
        report['concurrency_probe_passed'] = True
        runtime.atomic(ROOT / 'accounts.json', Path('/tmp/rs-agent-e2e-20261010-llm-opt-20261011/accounts.json').read_bytes())
        subprocess.run([sys.executable, str(OLD / 'clone.py'), '--model-port', '18082'], check=True)
        clone = json.loads(subprocess.check_output(['docker', 'inspect', 'rs-quantization-20261011-agent'], text=True))[0]
        report['own_clone_id'] = clone['Id']
        save()
        wait_clone_ready()
        subprocess.run([sys.executable, str(ROOT / 'business_compare.py'), '--label', 'production_cache50'], check=True, timeout=480)
        rows = json.loads((ROOT / 'production_cache50-business.json').read_text())['business_regression']
        report.update(business_passed=sum(row['passed'] for row in rows), business_total=len(rows))
        assert len(rows) == 8 and all(row['passed'] and row['failed_tools'] == 0 for row in rows)
        runtime.wait_idle()
        report.update(health=runtime.health(), gpu_after=runtime.gpu())
        assert report['health'] and runtime.identity(model, 0.50, 128) == (api, launcher)
        report['additional_memory_mib'] = report['gpu_after']['used_mib'] - report['gpu_before']['used_mib']
        assert report['gpu_after']['free_mib'] >= 8000, '扩大后剩余显存低于预期'
        for name, digest in baseline.items():
            if name != '.env':
                assert runtime.digest(LIVE / name) == digest
        report['promoted'] = True
        save()
        subprocess.run([sys.executable, str(restore)], check=True)
        print('部分量化 / 50% / 128 扩容与正式验收通过', flush=True)
    except BaseException as error:
        report.update(promoted=False, failure_type=type(error).__name__, failure=str(error))
        if stopped:
            if owned is not None:
                runtime.stop_owned(owned)
            else:
                runtime.wait_closed()
            runtime.atomic(LIVE / '.env', original)
            restored = runtime.start('partial-quantization-memory50-rollback40.log')
            runtime.wait_ready(restored)
            api, launcher = runtime.identity(model, 0.40, 64)
            prior.update(api_pid=api, launcher_pid=launcher, restored_by_cache50_attempt=True)
            runtime.atomic(runtime.STATE, (json.dumps(prior, ensure_ascii=False, indent=2) + '\n').encode())
            report.update(rollback=True, restored_api_pid=api, restored_launcher_pid=launcher, health=runtime.health())
        raise
    finally:
        try:
            cleanup_clone(report)
        finally:
            save()

if __name__ == '__main__':
    main()
