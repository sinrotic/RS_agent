"""验证报告间的输入与结果关联；不加载模型、不读取私有请求。"""
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
for path in ROOT.glob('*.py'):
    ast.parse(path.read_text(encoding='utf-8'))
for path in ROOT.glob('*.json'):
    json.loads(path.read_text(encoding='utf-8'))
control = json.loads((ROOT / 'control-planning.json').read_text(encoding='utf-8'))
identity = [(row['case'], row['repeat'], row['input_sha256'], row['sampling_seed'], row['temperature'])
            for row in control['results']]
assert len(identity) == 16
for label in ['mlp_only', 'gdn_bf16', 'winner_low_memory']:
    planning = json.loads((ROOT / (label + '-planning.json')).read_text(encoding='utf-8'))
    assert [(row['case'], row['repeat'], row['input_sha256'], row['sampling_seed'], row['temperature'])
            for row in planning['results']] == identity
    business = json.loads((ROOT / (label + '-business.json')).read_text(encoding='utf-8'))['business_regression']
    assert len(business) == 8
    assert not any(row.get('failed_tools', 0) < 0 for row in business)
    state = json.loads((ROOT / (label + '-state.json')).read_text(encoding='utf-8'))
    assert state['model_passed'] and state['business_completed'] and state['probe']['status'] == 'PASS'
for label in ['mlp_only', 'gdn_bf16']:
    source = json.loads((ROOT / (label + '-source.json')).read_text(encoding='utf-8'))
    assert source['payload_roundtrip_verified']
assert json.loads((ROOT / 'resolved-config-check.json').read_text(encoding='utf-8'))['matched']
assert json.loads((ROOT / 'cleanup-state.json').read_text(encoding='utf-8'))['production_unchanged']
assert not list(ROOT.glob('*.private.*'))
if (ROOT / 'deployment-state.json').exists():
    deployment = json.loads((ROOT / 'deployment-state.json').read_text(encoding='utf-8'))
    live = json.loads((ROOT / 'deployment-live-state.json').read_text(encoding='utf-8'))
    candidate = json.loads((ROOT / 'candidate-config.json').read_text(encoding='utf-8'))
    assert deployment['promoted'] and not deployment['rollback']
    assert deployment['model_regression_passed'] and deployment['own_validation_cleanup_passed']
    assert deployment['deployed_env_sha256'] == live['runtime_env_sha256']
    assert live['model_root'] == deployment['updates']['MODEL_PATH']
    assert live['gpu_memory_utilization'] == 0.40 and live['max_num_seqs'] == 64
    assert live['max_model_len'] == 16384 and live['health'] == 200
    assert live['own_validation_cleaned'] and live['startup_scripts_unchanged']
    assert live['bge_pid_unchanged'] == 3417056
    assert deployment['released_gpu_memory_mib'] >= 2000
    business = json.loads((ROOT / 'production-business.json').read_text(encoding='utf-8'))['business_regression']
    assert len(business) == 8 and all(row['passed'] and row['failed_tools'] == 0 for row in business)
    model = json.loads((ROOT / 'production-model.json').read_text(encoding='utf-8'))
    assert len(model['fixed_quality']) == 6 and all(row['passed'] for row in model['fixed_quality'])
    assert len(model['real_request_replay']) == 6
    if not (ROOT / 'cache50-deployment-state.json').exists():
        for key, value in deployment['updates'].items():
            if key in candidate['settings']:
                assert candidate['settings'][key] == value
    assert '已正式部署' in candidate['status']
    print('正式部署配置、验收、持久摘要、BGE 身份及清理证据关联验证通过')
if (ROOT / 'cache50-deployment-state.json').exists():
    deployment = json.loads((ROOT / 'cache50-deployment-state.json').read_text(encoding='utf-8'))
    live = json.loads((ROOT / 'cache50-live-state.json').read_text(encoding='utf-8'))
    candidate = json.loads((ROOT / 'candidate-config.json').read_text(encoding='utf-8'))
    assert deployment['promoted'] and not deployment['rollback']
    assert deployment['model_regression_passed'] and deployment['concurrency_probe_passed']
    assert deployment['own_validation_cleanup_passed'] and live['own_validation_cleaned']
    assert deployment['deployed_env_sha256'] == live['runtime_env_sha256']
    assert live['model_root'] == deployment['updates']['MODEL_PATH']
    assert live['gpu_memory_utilization'] == 0.50 and live['max_num_seqs'] == 128
    assert live['max_model_len'] == 16384 and live['health'] == 200
    assert live['kv_cache_gib'] >= 3.8 and live['kv_cache_tokens'] >= 100000
    assert live['estimated_full_context_concurrency'] > 6
    assert live['startup_scripts_unchanged'] and live['bge_pid_unchanged'] == 3417056
    assert live['prefix_caching_enabled'] and live['prefix_keepalive_enabled']
    assert live['warmup_only_when_idle'] and live['shared_agent_running']
    for key, value in deployment['updates'].items():
        assert candidate['settings'][key] == value
    assert candidate['deployment_report'] == 'cache-expansion.md'
    for label in ['cache40_before', 'cache50_after']:
        probe = json.loads((ROOT / (label + '-concurrency.json')).read_text(encoding='utf-8'))
        assert probe['workers'] == 16 and probe['peak_client_inflight'] == 16
        assert probe['samples'] == 32 and probe['passed'] == 32
    business = json.loads((ROOT / 'production_cache50-business.json').read_text(encoding='utf-8'))['business_regression']
    assert len(business) == 8 and all(row['passed'] and row['failed_tools'] == 0 for row in business)
    model = json.loads((ROOT / 'cache50-production-model.json').read_text(encoding='utf-8'))
    assert len(model['fixed_quality']) == 6 and all(row['passed'] for row in model['fixed_quality'])
    assert len(model['real_request_replay']) == 6
    print('50% 扩容配置、容量、扩容前后并发探针及正式业务证据关联验证通过')
print('公开 JSON、Python AST、三轮配对输入、验收状态、来源及清理记录关联验证通过')
