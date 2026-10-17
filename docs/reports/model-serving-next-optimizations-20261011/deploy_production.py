"""仅推广通过对照的预热配置；原模型与调度预算不变，失败受控恢复。"""
import importlib.util
import argparse
import json
from pathlib import Path
import shlex
import stat
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parent
LIVE = Path('/home/luo/RS_agent_java/model_deploy')
STATE = LIVE / 'model-serving-next-state-20261011.json'
PRIOR = LIVE / 'partial-quantization-memory50-state.json'
OLD = Path('/tmp/rs-agent-quantization-retry-20261011')
spec = importlib.util.spec_from_file_location('runtime', LIVE / 'partial_quantization_runtime_20261011.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def load(name):
    return json.loads((ROOT / name).read_text())


def performance(before, after):
    ratios = {}
    for name in ['warm_tool_c1', 'warm_tool_c4', 'warm_tool_c8', 'warm_tool_c16', 'mixed_c4', 'mixed_c8', 'mixed_c16']:
        ratios[name] = after['tests'][name]['summary']['e2e_median_ms'] / before['tests'][name]['summary']['e2e_median_ms']
    ratios['decode128'] = after['tests']['decode128']['e2e_median_ms'] / before['tests']['decode128']['e2e_median_ms']
    # 预热只改善首次请求；正式同卡稳态若明显退化则回滚，不把测量波动称作收益。
    assert max(ratios.values()) <= 1.20, '正式同卡稳态中位数出现超过 20% 的退化，回滚'
    return ratios


def main(startup=False, idle=False, matched=False):
    assert not matched or idle
    retry = startup or idle
    state_path = LIVE / 'model-serving-idle-guard-state-20261011.json' if idle else (LIVE / 'model-serving-warmup16-state-20261011.json' if startup else STATE)
    output = 'production-final-deployment-state.json' if retry else 'production-deployment-state.json'
    label = 'idle_guard' if idle else ('startup16' if startup else 'prefix_refilled')
    after_label = 'production_final_after' if retry else 'production_after'
    before_label = 'production_retry_before' if retry else 'production_before'
    if matched:
        state_path = LIVE / 'model-serving-idle-guard-matched-state-20261011.json'
        output = 'production-matched-deployment-state.json'
        after_label, before_label = 'production_matched_after', 'production_control'
    assert not state_path.exists() and not (ROOT / output).exists()
    selection = load('idle-guard-selection.json' if idle else ('startup16-selection.json' if startup else 'warmup-selection.json'))
    assert selection['accepted'] and selection['candidate'] == label
    candidate = load(label + '-state.json')
    if idle:
        assert candidate['local_guard_tests_passed'] and candidate['engine_baseline_passed']
    else:
        assert candidate['passed'] and candidate['owned_cleanup_passed']
    assert not candidate['mtp']
    assert candidate['expanded_prefixes'] == (not retry) and candidate['prewarm16'] == (not idle)
    assert candidate['final_prefix_refresh'] == (not idle)
    assert candidate['resolved_scheduler']['max_num_batched_tokens'] == 2048
    assert candidate['resolved_scheduler']['max_num_seqs'] == 128
    prior = json.loads(PRIOR.read_text())
    assert prior['promoted'] and not prior['rollback']
    assert prior['updates']['MODEL_PATH'] == candidate['model_path']
    before = load('production-control-before-state.json' if matched else ('production-retry-before-state.json' if retry else 'production-before-state.json'))
    identity = runtime.identity(candidate['model_path'], .50, 128)
    assert identity == (prior['api_pid'], prior['launcher_pid']) == (before['api_pid'], before['launcher_pid'])
    baseline = dict(before['file_sha256'])
    baseline['.env'] = before['env_sha256']
    for name, digest in baseline.items():
        assert runtime.digest(LIVE / name) == digest
    assert all(runtime.closed(port) for port in [18092, 18314]) and runtime.health()
    external_spec = importlib.util.spec_from_file_location('external_guard', '/tmp/rs-serving-tuning-20261011/deploy.py')
    external = importlib.util.module_from_spec(external_spec)
    external_spec.loader.exec_module(external)
    external.wait_external_validation()
    runtime.wait_idle()
    backup = LIVE / ('backup-serving-next-' + time.strftime('%Y%m%d-%H%M%S'))
    backup.mkdir(mode=0o700)
    original_env = (LIVE / '.env').read_bytes()
    original_start = (LIVE / 'start_qwen35_4b_vllm.sh').read_bytes()
    original_warmup = (LIVE / 'vllm_prefix_warmup.py').read_bytes()
    previous_warmup_mode = stat.S_IMODE((LIVE / 'vllm_prefix_warmup.py').stat().st_mode)
    previous_mode = stat.S_IMODE((LIVE / 'start_qwen35_4b_vllm.sh').stat().st_mode)
    runtime.atomic(backup / '.env', original_env)
    runtime.atomic(backup / 'start_qwen35_4b_vllm.sh', original_start, previous_mode)
    runtime.atomic(backup / 'vllm_prefix_warmup.py', original_warmup, previous_warmup_mode)
    runtime.atomic(backup / 'previous-state.json', PRIOR.read_bytes())
    restore = LIVE / ('restore_model_serving_idle_guard_20261011.py' if idle else ('restore_model_serving_warmup16_20261011.py' if startup else 'restore_model_serving_next_20261011.py'))
    if matched:
        restore = LIVE / 'restore_model_serving_idle_guard_matched_20261011.py'
    assert not restore.exists()
    restore_code = (ROOT / 'restore_serving_next.py').read_text()
    if retry:
        assert restore_code.count('model-serving-next-state-20261011.json') == 1
        restore_code = restore_code.replace('model-serving-next-state-20261011.json', state_path.name)
    runtime.atomic(restore, restore_code.encode(), 0o700)
    updates = {} if matched else {'VLLM_EXTRA_WARMUP_CONCURRENCY': '0' if idle else '16'}
    if not retry:
        warmfile = LIVE / 'warmup-prefixes-expanded-20261011.private.json'
        assert not warmfile.exists()
        assert len(json.loads((ROOT / 'expanded-prefixes.private.json').read_text())) == 8
        runtime.atomic(warmfile, (ROOT / 'expanded-prefixes.private.json').read_bytes())
        updates['VLLM_WARMUP_PAYLOAD_FILE'] = str(warmfile)
    lines = original_env.decode().splitlines()
    for key in updates:
        assert sum(line.startswith(key + '=') for line in lines) <= 1
    contents = '\n'.join(line for line in lines if line.split('=', 1)[0] not in updates) + '\n'
    contents += '\n'.join(key + '=' + shlex.quote(value) for key, value in updates.items()) + '\n'
    report = {'authorization': '用户要求实际优化服务且原功能不能退化', 'strategy': label, 'model_path': candidate['model_path'],
        'precision': prior['precision'], 'updates': updates, 'budget': .50, 'max_num_seqs': 128,
        'max_model_len': 16384, 'max_num_batched_tokens': 2048, 'mtp': False,
        'previous_api_pid': identity[0], 'previous_launcher_pid': identity[1], 'previous_start_mode': previous_mode,
        'previous_warmup_mode': previous_warmup_mode,
        'baseline_sha256': baseline, 'backup': str(backup), 'restore_script': str(restore),
        'gpu_before': runtime.gpu(), 'promoted': False, 'rollback': False}
    def save():
        data = (json.dumps(report, ensure_ascii=False, indent=2) + '\n').encode()
        runtime.atomic(ROOT / output, data)
        runtime.atomic(state_path, data)
    save()
    owned, stopped = None, False
    try:
        runtime.wait_idle()
        for name, digest in baseline.items():
            assert runtime.digest(LIVE / name) == digest
        stopped = True
        runtime.stop_identity(identity, report['model_path'], .50, 128)
        if not matched:
            runtime.atomic(LIVE / 'start_qwen35_4b_vllm.sh', (ROOT / 'model/start_optimized.sh').read_bytes(), previous_mode)
        runtime.atomic(LIVE / 'vllm_prefix_warmup.py', (ROOT / 'model/warmup_optimized.py').read_bytes(), previous_warmup_mode)
        if not matched:
            runtime.atomic(LIVE / '.env', contents.encode())
        report['log_file'] = 'model-serving-idle-guard-20261011.log' if idle else ('model-serving-warmup16-20261011.log' if startup else 'model-serving-next-20261011.log')
        if matched:
            report['log_file'] = 'model-serving-idle-guard-matched-20261011.log'
        owned = runtime.start(report['log_file'])
        report['launcher_pid'] = owned.pid
        save()
        report['probe'] = runtime.wait_ready(owned)
        report['extra_warmup_enabled'] = not idle
        if not idle:
            report['extra_probe'] = json.loads(Path(str(runtime.READY) + '.extra-warmup.json').read_text())
            assert report['extra_probe']['status'] == 'PASS' and 'named_tool_concurrency_16' in report['extra_probe']['cases']
        api, launcher = runtime.identity(report['model_path'], .50, 128)
        assert launcher == owned.pid
        report.update(api_pid=api, deployed_env_sha256=runtime.digest(LIVE / '.env'),
            deployed_file_sha256={name: runtime.digest(LIVE / name) for name in baseline if name != '.env'})
        if matched:
            assert report['deployed_env_sha256'] == baseline['.env']
            assert report['deployed_file_sha256']['start_qwen35_4b_vllm.sh'] == baseline['start_qwen35_4b_vllm.sh']
        save()
        runtime.wait_idle()
        subprocess.run([sys.executable, str(ROOT / 'serving_benchmark.py'), '--base-url', 'http://127.0.0.1:18082/v1',
                        '--label', after_label], check=True, timeout=420)
        report['steady_median_ratios'] = performance(load(before_label + '-performance.json'), load(after_label + '-performance.json'))
        subprocess.run([sys.executable, str(OLD / 'model_direct.py'), '--base-url', 'http://127.0.0.1:18082/v1',
                        '--output', str(ROOT / (after_label + '-model.json'))], check=True, timeout=360)
        report['model_regression_passed'] = True
        subprocess.run([sys.executable, str(ROOT / 'functional_probe.py'), '--base-url', 'http://127.0.0.1:18082/v1',
                        '--label', after_label], check=True, timeout=90)
        subprocess.run([sys.executable, str(ROOT / 'business_validation.py'), '--model-port', '18082',
                        '--label', after_label], check=True, timeout=540)
        rows = load(after_label + '-business.json')['business_regression']
        assert len(rows) == 8 and all(row['passed'] and row['failed_tools'] == 0 for row in rows)
        report.update(business_passed=8, business_total=8, vision_passed=True)
        subprocess.run([sys.executable, str(ROOT / 'planning_probe.py'), '--port', '18082',
                        '--label', after_label], check=True, timeout=360)
        report['planning_control'] = 'production_control' if matched else 'baseline'
        planning, planning_before = load(after_label + '-planning.json'), load(report['planning_control'] + '-planning.json')
        for key in ['incomplete_generations', 'schema_errors', 'rag_missing_query']:
            assert planning[key] <= planning_before[key], '正式固定工具规划指标退化：' + key
        report['planning'] = {key: planning[key] for key in ['samples', 'incomplete_generations', 'schema_errors', 'rag_missing_query']}
        runtime.wait_idle()
        report.update(health=runtime.health(), gpu_after=runtime.gpu())
        assert report['health'] and runtime.identity(report['model_path'], .50, 128) == (api, launcher)
        before_other = {item['pid'] for item in report['gpu_before']['processes'] if item['pid'] not in [identity[0]]}
        # 旧模型的 engine PID 会随重启变化；BGE 的既有进程必须仍在。
        assert 3417056 in before_other and 3417056 in {item['pid'] for item in report['gpu_after']['processes']}
        assert report['gpu_after']['free_mib'] >= 8000
        for name, digest in baseline.items():
            if name not in ['.env', 'start_qwen35_4b_vllm.sh', 'vllm_prefix_warmup.py']:
                assert runtime.digest(LIVE / name) == digest
        for name, digest in report['deployed_file_sha256'].items():
            assert runtime.digest(LIVE / name) == digest
        assert all(runtime.closed(port) for port in [18092, 18314])
        assert not (ROOT / 'accounts.json').exists() and not (OLD / 'agent-clone.private.env').exists()
        report['promoted'] = True
        save()
        subprocess.run([sys.executable, str(restore)], check=True)
        print('正式优化 ' + label + ' 的推广、回归及恢复入口核验通过', flush=True)
    except BaseException as error:
        report.update(promoted=False, failure_type=type(error).__name__, failure=str(error))
        if stopped:
            if owned is not None:
                runtime.stop_owned(owned)
            else:
                runtime.wait_closed()
            runtime.atomic(LIVE / 'start_qwen35_4b_vllm.sh', original_start, previous_mode)
            runtime.atomic(LIVE / 'vllm_prefix_warmup.py', original_warmup, previous_warmup_mode)
            runtime.atomic(LIVE / '.env', original_env)
            restored = runtime.start('model-serving-next-rollback50-20261011.log')
            runtime.wait_ready(restored)
            api, launcher = runtime.identity(report['model_path'], .50, 128)
            prior.update(api_pid=api, launcher_pid=launcher, restored_by_next_attempt=True)
            runtime.atomic(PRIOR, (json.dumps(prior, ensure_ascii=False, indent=2) + '\n').encode())
            report.update(rollback=True, restored_api_pid=api, restored_launcher_pid=launcher, health=runtime.health())
        raise
    finally:
        save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--startup16', action='store_true')
    group.add_argument('--idle-guard', action='store_true')
    parser.add_argument('--matched', action='store_true')
    args = parser.parse_args()
    main(args.startup16, args.idle_guard, args.matched)
