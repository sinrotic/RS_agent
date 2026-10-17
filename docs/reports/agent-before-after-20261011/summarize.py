"""汇总真实对照；质量不合格的交付耗时不当作成功推荐加速。"""
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def read(name):
    path = ROOT / (name + '.json')
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else None


def summarize_rows(rows):
    delivered = [row for row in rows if row.get('complete_ms') is not None]
    passed = [row for row in rows if row['passed']]
    first_model = [row['first_model_call_ttft_ms'] for row in rows if row.get('first_model_call_ttft_ms') is not None]
    return {'samples': len(rows), 'delivered': len(delivered), 'quality_passed': len(passed),
        'delivered_mean_ms': round(statistics.mean(row['complete_ms'] for row in delivered), 2) if delivered else None,
        'quality_passed_mean_ms': round(statistics.mean(row['complete_ms'] for row in passed), 2) if passed else None,
        'delivered_first_text_mean_ms': round(statistics.mean(row['first_text_block_ms'] for row in delivered
            if row.get('first_text_block_ms') is not None), 2) if any(row.get('first_text_block_ms') is not None for row in delivered) else None,
        'first_model_call_ttft_mean_ms': round(statistics.mean(first_model), 3) if first_model else None,
        'model_calls_per_turn': [row.get('model_metrics', {}).get('observed_model_calls') for row in rows],
        'mean_answer_chars': round(statistics.mean(row['answer_chars'] for row in delivered if row.get('answer_chars') is not None), 2)
            if any(row.get('answer_chars') is not None for row in delivered) else None,
        'failed_tool_counts': [row.get('failed_tools') for row in rows]}


def latency_comparison(before_name, after_name):
    before, after = read(before_name), read(after_name)
    if not before or not after:
        return None
    assert before['completed'] and after['completed']
    for data in (before, after):
        assert data['model_process_unchanged'] and data['dependencies_stable'] and data['clone_cleaned']
        assert data.get('target_model_process_unchanged', True)
    result = {'before_report': before_name, 'after_report': after_name, 'groups': {}}
    for group in ('ordinary', 'complex-office', 'complex-keyboard', 'multi'):
        left = [row for row in before['cases'] if row['label'].startswith(group)]
        right = [row for row in after['cases'] if row['label'].startswith(group)]
        if not left and not right:
            continue
        both_passed = [(a, b) for a in left for b in right if a['label'] == b['label'] and a['passed'] and b['passed']]
        pair = {'before': summarize_rows(left), 'after': summarize_rows(right),
            'quality_passed_pairs': len(both_passed), 'quality_passed_mean_reduction_percent': None}
        if both_passed:
            a = statistics.mean(first['complete_ms'] for first, second in both_passed)
            b = statistics.mean(second['complete_ms'] for first, second in both_passed)
            pair['quality_passed_mean_reduction_percent'] = round(100 * (a - b) / a, 2)
        result['groups'][group] = pair
    return result


def capacity_comparison():
    before, after = read('pre-concurrency-capacity'), read('current-capacity')
    if not before or not after:
        return None
    result = {'before_report': 'pre-concurrency-capacity', 'after_report': 'current-capacity', 'levels': []}
    assert before['completed'] and after['completed']
    for data in (before, after):
        assert data['model_process_unchanged'] and data['target_model_process_unchanged'] and data['dependencies_stable'] and data['clone_cleaned']
    assert before['target_model_before'] == after['target_model_before']
    for count in sorted({stage['concurrent_requests'] for stage in before['stages']}):
        pair = {'concurrent_requests': count}
        for name, data in (('before', before), ('after', after)):
            stages = [stage for stage in data['stages'] if stage['concurrent_requests'] == count]
            rows = [row for stage in stages for row in stage['cases']]
            elapsed = sum(stage['batch_wall_ms'] for stage in stages) / 1000
            timing_windows = []
            for stage in stages:
                delta = stage['model_metrics']['delta']
                calls = delta.get('vllm:time_to_first_token_seconds_count', 0)
                delivered_count = sum(row.get('complete_ms') is not None for row in stage['cases'])
                valid = calls > 0 and calls == delivered_count and all(delta.get(metric + '_count') == calls
                    for metric in ('vllm:request_prompt_tokens', 'vllm:request_queue_time_seconds', 'vllm:request_prefill_time_seconds'))
                valid &= all(delta.get(metric + '_sum', -1) >= 0 for metric in
                    ('vllm:time_to_first_token_seconds', 'vllm:request_queue_time_seconds', 'vllm:request_prefill_time_seconds'))
                timing_windows.append({'valid': valid, 'model_calls': calls,
                    'ttft_sum_seconds': delta.get('vllm:time_to_first_token_seconds_sum'),
                    'ttft_mean_ms': round(1000 * delta['vllm:time_to_first_token_seconds_sum'] / calls, 3) if valid else None})
            summary = summarize_rows(rows)
            summary.update(repeats=len(stages), completed_requests_per_second=round(summary['quality_passed'] / elapsed, 4),
                batch_median_ms=[stage['successful_median_ms'] for stage in stages],
                error_codes={code: sum(row.get('error_code') == code for row in rows)
                             for code in {row.get('error_code') for row in rows} if code is not None},
                successful_first_text_mean_ms=round(statistics.mean(row['first_text_block_ms'] for row in rows
                    if row['passed'] and row.get('first_text_block_ms') is not None), 2)
                    if any(row['passed'] and row.get('first_text_block_ms') is not None for row in rows) else None,
                model_timing_windows=timing_windows,
                model_window_mean_ttft_ms=[window['ttft_mean_ms'] for window in timing_windows],
                model_window_weighted_mean_ttft_ms=round(1000 * sum(window['ttft_sum_seconds'] for window in timing_windows)
                    / sum(window['model_calls'] for window in timing_windows), 3) if all(window['valid'] for window in timing_windows) else None)
            pair[name] = summary
        pair['completion_throughput_change_percent'] = round(100 * (
            pair['after']['completed_requests_per_second'] / pair['before']['completed_requests_per_second'] - 1), 2) if pair['before']['completed_requests_per_second'] else None
        result['levels'].append(pair)
    return result


def main():
    result = {'same_quant_model_agent_comparison': latency_comparison('original-latency-r1', 'current-latency-r1'),
        'overall_same_gpu2_comparison': latency_comparison('original-bf16-gpu2', 'current-quant-gpu2'),
        'same_gpu2_current_agent_model_service_comparison': latency_comparison('current-bf16-gpu2', 'current-quant-gpu2'),
        'capacity': capacity_comparison(),
        'limitations': ['两次全流程采用相同当前推荐资产，不复原历史数据与依赖版本',
            'BF16与量化服务的预算、并发上限和紧凑结构化输出也不同，不能将业务收益全归因于量化',
            '旧版含失败工具的交付不计合格完成，不能据此声称等质量加速',
            '模型指标是窗口累计值；首模型调用TTFT未按request_id关联；包含共享服务干扰的可能性',
            '并发为独立Session突发，16请求使用8账号，不代表16不同用户或持续最大容量',
            '小样本不代表生产SLA，也不替代解释语义回归']}
    before, after = read('bf16-length-probe'), read('quant-length-probe')
    if before and after:
        assert before['samples'] == after['samples'] == 10
        result['same_gpu2_fixed_128_tokens'] = {name: {key: data[key] for key in
            ('samples', 'mean_ms', 'median_ms', 'mean_model_ttft_ms', 'model', 'gpu')} for name, data in (('before', before), ('after', after))}
        result['same_gpu2_fixed_128_tokens']['mean_duration_reduction_percent'] = round(100 * (before['mean_ms'] - after['mean_ms']) / before['mean_ms'], 2)
    (ROOT / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
