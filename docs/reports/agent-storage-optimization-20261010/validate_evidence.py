"""独立核对本地保存的结果数量、最终交付与远端构建，避免只统计成功样本。"""
import json
from pathlib import Path
import re
import sys

sys.stdout.reconfigure(encoding='utf-8')
HERE = Path(__file__).resolve().parent
def read(name): return json.loads((HERE / (name + '.json')).read_text(encoding='utf-8'))
def rows(name):
    data = read(name)
    if isinstance(data, list): return data
    if 'session_id' in data: return [data]
    return [row for group in data.values() if isinstance(group, list) for row in group]

phases = ('optimized', 'ordinary', 'diagnostic-sync', 'wire-diagnostic', 'diagnostic-sync-repeated',
          'ordinary-fixed', 'profiled', 'optimized-before-transport', 'ordinary-before-transport',
          'optimized-final', 'ordinary-final', 'after-feedback')
counts = {}
for phase in phases:
    values = rows(phase)
    complete = [row for row in values if (row.get('response') or {}).get('recommended_items') and not row.get('error')]
    counts[phase] = {'attempts': len(values), 'complete': len(complete), 'failed': len(values) - len(complete),
                     'ranking_degraded': sum(bool(row['response'].get('degradation_reasons')) for row in complete)}
totals = {key: sum(value[key] for value in counts.values()) for key in next(iter(counts.values()))}
assert totals == {'attempts': 151, 'complete': 148, 'failed': 3, 'ranking_degraded': 1}, totals
for phase in ('optimized-final', 'ordinary-final', 'profiled', 'after-feedback'):
    for row in rows(phase):
        assert row.get('response') and not row.get('error')
        ids = [item['item_id'] for item in row['response']['recommended_items']]
        assert len(ids) == len(set(ids)) == 5
        assert not row['response']['degradation_reasons']
        assert row['recommend_trace']['stage_counts']['deepfm_scored'] > 0
        assert row['recommend_trace']['stage_counts']['bge_reranked'] > 0
        assert row['recommend_trace']['config']['ranking_degraded'] == 0
build = read('build'); restoration = read('restoration'); audit = read('audit')
assert audit['complete_successful_requests'] == 64 and audit['failed_requests'] == 0
for module, sha in restoration['business_jar_sha256'].items(): assert build[module] == sha
assert not restoration['qa_containers_remaining'] and not restoration['qa_private_files_remaining']
assert all(restoration['training_original_pids_present'].values())
for link in re.findall(r'\]\(([^)]+)\)', (HERE / 'README.md').read_text(encoding='utf-8')):
    assert (HERE / link).exists(), link
result = {'total_entered_chat_attempts': totals, 'phases': counts, 'final_audited_success': 64,
          'expired_token_requests_before_entering_chat': sum(len(rows(name)) for name in ('optimized-expired-token', 'ordinary-expired-token')),
          'build_hashes_match_qa': True, 'artifact_links_exist': True, 'cleanup_verified': True}
(HERE / 'validation.json').write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
print('证据验收通过', json.dumps(result['total_entered_chat_attempts'], ensure_ascii=False))
