"""依据前后基线选择调度候选；不改正式配置。"""
import json
from pathlib import Path
import statistics

ROOT = Path(__file__).resolve().parent
BASES = ['default_before', 'default_after']
TARGETS = ['mixed_c4', 'mixed_c8', 'mixed_c16']

def load(label):
    return json.loads((ROOT / (label + '-performance.json')).read_text())['tests']

def select():
    baselines = [load(label) for label in BASES]
    results = []
    for label in ['batch4096', 'batch8192']:
        state = json.loads((ROOT / (label + '-state.json')).read_text())
        record = {'label': label, 'eligible': False, 'state_passed': state['passed']}
        if state['passed']:
            current = load(label)
            ratios = {key: max(current[key]['summary']['e2e_median_ms'] / base[key]['summary']['e2e_median_ms']
                               for base in baselines) for key in TARGETS}
            record['mixed_median_ratio_against_both_baselines'] = ratios
            record['geometric_mean_mixed_ratio'] = statistics.geometric_mean(ratios.values())
            record['worst_decode128_ratio'] = max(current['decode128']['e2e_median_ms'] / base['decode128']['e2e_median_ms'] for base in baselines)
            all_summary_keys = [key for key in current if key.startswith(('warm_tool_', 'mixed_'))]
            record['worst_median_ratio'] = max(current[key]['summary']['e2e_median_ms'] / base[key]['summary']['e2e_median_ms']
                                             for key in all_summary_keys for base in baselines)
            record['worst_p95_ratio'] = max(current[key]['summary']['e2e_p95_ms'] / base[key]['summary']['e2e_p95_ms']
                                          for key in all_summary_keys for base in baselines)
            record['eligible'] = (record['geometric_mean_mixed_ratio'] <= .92 and record['worst_decode128_ratio'] <= 1.05
                and record['worst_median_ratio'] <= 1.10 and record['worst_p95_ratio'] <= 1.15)
        results.append(record)
    eligible = sorted([row for row in results if row['eligible']], key=lambda row: row['geometric_mean_mixed_ratio'])
    report = {'selection_scope': '按前后两组小样本模型基线筛选；仍需候选功能、真实业务及正式同卡复验',
        'gate': '混合请求几何平均耗时至少降低8%，固定128token不退化超过5%，场景中位数不退化超过10%，样本P95不退化超过15%',
        'candidates': results, 'winner': eligible[0]['label'] if eligible else None}
    (ROOT / 'selection.json').write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return report

if __name__ == '__main__':
    select()
