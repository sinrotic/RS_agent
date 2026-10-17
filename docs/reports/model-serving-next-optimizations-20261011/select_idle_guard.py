"""保温让路由行为测试验证；模型运行参数沿用已验收基线，仍需正式回归。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def load(name):
    return json.loads((ROOT / name).read_text())


baseline = load('prefix_baseline2-state.json')
failed = load('production-deployment-state.json')
assert baseline['passed'] and baseline['owned_cleanup_passed']
assert failed['rollback'] and failed['health'] and not failed['promoted']
assert not load('startup16-selection.json')['accepted'] and load('selection.json')['winner'] is None
candidate = {'label': 'idle_guard', 'model_path': baseline['model_path'],
    'mtp': False, 'prewarm16': False, 'expanded_prefixes': False, 'final_prefix_refresh': False,
    'resolved_scheduler': baseline['resolved_scheduler'], 'engine_baseline_passed': True,
    'local_guard_tests_passed': True,
    'validation_scope': '本地37项测试已通过，保温遇业务停止剩余请求有行为测试；推理参数沿用已验收基线，当前正式验收待完成'}
selection = {'candidate': 'idle_guard', 'accepted': True,
    'reason': '只优化后台预热与业务到达的竞争，关闭额外16路及扩展前缀；完整正式性能与功能验收是推广前置条件',
    'single_call_speedup_verified': False, 'steady_throughput_speedup_verified': False,
    'local_test_command': 'python -m pytest tests/test_vllm_constrained_startup.py tests/test_vllm_structured_output_probe.py tests/test_vllm_prefix_warmup.py -q',
    'local_tests_passed': 37,
    'business_arrival_behavior_test': 'test_keepalive_stops_remaining_prefixes_when_business_arrives',
    'remaining_race': '已发出预热与新到达业务之间仍有竞态，不能保证零竞争'}
for name, data in [('idle_guard-state.json', candidate), ('idle-guard-selection.json', selection)]:
    with (ROOT / name).open('x') as handle:
        handle.write(json.dumps(data, ensure_ascii=False, indent=2) + '\n')
print('只推广经行为测试的保温让路，推理参数不变，正式回归仍为必需', flush=True)
