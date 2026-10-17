"""聚合部署与并发结果；保留依赖干扰和预热失败，不将其掩盖为成功。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    deployment = json.loads((ROOT / 'deployment.json').read_text(encoding='utf-8'))
    smoke = json.loads((ROOT / 'post-switch-smoke.json').read_text(encoding='utf-8'))
    audit = json.loads((ROOT / 'audit-after.json').read_text(encoding='utf-8'))
    assert deployment['deployed'] and not deployment['rolled_back']
    assert smoke['passed'] == 5 and len(smoke['cases']) == 5
    assert all(row['passed'] for row in smoke['cases'])
    assert smoke['cases'][-1]['history_turns'] == 2
    assert audit['model_process_unchanged'] and len(audit['existing_history_checked']) == 8
    assert all(value == 200 for value in audit['health'].values())
    phases = {}
    for name in ('complex-ladder', 'complex-boundary', 'complex-boundary-repeat', 'complex-stable', 'complex-recovery',
                 'complex-confirmed-update'):
        result = json.loads((ROOT / (name + '.json')).read_text(encoding='utf-8'))
        before = [line for line in result['model_before'] if '--port 18082 ' in line]
        assert before == audit['model_after'], '目标模型变化，不允许汇总为同条件评测'
        phases[name] = {'warmup_passed': sum(row['passed'] for row in result.get('warmup', [])),
            'warmup_count': len(result.get('warmup', [])), 'stages': [
                {key: stage[key] for key in ('concurrent_requests', 'passed', 'failed', 'median_ms', 'maximum_ms',
                    'completed_requests_per_second')} for stage in result.get('stages', [])]}
    summary = {'deployed': True, 'agent_sha256': deployment['new_agent_sha256'], 'model_pid': 806733,
        'target_model_unchanged': True, 'post_switch_smoke_passed': 5, 'existing_history_accounts_checked': 8,
        'phases': phases, 'verified_reliable_maximum': None,
        'concurrent_recommend_update_confirmed_by_user': True,
        'current_full_flow_quality_gate_passed': False,
        'limits': ['16 路复杂请求没有全部通过', '12 路复测受到 Recommend 重启干扰',
                   '依赖更新后单请求也出现 BGE 降级，不能发布当前环境可靠最大容量',
                   '完整流程属性不替代语义质量对照'], 'rollback_available': True, 'final_health': audit['health']}
    (ROOT / 'validation.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print('live validation: deployment active; model unchanged; smoke 5/5; old history 8/8; concurrency limits retained')


if __name__ == '__main__':
    main()
