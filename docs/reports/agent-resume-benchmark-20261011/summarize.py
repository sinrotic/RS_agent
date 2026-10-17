"""逐档汇总并保留失败分母；匹配同档同批同位置，拒绝筛选快样本。"""
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def mean(rows, field='complete_ms'):
    values = [row[field] for row in rows if field in row]
    return round(statistics.mean(values), 3) if values else None


def flatten(report, count):
    return [row for stage in report['stages'] if stage['concurrency'] == count for row in stage['cases']]


def aggregate(report, count):
    stages = [stage for stage in report['stages'] if stage['concurrency'] == count]
    rows = flatten(report, count)
    passed = [row for row in rows if row['passed']]
    durations = sorted(row['complete_ms'] for row in passed)
    return {'total': len(rows), 'passed': len(passed), 'failed': len(rows) - len(passed),
            'success_mean_ms': mean(passed),
            'median_ms': statistics.median(durations) if durations else None,
            'successful_throughput': round(len(passed) * 1000 / sum(stage['batch_wall_ms'] for stage in stages), 4),
            'mean_answer_chars': mean(passed, 'answer_chars'),
            'failed_tool_total': sum(row.get('failed_tools', 0) for row in rows),
            'observed_model_calls': sum(stage['model_metrics']['observed_model_calls'] for stage in stages),
            'degraded_requests': sum(row.get('checks', {}).get('no_degradation') is False for row in rows),
            'error_codes': [row.get('error_code') or row.get('error_type') for row in rows if not row['passed']],
            'batches': [{key: stage[key] for key in ('repeat', 'total', 'passed', 'successful_mean_ms', 'throughput')} for stage in stages]}


def main():
    before = json.loads((ROOT / 'before-bf16-capacity.json').read_text(encoding='utf-8'))
    after = json.loads((ROOT / 'after-quant-capacity.json').read_text(encoding='utf-8'))
    assert before['completed'] and after['completed']
    summary = {'scope': '8a8385 Agent + BF16 对照 4bc94fc Agent + MLP INT4；相同 GPU2、vLLM 参数、真实共享下游、预热、普通推荐；非最初版本整栈还原',
               'comparisons': [], 'strongest_all_success_latency': None}
    for count in (1, 4, 8, 16):
        left = aggregate(before, count); right = aggregate(after, count)
        left_rows = {row['pair_id']: row for row in flatten(before, count)}
        right_rows = {row['pair_id']: row for row in flatten(after, count)}
        assert left_rows.keys() == right_rows.keys()
        keys = [key for key in left_rows if left_rows[key]['passed'] and right_rows[key]['passed']]
        paired_before = mean([left_rows[key] for key in keys])
        paired_after = mean([right_rows[key] for key in keys])
        both_all = left['failed'] == right['failed'] == 0
        result = {'concurrency': count, 'before': left, 'after': right,
                  'pair_scope': '同档同批同位置、同测试账号，独立 Session，非相同输出',
                  'paired_success_count': len(keys), 'paired_before_mean_ms': paired_before,
                  'paired_after_mean_ms': paired_after, 'both_all_success': both_all,
                  'conditional_paired_latency_reduction_percent': round(100 * (1 - paired_after / paired_before), 2) if keys else None,
                  'all_success_latency_reduction_percent': round(100 * (1 - right['success_mean_ms'] / left['success_mean_ms']), 2) if both_all else None,
                  'throughput_improvement_percent': round(100 * (right['successful_throughput'] / left['successful_throughput'] - 1), 2)}
        summary['comparisons'].append(result)
    eligible = [row for row in summary['comparisons'] if row['both_all_success']]
    if eligible:
        summary['strongest_all_success_latency'] = max(eligible, key=lambda row: row['all_success_latency_reduction_percent'])
    screen_path = ROOT / 'original-bf16-screen.json'
    if screen_path.exists():
        original = json.loads(screen_path.read_text(encoding='utf-8'))
        screen_rows = [row for stage in original['stages'] for row in stage['cases']]
        summary['original_screen'] = {'total': len(screen_rows), 'passed': sum(row['passed'] for row in screen_rows),
                                      'queries': [{'query': row['query'], 'passed': row['passed'],
                                                  'failed_tools': row.get('failed_tools'), 'complete_ms': row.get('complete_ms')} for row in screen_rows]}
    (ROOT / 'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
