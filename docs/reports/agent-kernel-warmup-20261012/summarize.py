"""汇总全部正式样本，不剔除慢请求；合成冷启动和真实推荐分开计量。"""
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent


def main():
    before, after = [json.loads((ROOT / f'live-{phase}.json').read_text(encoding='utf-8')) for phase in ('before', 'after')]
    cold = json.loads((ROOT / 'cold-validation.json').read_text(encoding='utf-8'))
    prior = json.loads((ROOT.parent / 'agent-prefill-diagnosis-20261012/reproduction.json').read_text(encoding='utf-8'))
    old_partial = next(row for row in prior['cases'] if row['cycle'] == 0 and row['label'] == 'first-prefix-hit')
    result = {'serial': {}, 'bursts': [], 'cold_partial': {
        'input_tokens': 6610, 'cached_tokens': 4752,
        'previous_unwarmed_ttft_ms': old_partial['ttft_ms'],
        'warmed_first_ttft_ms': cold['first_partial_ttft_ms'],
        'formal_jit_events': cold['formal_jit_events'],
        'scope': '同 GPU、权重、缓存数量和请求预算，两个隔离进程；旧单次冷请求对新单次已预热请求，不是业务平均增益'}}
    for phase, data in (('before', before), ('after', after)):
        rows = data['serial']
        result['serial'][phase] = data['serial_summary'] | {
            'mean_first_text_block_ms': statistics.mean(row['first_text_block_ms'] for row in rows),
            'mean_prefill_ms': statistics.mean(row['model_prefill_observed_ms'] for row in rows),
            'mean_queue_ms': statistics.mean(row['model_queue_observed_ms'] for row in rows),
            'cached_tokens_each': [row['model_cached_tokens'] for row in rows],
            'model_unchanged': data['model_unchanged'], 'dependencies_unchanged': data['dependencies_unchanged']}
    for size in (4, 8):
        row = {'concurrency': size}
        for phase, data in (('before', before), ('after', after)):
            batches = [item for item in data['bursts'] if item['concurrency'] == size]
            assert all(item['timing_count_valid'] for item in batches)
            rows = [sample for item in batches for sample in item['rows']]
            row[phase] = {'total': len(rows), 'passed': sum(sample['passed'] for sample in rows),
                'mean_model_ttft_ms': statistics.mean(item['mean_model_ttft_ms'] for item in batches),
                'mean_complete_ms': statistics.mean(sample['complete_ms'] for sample in rows)}
        result['bursts'].append(row)
    result['serial_mean_ttft_reduction_percent'] = 100 * (1 - result['serial']['after']['mean_model_ttft_ms'] / result['serial']['before']['mean_model_ttft_ms'])
    (ROOT / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
