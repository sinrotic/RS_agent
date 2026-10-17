"""切换前在正式 GPU 1 上补测同长度延迟，避免仅以另一张卡作为对照。"""
import importlib.util
import json
from pathlib import Path
import statistics
from benchmark_core import get_json, measure, metrics, payload

root = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('runtime', '/tmp/rs-serving-tuning-20261011/deploy.py')
runtime = importlib.util.module_from_spec(spec); spec.loader.exec_module(runtime)
runtime.canonical_process()
runtime.wait_idle()
base = 'http://127.0.0.1:18082/v1'
model = get_json(base + '/models')['data'][0]['id']
records = []
for name, options, count in [('short_json', {}, 6), ('named_tool', {'tool': True}, 6),
                             ('decode_128', {'decode': True}, 4)]:
    request = payload(model, **options)
    runtime.wait_idle()
    measure(base, request, name + '_warmup', fixed_decode=bool(options.get('decode')))
    records += [measure(base, request, name, fixed_decode=bool(options.get('decode'))) for _ in range(count)]
summaries = {name: {'samples': sum(r['scenario'] == name for r in records),
    'e2e_median_ms': round(statistics.median(r['e2e_seconds'] * 1000 for r in records if r['scenario'] == name), 2),
    'completion_tokens_median': statistics.median(r['usage']['completion_tokens'] for r in records if r['scenario'] == name)}
    for name in sorted({r['scenario'] for r in records})}
result = {'model_base': base, 'gpu': 1, 'model_info': get_json(base + '/models'),
          'summaries': summaries, 'records': records, 'final_metrics': metrics(base)}
(root / 'bf16-production-latency.json').write_text(json.dumps(result, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(summaries, ensure_ascii=False, indent=2))
