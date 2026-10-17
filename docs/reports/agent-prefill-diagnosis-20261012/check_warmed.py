"""验证补充缓存命中路径后，同工作量没有再出现历史类型的尖峰。"""
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
data = json.loads((ROOT / 'reproduction.json').read_text(encoding='utf-8'))
rows = [row for row in data['cases'] if row['label'] == 'first-prefix-hit']
assert data['completed'] and data['same_workload_valid'] and len(rows) == 3
assert all(row['input_tokens'] == 6610 and row['cached_tokens'] == 4752 for row in rows)
assert any('_fused_post_conv_kernel' in event for event in rows[0]['jit_events'])
assert rows[0]['prefill_ms'] > max(300, 2 * data['hot_same_prefix_prefill_mean_ms'])
assert all(row['prefill_ms'] < 300 and row['queue_ms'] < 10 and not row['jit_events'] for row in rows[1:])
assert data['shared_model_unchanged'] and data['dependencies_unchanged'] and data['temporary_model_stopped']
print(json.dumps({'result': 'PASS', 'cold_prefill_ms': rows[0]['prefill_ms'],
                  'warmed_prefill_ms': [row['prefill_ms'] for row in rows[1:]],
                  'scope': '临时同模型合成输入、同长度同缓存数量；验证预热覆盖效果，不代表生产全面修复'}, ensure_ascii=False))
