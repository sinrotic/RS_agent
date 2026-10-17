"""核验完整商品交付、权威记录、重试、真实反馈与冷恢复。"""
import json
import re
import subprocess
import time
from measure import ready
from probe import ROOT, accounts, http, one

state = json.loads((ROOT / 'state.json').read_text()); users = accounts()
rows = []; failures = []
for phase in ('optimized-final', 'ordinary-final', 'profiled'):
    data = json.loads((ROOT / (phase + '.json')).read_text())
    rows.extend(row for group, values in data.items() if group != 'failures' for row in values)
    failures.extend(data['failures'])
for row in rows:
    response = row['response']; assert response and not row['error']
    ids = [item['item_id'] for item in response['recommended_items']]
    assert len(ids) == len(set(ids)) == 5 and response['assistant_message']
    assert not response['degradation_reasons']
    assert set(ids) == {item['item_id'] for item in row['catalog']}
    assert row['history']['turns'][-1]['recommended_item_ids'] == ids
    assert row['history']['turns'][-1]['finish_reason'] == 'FINAL_ANSWER'
    trace = row['recommend_trace']
    assert trace['stage_counts']['deepfm_scored'] > 0 and trace['stage_counts']['bge_reranked'] > 0
    assert trace['config']['ranking_degraded'] == 0
deliveries = [row['response']['card_set_id'] for row in rows]
assert len(deliveries) == len(set(deliveries))
sample = json.loads((ROOT / 'optimized-final.json').read_text())['single'][1]
token = users[0]['accessToken']; session = sample['session_id']
assert http('/api/agent/chat', sample['request_payload'], token) == sample['response']
assert http('/api/agent/sessions/' + session + '/history', token=token) == sample['history']
database = state['database']; assert re.fullmatch(r'rs_e2e_[a-f0-9]{8}', database)
assert re.fullmatch(r'sess_[a-z0-9]{32}', session)
cql = subprocess.run(['docker', 'exec', '-i', 'rs-agent-java-scylla', 'cqlsh'],
    input=f"SELECT seq,entry_type FROM {database}.agent_transcript_entries_by_session WHERE session_id='{session}';",
    text=True, capture_output=True, check=True).stdout
assert 'ASSISTANT_FINAL' in cql and 'USER_MESSAGE' in cql and '(4 rows)' in cql
sql = f"USE `{database}`; SELECT last_seq FROM agent_sessions WHERE session_id='{session}'; SELECT first_seq,last_seq FROM agent_turns WHERE session_id='{session}';"
projection = subprocess.run(['docker', 'exec', '-i', 'rs-agent-java-mysql', 'sh', '-c',
    'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -N -B'], input=sql, text=True, capture_output=True, check=True).stdout
assert projection.splitlines() == ['4', '1\t4']
event = {'request_id': sample['response']['card_set_id'], 'session_id': session,
         'item_id': sample['response']['recommended_items'][0]['item_id'], 'event_type': 'like',
         'event_value': 1, 'occurred_at': int(time.time() * 1000)}
ack = http('/api/recommend/feedback/event', event, token); duplicate = http('/api/recommend/feedback/event', event, token)
assert ack['application_status'] == 'APPLIED' and duplicate['duplicate']
assert duplicate['feedback_id'] == ack['feedback_id']
# 反馈改变偏好后再运行，覆盖上次相同查询落入普通 Agent 而失败的场景。
after_feedback = one(users[0], '推荐鼠标', 'fast', 'after-feedback')
(ROOT / 'after-feedback.json').write_text(json.dumps(after_feedback, ensure_ascii=False, indent=2))
assert after_feedback.get('response') and not after_feedback.get('error')
assert len(after_feedback['response']['recommended_items']) == 5
assert not after_feedback['response']['degradation_reasons']
assert after_feedback['recommend_trace']['stage_counts']['deepfm_scored'] > 0
assert after_feedback['recommend_trace']['stage_counts']['bge_reranked'] > 0
assert after_feedback['recommend_trace']['config']['ranking_degraded'] == 0
redis_key = 'agent:session:' + session
ttl = int(subprocess.run(['docker', 'exec', state['redis'], 'redis-cli', '-p', '18279', 'PTTL', redis_key + ':events'],
    text=True, capture_output=True, check=True).stdout)
assert 0 < ttl <= 86400000
subprocess.run(['docker', 'exec', state['redis'], 'redis-cli', '-p', '18279', 'DEL',
                redis_key + ':events', redis_key + ':snapshot'], check=True, capture_output=True)
subprocess.run(['python3', str(ROOT / 'restart_services.py'), 'control'], check=True)
ready()
assert http('/api/agent/sessions/' + session + '/history', token=token) == sample['history']
assert http('/api/agent/chat', sample['request_payload'], token) == sample['response']
initial_failures = json.loads((ROOT / 'ordinary.json').read_text())['failures']
report = {'complete_successful_requests': len(rows) + 1, 'failed_requests': len(failures),
          'pre_fix_ordinary_failed_requests': len(initial_failures), 'pre_fix_failures_preserved': True,
          'all_failures_preserved': True, 'five_real_items_each': True, 'independent_deliveries': True,
          'trained_deepfm_and_bge_each': True, 'authoritative_scylla': cql,
          'mysql_projection': projection, 'redis_ttl_ms': ttl,
          'retry_returns_identical_delivery_and_history': True, 'feedback_applied_and_deduplicated': True,
          'recommendation_after_feedback': True, 'recovered_after_deleting_hot_keys_and_restarting': True}
(ROOT / 'audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
assert not failures, '有失败样本，必须调查后再报告验收结果'
print('正确性验收通过', len(rows) + 1, '成功请求', flush=True)
