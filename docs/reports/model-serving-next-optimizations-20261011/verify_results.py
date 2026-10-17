"""核验候选、失败门槛、回滚及最终原配置证据；不加载模型或读取私有数据。"""
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load(name):
    return json.loads((ROOT / name).read_text(encoding='utf-8'))


for path in ROOT.glob('*.py'):
    ast.parse(path.read_text(encoding='utf-8'))
for path in ROOT.glob('*.json'):
    json.loads(path.read_text(encoding='utf-8'))
assert not list(ROOT.glob('*.private.*')) and not (ROOT / 'accounts.json').exists()
assert load('selection.json')['winner'] is None
assert not load('prefix_optimized-selection.json')['accepted']
assert not load('startup16-selection.json')['accepted']
assert load('warmup-selection.json')['accepted']  # 只通过隔离门槛，正式未推广。
for name in ['production-deployment-state.json', 'production-final-deployment-state.json', 'production-matched-deployment-state.json']:
    state = load(name)
    assert not state['promoted'] and state['rollback'] and state['health']
    assert state['failure_type'] in ['AssertionError', 'CalledProcessError']
baseline = load('baseline-planning.json')
identity = [(row['case'], row['repeat'], row['input_sha256'], row['sampling_seed'], row['temperature']) for row in baseline['results']]
for label in ['mtp1', 'prefix_optimized', 'prefix_refilled', 'startup16', 'production_final_after', 'production_control', 'production_matched_after']:
    report = load(label + '-planning.json')
    assert len(report['results']) == 16
    assert [(row['case'], row['repeat'], row['input_sha256'], row['sampling_seed'], row['temperature']) for row in report['results']] == identity
assert baseline['incomplete_generations'] == load('production_control-planning.json')['incomplete_generations'] == 2
assert load('production_final_after-planning.json')['incomplete_generations'] == 3
assert load('production_matched_after-planning.json')['incomplete_generations'] == 3
for label in ['default_before', 'batch4096', 'batch8192', 'default_after', 'prefix_baseline2', 'mtp1', 'prefix_optimized', 'prefix_refilled', 'startup16']:
    state = load(label + '-state.json')
    assert state['passed'] and state['owned_cleanup_passed'] and state['probe']['status'] == 'PASS'
    model = load(label + '-model.json')
    assert len(model['fixed_quality']) == 6 and all(row['passed'] for row in model['fixed_quality'])
    assert len(model['real_request_replay']) == 6
for label in ['production_final_after', 'production_control', 'production_matched_after']:
    model = load(label + '-model.json')
    assert len(model['fixed_quality']) == 6 and all(row['passed'] for row in model['fixed_quality'])
    assert len(model['real_request_replay']) == 6
assert not load('prefix_baseline-state.json')['passed'] and load('prefix_baseline-state.json')['owned_cleanup_passed']
for label in ['baseline', 'mtp1', 'prefix_optimized', 'prefix_refilled', 'startup16', 'production_final_after', 'production_control', 'production_matched_after']:
    rows = load(label + '-business.json')['business_regression']
    assert len(rows) == 8 and all(row['passed'] and row['failed_tools'] == 0 for row in rows)
    assert all(load(label + '-business-cleanup.json').values())
    assert load(label + '-functional.json')['vision_passed']
control = load('production-control-before-state.json')
matched = load('production-matched-deployment-state.json')
assert matched['deployed_env_sha256'] == control['env_sha256']
assert matched['deployed_file_sha256']['start_qwen35_4b_vllm.sh'] == control['file_sha256']['start_qwen35_4b_vllm.sh']
live = load('production-original-live-state.json')
assert live['original_configuration_restored'] and not live['optimization_changes_promoted'] and not live['promoted']
assert live['health'] == 200 and live['bge_pid_unchanged'] == 3417056
assert live['own_validation_cleaned'] and live['shared_agent_running'] and live['unused_failed_private_payload_removed']
assert live['kv_cache_tokens'] == 106496 and live['kv_cache_gib'] >= 3.8 and live['model_loading_gib'] < 5.6
assert live['warmup_records'] == 2 and live['warmup_private_mode'] == '0600'
assert live['runtime_env_sha256'] == load('production-before-state.json')['env_sha256']
assert live['source_sha256'] == {name: digest for name, digest in load('production-before-state.json')['file_sha256'].items() if name != '.env'}
assert live['api_pid'] == matched['restored_api_pid'] and live['launcher_pid'] == matched['restored_launcher_pid']
assert live['settings']['VLLM_MAX_MODEL_LEN'] == '16384'
assert live['settings']['VLLM_MAX_NUM_SEQS'] == '128'
assert live['settings']['VLLM_GPU_MEMORY_UTILIZATION'] == '0.50'
assert not live['settings']['VLLM_SPECULATIVE_CONFIG'] and live['settings']['VLLM_SERVER_DEV_MODE'] != '1'
assert live['gpu']['free_mib'] >= 8000
print('Candidate evidence, paired inputs, all rollback gates, restored configuration and cleanup verified')
