"""保持原两条前缀，只以首次并发突发收益选择新预热方案。"""
import json
from pathlib import Path
import re

from deploy_production import performance

ROOT = Path(__file__).resolve().parent


def load(name):
    return json.loads((ROOT / name).read_text())


candidate = load('startup16-state.json')
assert candidate['passed'] and candidate['owned_cleanup_passed']
assert not candidate['mtp'] and not candidate['expanded_prefixes']
assert candidate['prewarm16'] and candidate['final_prefix_refresh']
assert candidate['resolved_scheduler'] == load('prefix_baseline2-state.json')['resolved_scheduler']
control, current = load('prefix_baseline2-performance.json'), load('startup16-performance.json')
ratio = current['tests']['first_burst16']['summary']['e2e_median_ms'] / control['tests']['first_burst16']['summary']['e2e_median_ms']
ratios = performance(control, current)
planning, baseline = load('startup16-planning.json'), load('baseline-planning.json')
assert [(row['case'], row['repeat'], row['input_sha256'], row['sampling_seed'], row['temperature']) for row in planning['results']] == [
    (row['case'], row['repeat'], row['input_sha256'], row['sampling_seed'], row['temperature']) for row in baseline['results']]
functional = all(planning[key] <= baseline[key] for key in ['incomplete_generations', 'schema_errors', 'rag_missing_query'])
business = load('startup16-business.json')['business_regression']
assert len(business) == 8 and all(row['passed'] and row['failed_tools'] == 0 for row in business)
assert load('startup16-functional.json')['vision_passed']
tokens = int(re.findall(r'GPU KV cache size: ([\d,]+) tokens', (ROOT / 'startup16.log').read_text())[-1].replace(',', ''))
report = {'candidate': 'startup16', 'accepted': ratio <= .92 and functional and tokens == 106496,
    'scope': '原两条前缀不变，以首次16路短工具突发至少降低8%为目标，仍需正式同卡稳态、P95和业务验收',
    'first_burst_median_ratio': ratio, 'minimum_first_burst_improvement': .08,
    'steady_median_ratios': ratios, 'planning_no_regression': functional, 'kv_cache_tokens': tokens}
with (ROOT / 'startup16-selection.json').open('x') as handle:
    handle.write(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps(report, ensure_ascii=False), flush=True)
