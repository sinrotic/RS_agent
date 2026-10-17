"""用已捕获的真实模型计时建立慢 prefill 判据，不删异常样本。"""
import json
import statistics
from pathlib import Path

ROOT = Path(__file__).resolve().parent
data = json.loads((ROOT.parent / 'agent-resume-benchmark-20261011' / 'after-quant-capacity.json').read_text(encoding='utf-8'))
stages = [stage for stage in data['stages'] if stage['concurrency'] == 1]
rows = []
for stage in stages:
    delta = stage['model_metrics']['delta']
    assert delta['vllm:time_to_first_token_seconds_count'] == delta['vllm:request_prefill_time_seconds_count'] == 1
    rows.append({'index': stage['repeat'], 'prefill_ms': 1000 * delta['vllm:request_prefill_time_seconds_sum'],
                 'ttft_ms': 1000 * delta['vllm:time_to_first_token_seconds_sum'],
                 'queue_ms': 1000 * delta['vllm:request_queue_time_seconds_sum']})
baseline = statistics.median(row['prefill_ms'] for row in rows[1:])
spikes = [row for row in rows if row['prefill_ms'] > max(300, 2 * baseline) and row['queue_ms'] < 10]
report = {'hot_prefill_median_ms': round(baseline, 3), 'spikes': spikes,
          'scope': '历史窗口每条新增一个模型调用，判据为 prefill 超过热态两倍且超过300ms、排队小于10ms'}
(ROOT / 'historical-signal.json').write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
print(json.dumps(report, ensure_ascii=False))
assert not spikes, '复现：prefill 出现非排队造成的延迟尖峰'
