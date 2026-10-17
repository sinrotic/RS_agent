"""从既有验收数据生成可复核对比，不跨模型或负载拼接加速比例。"""
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent
REPORTS = ROOT.parent


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    llm_root = REPORTS / 'agent-llm-optimization-20261011'
    before = read(llm_root / 'baseline-summary.json')
    after = read(llm_root / 'optimized-final-summary.json')
    old = {row['label']: row for row in before['requests']}
    pairs = []
    for row in after['requests']:
        previous = old[row['label']]
        assert previous['query'] == row['query']
        old_ms, new_ms = previous['complete_ms'], row['complete_ms']
        pairs.append({'label': row['label'], 'query': row['query'],
            'before_failed': previous['failed'], 'after_failed': row['failed'],
            'before_complete_ms': old_ms, 'after_complete_ms': new_ms,
            'duration_change_percent': round((new_ms / old_ms - 1) * 100, 2) if old_ms and new_ms else None,
            'before_llm_calls': previous['llm_calls'], 'after_llm_calls': row['llm_calls'],
            'before_model_first_delta_ms': previous['first_delta_ms'][0] if previous['first_delta_ms'] else None,
            'after_model_first_delta_ms': row['first_delta_ms'][0] if row['first_delta_ms'] else None})
    concurrency_root = REPORTS / 'agent-concurrency-optimization-20261011'
    baseline = read(concurrency_root / 'baseline.json')
    final = read(concurrency_root / 'guarded4.json')
    old_16 = next(row for row in baseline['stages'] if row['concurrent_requests'] == 16)
    new_16 = next(row for row in final['stages'] if row['concurrent_requests'] == 16)
    assert baseline['model_before'] == final['model_before'], '并发对照模型条件不一致'
    keys = ('concurrent_requests', 'passed', 'failed', 'median_ms', 'maximum_ms', 'completed_requests_per_second')
    result = {'historical_full_pipeline_scope': 'BF16 原模型历史小样本；热状态、随机输出和恢复后的真实 RAG 工作量可能不同，非稳定 SLA',
        'historical_full_pipeline_pairs': pairs,
        'historical_success_count': {'before': len(before['requests']) - before['failed'],
                                     'after': len(after['requests']) - after['failed'], 'total': len(pairs)},
        'model_delta_definition': '从单次模型 HTTP 调用开始到首次 content/tool_calls/reasoning_content 非空；不是网关请求到首字',
        'last_concurrency_optimization_scope': 'INT4 同模型、同普通推荐输入、16 路独立 Session；中位耗时只统计成功请求',
        'last_concurrency_optimization': {'before': {key: old_16[key] for key in keys},
            'after': {key: new_16[key] for key in keys},
            'completion_throughput_change_percent': round((new_16['completed_requests_per_second'] /
                old_16['completed_requests_per_second'] - 1) * 100, 2),
            'successful_duration_change_percent': round((new_16['median_ms'] / old_16['median_ms'] - 1) * 100, 2)},
        'frontend_streaming_behavior': '当前 agentClient.ts 只在 answer_block 调用展示回调，不逐 token 显示正文',
        'current_first_public_token_ms': None, 'current_first_visible_block_ms': None,
        'current_measurement_status': '首次采集器平台鉴权/计时字段问题已修正；修正后模型健康端口不可连接，未得有效当前样本',
        'complex_concurrency_before_after_available': False,
        'limitations': ['模型首次非空增量可能是工具参数或推理内容，不能当作用户可见正文',
            '并发优化改善完整完成率与吞吐，没有证明单请求或首字更快',
            '复杂并发没有同条件旧新版对照，不能宣称其加速幅度',
            '失败耗时不与成功耗时计算降幅；不混合 BF16/INT4/快速推荐的指标']}
    current_path = ROOT / 'first-visible-current.json'
    if current_path.exists():
        current = read(current_path)
        ordinary = [row for row in current['cases'] if row.get('passed') and row['query'] == '推荐鼠标'
                    and row.get('first_text_block_ms') is not None]
        if ordinary and current.get('model_process_unchanged') and current.get('dependencies_stable'):
            result['current_first_visible_block_ms'] = statistics.mean(row['first_text_block_ms'] for row in ordinary)
            result['current_first_visible_scope'] = '普通鼠标单轮，服务器本机调用真实网关；不含用户公网链路和浏览器渲染'
            result['current_ordinary_samples'] = len(ordinary)
            result['current_ordinary_complete_mean_ms'] = statistics.mean(row['complete_ms'] for row in ordinary)
            result['current_measurement_status'] = '当前采集器核验通过；两条普通与一条办公静音完整通过，键盘 BGE 降级不计合格样本'
            result['current_measurement_checked_at_utc'] = current['checked_at_utc']
            result['current_public_token_event_count'] = sum(row.get('sse_event_counts', {}).get('token', 0)
                for row in current['cases'])
    generated_path = ROOT / 'first-generated-ttft-current.json'
    if generated_path.exists():
        generated = read(generated_path)
        cases = generated.get('cases', [])
        if (cases and all(row.get('passed') and row.get('model_ttft_observed_count') == 1
                         and row.get('model_ttft_observed_ms') is not None for row in cases)
                and generated.get('model_process_unchanged') and generated.get('dependencies_stable')):
            result['current_model_ttft_mean_ms'] = statistics.mean(row['model_ttft_observed_ms'] for row in cases)
            result['current_model_ttft_samples_ms'] = [row['model_ttft_observed_ms'] for row in cases]
            result['current_model_ttft_scope'] = '真实普通单轮推荐；每个共享指标窗口仅新增一条模型 TTFT，未按 request_id 关联；非高并发 SLA'
            result['current_model_ttft_checked_at_utc'] = generated['checked_at_utc']
    (ROOT / 'latency-comparison.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print('对比汇总完成：历史 7 对样本、同模型 16 路并发；模型 TTFT、首正文和多轮变慢分别记录')
    for pair in pairs:
        print(pair['label'], pair['before_complete_ms'], '->', pair['after_complete_ms'],
              '耗时变化%', pair['duration_change_percent'])
    print('16 路吞吐变化%', result['last_concurrency_optimization']['completion_throughput_change_percent'])


if __name__ == '__main__':
    main()
