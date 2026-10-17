"""重复并发批次，区分首次突发和已扩容连接池下的稳态。"""
import concurrent.futures
import json
import statistics
from measure import ready
from probe import ROOT, accounts, one

ready(); users = accounts(); result = {'warmups': [], 'bursts': [], 'failures': []}
def save(): (ROOT / 'nvme-repeated.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
for i, user in enumerate(users):
    row = one(user, '推荐鼠标', 'fast', f'repeat-warmup-{i}')
    (result['warmups'] if row.get('response') else result['failures']).append(row); save()
for index in range(3):
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
        rows = list(pool.map(lambda user: one(user, '推荐鼠标', 'fast', f'repeat-burst-{index}'), users))
    result['bursts'].append(rows); save()
attempts = result['warmups'] + [row for burst in result['bursts'] for row in burst]
all_rows = [row for row in attempts if row.get('response')]
result['failures'] = [row for row in attempts if not row.get('response')]; save()
for row in all_rows:
    response = row['response']; assert response and not row['error'] and not response['degradation_reasons']
    ids = [item['item_id'] for item in response['recommended_items']]
    assert len(ids) == len(set(ids)) == 5 and response['assistant_message']
    assert set(ids) == {item['item_id'] for item in row['catalog']}
    assert len(row['history']['turns']) == 1 and row['history']['turns'][0]['finish_reason'] == 'FINAL_ANSWER'
    assert row['history']['turns'][0]['recommended_item_ids'] == ids
    trace = row['recommend_trace']
    assert trace['stage_counts']['deepfm_scored'] > 0 and trace['stage_counts']['bge_reranked'] == 96
    assert trace['config']['ranking_degraded'] == 0
assert len({row['response']['card_set_id'] for row in all_rows}) == len(all_rows)
summary = {'complete_successful_requests': len(all_rows), 'failed_requests': len(result['failures']),
           'five_real_items_and_independent_deliveries': True, 'trained_ranking_96_bge_and_final_history': True,
           'bursts': [{'attempted': len(rows), 'successful': sum(bool(row.get('response')) for row in rows),
                       'failed': sum(not bool(row.get('response')) for row in rows),
                       'min_success_ms': min(row['complete_with_catalog_ms'] for row in rows if row.get('response')),
                       'median_success_ms': statistics.median(row['complete_with_catalog_ms'] for row in rows if row.get('response')),
                       'max_success_ms': max(row['complete_with_catalog_ms'] for row in rows if row.get('response'))}
                      for rows in result['bursts']]}
(ROOT / 'repeat-validation.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2))
print('重复并发核验', json.dumps(summary, ensure_ascii=False), flush=True)
