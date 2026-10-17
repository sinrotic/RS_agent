"""公开证据关联及预热推广门槛；MTP 不通过规划与容量门槛。"""
import json
import argparse
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent


def load(name):
    return json.loads((ROOT / name).read_text())


def run(label):
    baseline = load('prefix_baseline2-state.json')
    candidate = load(label + '-state.json')
    assert baseline['passed'] and candidate['passed']
    assert baseline['owned_cleanup_passed'] and candidate['owned_cleanup_passed']
    assert baseline['model_path'] == candidate['model_path'] and baseline['budget'] == candidate['budget'] == .50
    assert baseline['resolved_scheduler'] == candidate['resolved_scheduler']
    assert baseline['resolved_cache'] == candidate['resolved_cache']
    before, after = load('prefix_baseline2-prefix.json'), load(label + '-prefix.json')
    assert [(row['case'], row['repeat'], row['input_sha256'], row['usage']['prompt_tokens']) for row in before['rows']] == [
        (row['case'], row['repeat'], row['input_sha256'], row['usage']['prompt_tokens']) for row in after['rows']]
    ratio = after['planning_first_response_median_ms'] / before['planning_first_response_median_ms']
    # 不改变吞吐调度；门槛在推广前固定，冷前缀收益不能掩盖明显稳态退化。
    from deploy_production import performance
    ratios = performance(load('prefix_baseline2-performance.json'), load(label + '-performance.json'))
    planning, control = load(label + '-planning.json'), load('baseline-planning.json')
    assert [(row['case'], row['repeat'], row['input_sha256'], row['sampling_seed'], row['temperature']) for row in planning['results']] == [
        (row['case'], row['repeat'], row['input_sha256'], row['sampling_seed'], row['temperature']) for row in control['results']]
    functional = all(planning[key] <= control[key] for key in ['incomplete_generations', 'schema_errors', 'rag_missing_query'])
    business = load(label + '-business.json')['business_regression']
    assert len(business) == 8 and all(row['passed'] and row['failed_tools'] == 0 for row in business)
    assert load(label + '-functional.json')['vision_passed']
    capacity = []
    for trial in ['prefix_baseline2', label]:
        log = (ROOT / (trial + '.log')).read_text()
        count = re.findall(r'GPU KV cache size: ([\d,]+) tokens', log)
        assert count
        capacity.append(int(count[-1].replace(',', '')))
    report = {'candidate': label, 'accepted': ratio <= .95 and functional and capacity[0] == capacity[1],
        'prefix_response_median_ratio': ratio, 'minimum_prefix_improvement': .05,
        'steady_median_ratios': ratios, 'planning_no_regression': functional,
        'kv_cache_tokens': capacity, 'scope': '规划前缀 1 token 冷启动响应，不代表完整生成提速或持续吞吐 SLA',
        'mtp_rejected': {'reason': '固定规划未完成数增加及 RAG query 缺失；另有容量下降',
                         'baseline': {key: control[key] for key in ['incomplete_generations', 'rag_missing_query']},
                         'candidate': {key: load('mtp1-planning.json')[key] for key in ['incomplete_generations', 'rag_missing_query']}}}
    contents = json.dumps(report, ensure_ascii=False, indent=2) + '\n'
    (ROOT / (label + '-selection.json')).write_text(contents)
    if report['accepted']:
        with (ROOT / 'warmup-selection.json').open('x') as handle:
            handle.write(contents)
    print(json.dumps(report, ensure_ascii=False), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--candidate', default='prefix_refilled', choices=['prefix_optimized', 'prefix_refilled'])
    run(parser.parse_args().candidate)
