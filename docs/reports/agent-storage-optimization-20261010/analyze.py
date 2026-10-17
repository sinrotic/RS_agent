"""沿用前一轮互斥计时口径，对比无探针时延与提交、筛选子阶段。"""
import importlib.util
import json
from pathlib import Path
import statistics
import sys

sys.stdout.reconfigure(encoding='utf-8')

HERE = Path(__file__).resolve().parent
source = HERE.parent / 'agent-latency-profile-20261010' / 'analyze.py'
spec = importlib.util.spec_from_file_location('latency_analysis', source)
analysis = importlib.util.module_from_spec(spec); spec.loader.exec_module(analysis)
analysis.HERE = HERE
result = {name: analysis.summarize(name) for name in ('optimized', 'optimized-final', 'profiled')}
ordinary = json.loads((HERE / 'ordinary-final.json').read_text(encoding='utf-8'))
result['ordinary_fixed'] = {group: analysis.stats([row['complete_with_catalog_ms'] for row in ordinary[group]])
                            for group in ('single', 'multi_turn')}
result['ordinary_fixed']['failed_requests'] = len(ordinary['failures'])
before = json.loads((HERE.parent / 'agent-latency-profile-20261010' / 'summary.json').read_text(encoding='utf-8'))
result['previous_hdd'] = {group: before['control']['groups'][group]['complete_ms'] for group in ('single','concurrent_8')}
result['median_reduction'] = {group: 1 - result['optimized-final']['groups'][group]['complete_ms']['median'] /
                             result['previous_hdd'][group]['median'] for group in ('single','concurrent_8')}
(HERE / 'summary.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
for name, data in result.items():
    if 'groups' in data:
        print(name, {g:v['complete_ms'] for g,v in data['groups'].items()})
        if data['groups']['single'].get('recommend_substages_ms'):
            print('子阶段', data['groups']['single']['recommend_substages_ms'])
    else: print(name, data)
