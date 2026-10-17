"""用户授权的 MLP INT4 / 注意力 GDN BF16 正式部署，失败恢复此前 INT4。"""
import hashlib
import importlib.util
import json
from pathlib import Path
import shlex
import shutil
import stat
import subprocess
import sys
import time

import deployment_runtime as runtime
from export_hybrid import inventory, bytes_count

ROOT = Path('/tmp/rs-agent-partial-quantization-20261011')
OLD = Path('/tmp/rs-agent-quantization-retry-20261011')
LIVE = runtime.LIVE
sys.path.insert(0, str(OLD))
from promote import wait_clone_ready

def check_weights():
    inputs = json.loads((ROOT / 'deployment-input.json').read_text())
    assert runtime.digest(ROOT / 'mlp_only-source.json') == inputs['source_manifest_sha256']
    source = json.loads((ROOT / 'mlp_only-source.json').read_text())
    target = Path(source['path'])
    assert target == Path('/mnt/data/luo/models/Qwen3.5-4B-INT4-MLP-BF16-sensitive-20261011')
    assert source['int4_modules'] == 96 and source['payload_roundtrip_verified']
    records = inventory(target)
    assert set(records) == set(source['tensor_sha256'])
    for name, item in records.items():
        digest = hashlib.sha256()
        remaining = bytes_count(item)
        with item['file'].open('rb') as handle:
            handle.seek(item['header_bytes'] + item['data_offsets'][0])
            while remaining:
                chunk = handle.read(min(8 * 1024 * 1024, remaining))
                assert chunk
                digest.update(chunk)
                remaining -= len(chunk)
        assert digest.hexdigest() == source['tensor_sha256'][name], '候选 tensor 摘要变化'
    for name, digest in source['asset_sha256'].items():
        assert runtime.digest(target / name) == digest
    quant = json.loads((target / 'config.json').read_text())['quantization_config']
    assert quant['bits'] == 4 and quant['block_name_to_quantize'] == [f'model.language_model.layers.{i}.mlp' for i in range(32)]
    state = json.loads((ROOT / 'winner_low_memory-state.json').read_text())
    assert state['model_path'] == str(target) and state['gpu_memory_utilization'] == 0.40
    assert state['max_num_seqs'] == 64 and state['model_passed'] and state['business_completed']
    rows = json.loads((ROOT / 'winner_low_memory-business.json').read_text())['business_regression']
    assert len(rows) == 8 and all(row['passed'] and row['failed_tools'] == 0 for row in rows)
    assert json.loads((ROOT / 'resolved-config-check.json').read_text())['matched']
    print('候选全部 tensor、原分词器资产、INT4 范围与隔离验收记录核验通过', flush=True)
    return source

def cleanup_clone(report):
    name = 'rs-quantization-20261011-agent'
    inspection = subprocess.run(['docker', 'inspect', name], capture_output=True, text=True)
    if inspection.returncode == 0:
        container = json.loads(inspection.stdout)[0]
        assert report.get('own_clone_id') == container['Id'], '验收容器身份变化，拒绝清理'
        env = dict(row.split('=', 1) for row in container['Config']['Env'] if '=' in row)
        assert container['Config']['Labels']['rsagent.quantization-task'] == '20261011'
        assert env['SERVER_PORT'] == '18314' and env['SERVER_ADDRESS'] == '127.0.0.1'
        subprocess.run(['docker', 'stop', name], check=True, stdout=subprocess.DEVNULL)
        subprocess.run(['docker', 'rm', name], check=True, stdout=subprocess.DEVNULL)
    for path in [ROOT / 'accounts.json', OLD / 'agent-clone.private.env']:
        if path.exists():
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
            path.unlink()
    assert runtime.closed(18314) and runtime.closed(18092) and runtime.closed(18094)
    report['own_validation_cleanup_passed'] = True

def main():
    assert not (ROOT / 'deployment-state.json').exists() and not runtime.STATE.exists(), '不覆盖既有部署记录'
    source = check_weights()
    prior = json.loads((OLD / 'memory-deployment-state.json').read_text())
    baseline = dict(prior['baseline_sha256'])
    baseline['.env'] = prior['deployed_env_sha256']
    for name, digest in baseline.items():
        assert runtime.digest(LIVE / name) == digest, '正式文件在候选验收后发生变化'
    previous_model = prior['updates']['MODEL_PATH']
    initial = runtime.identity(previous_model, 0.50)
    assert initial == (prior['api_pid'], prior['launcher_pid'])
    assert runtime.health()
    assert runtime.closed(18314) and runtime.closed(18092) and runtime.closed(18094)
    helper_spec = importlib.util.spec_from_file_location('old_runtime', '/tmp/rs-serving-tuning-20261011/deploy.py')
    helper = importlib.util.module_from_spec(helper_spec)
    helper_spec.loader.exec_module(helper)
    helper.wait_external_validation()
    runtime.wait_idle()
    cache_source = ROOT / 'cache/mlp_only'
    cache_target = LIVE / 'quantization-cache/20261011-mlp-int4-bf16-memory40'
    assert cache_source.is_dir() and not cache_target.exists()
    shutil.copytree(cache_source, cache_target)
    backup = LIVE / ('backup-partial-quantization-' + time.strftime('%Y%m%d-%H%M%S'))
    backup.mkdir(mode=0o700)
    original = (LIVE / '.env').read_bytes()
    runtime.atomic(backup / '.env', original)
    updates = {'MODEL_PATH': source['path'], 'VLLM_QUANTIZATION': 'auto', 'VLLM_QUANTIZATION_CONFIG': '',
               'VLLM_TEST_FORCE_FP8_MARLIN': '0', 'VLLM_GPU_MEMORY_UTILIZATION': '0.40',
               'VLLM_MAX_NUM_SEQS': '64', 'VLLM_MAX_MODEL_LEN': '16384',
               'VLLM_CACHE_ROOT': str(cache_target)}
    lines = original.decode().splitlines()
    for key in updates:
        assert sum(line.startswith(key + '=') for line in lines) <= 1
    contents = '\n'.join(line for line in lines if line.split('=', 1)[0] not in updates) + '\n'
    contents += '\n'.join(key + '=' + shlex.quote(value) for key, value in updates.items()) + '\n'
    for local, remote in [('deployment_runtime.py', 'partial_quantization_runtime_20261011.py'),
                          ('restore.py', 'restore_qwen35_4b_partial_memory40.py')]:
        assert not (LIVE / remote).exists()
        runtime.atomic(LIVE / remote, (ROOT / local).read_bytes(), 0o700)
    report = {'authorization': '用户明确要求正式部署 MLP INT4、注意力和 GDN BF16、40% 显存预算',
        'model': 'Qwen3.5-4B', 'precision': 'MLP INT4 / attention and GDN BF16',
        'updates': updates, 'previous_model_path': previous_model, 'previous_api_pid': initial[0],
        'previous_launcher_pid': initial[1], 'baseline_sha256': baseline, 'backup': str(backup),
        'gpu_before': runtime.gpu(), 'promoted': False, 'rollback': False,
        'restore_script': str(LIVE / 'restore_qwen35_4b_partial_memory40.py'),
        'known_limitations': ['隔离固定规划回放 4/16 未完整结束，尚未证明工具可靠性修复',
                              '40% 缓存容量较小，未做持续高并发长上下文负载测试']}
    def save():
        contents = (json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode()
        runtime.atomic(ROOT / 'deployment-state.json', contents)
        runtime.atomic(runtime.STATE, contents)
    save()
    owned, stopped = None, False
    try:
        runtime.wait_idle()
        assert runtime.digest(LIVE / '.env') == baseline['.env']
        print('开始正式切换；已有 INT4 配置已备份', flush=True)
        stopped = True
        runtime.stop_identity(initial, previous_model, 0.50)
        runtime.atomic(LIVE / '.env', contents.encode())
        owned = runtime.start('partial-quantization-memory40-20261011.log')
        report['launcher_pid'] = owned.pid
        save()
        report['probe'] = runtime.wait_ready(owned)
        api, launcher = runtime.identity(source['path'], 0.40, 64)
        assert launcher == owned.pid
        report.update(api_pid=api, deployed_env_sha256=runtime.digest(LIVE / '.env'))
        save()
        runtime.wait_idle()
        subprocess.run([sys.executable, str(OLD / 'model_direct.py'), '--base-url', 'http://127.0.0.1:18082/v1',
                        '--output', str(ROOT / 'production-model.json')], check=True, timeout=360)
        report['model_regression_passed'] = True
        print('正式模型侧回归通过，开始真实工具验收', flush=True)
        accounts = ROOT / 'accounts.json'
        assert not accounts.exists()
        runtime.atomic(accounts, Path('/tmp/rs-agent-e2e-20261010-llm-opt-20261011/accounts.json').read_bytes())
        subprocess.run([sys.executable, str(OLD / 'clone.py'), '--model-port', '18082'], check=True)
        clone = json.loads(subprocess.check_output(['docker', 'inspect', 'rs-quantization-20261011-agent'], text=True))[0]
        report['own_clone_id'] = clone['Id']
        save()
        wait_clone_ready()
        subprocess.run([sys.executable, str(ROOT / 'business_compare.py'), '--label', 'production'], check=True, timeout=480)
        rows = json.loads((ROOT / 'production-business.json').read_text())['business_regression']
        report.update(business_passed=sum(bool(row['passed']) for row in rows), business_total=len(rows))
        assert len(rows) == 8 and all(row['passed'] and row['failed_tools'] == 0 for row in rows), '真实业务或工具验收失败'
        runtime.wait_idle()
        report.update(health=runtime.health(), gpu_after=runtime.gpu())
        assert report['health'] and runtime.identity(source['path'], 0.40, 64) == (api, launcher)
        report['released_gpu_memory_mib'] = report['gpu_before']['used_mib'] - report['gpu_after']['used_mib']
        assert report['released_gpu_memory_mib'] >= 2000, '正式服务未释放预期显存'
        for name, digest in baseline.items():
            if name != '.env':
                assert runtime.digest(LIVE / name) == digest
        report['promoted'] = True
        save()
        subprocess.run([sys.executable, report['restore_script']], check=True)
        print('正式部分量化 / 40% 部署及真实工具验收通过', flush=True)
    except BaseException as error:
        report.update(promoted=False, failure_type=type(error).__name__, failure=str(error))
        if stopped:
            if owned is not None:
                runtime.stop_owned(owned)
            else:
                runtime.wait_closed()
            runtime.atomic(LIVE / '.env', original)
            restored = runtime.start('partial-quantization-memory40-rollback.log')
            runtime.wait_ready(restored)
            restored_api, restored_launcher = runtime.identity(previous_model, 0.50)
            report.update(rollback=True, health=runtime.health(), restored_api_pid=restored_api,
                          restored_launcher_pid=restored_launcher)
            previous_state = json.loads((LIVE / 'quantization-memory50-state.json').read_text())
            previous_state.update(api_pid=restored_api, launcher_pid=restored_launcher,
                                  restored_by_partial_attempt=True)
            runtime.atomic(LIVE / 'quantization-memory50-state.json',
                (json.dumps(previous_state, ensure_ascii=False, indent=2) + '\n').encode())
        raise
    finally:
        try:
            cleanup_clone(report)
        finally:
            save()

if __name__ == '__main__':
    main()
