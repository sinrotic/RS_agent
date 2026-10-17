"""核验完整交付、真实排序、重试、反馈，以及清除热状态和重启后的恢复。"""
import json
import re
import subprocess
import time
from probe import ROOT, accounts, http

state = json.loads((ROOT / 'state.json').read_text())
users = accounts()
comparison = json.loads((ROOT / 'comparison.json').read_text())
final = json.loads((ROOT / 'final-matrix.json').read_text())
rows = [row for group in comparison.values() for row in group] + final['single'] + final['concurrent_8']
for filename in ('baseline-profile-warmups.json', 'fast-profile-warmups.json'):
    rows += json.loads((ROOT / filename).read_text())
rows += [json.loads((ROOT / name).read_text()) for name in ('before-first.json', 'after-first.json')]
for row in rows:
    response = row['response']
    assert response and not row['error']
    ids = [item['item_id'] for item in response['recommended_items']]
    assert len(ids) == len(set(ids)) == 5 and response['assistant_message']
    assert not response['degradation_reasons']
    assert set(ids) == {item['item_id'] for item in row['catalog']}
    assert len(row['history']['turns']) == 1
    assert row['history']['turns'][0]['recommended_item_ids'] == ids
    assert row['history']['turns'][0]['finish_reason'] == 'FINAL_ANSWER'
    trace = row['recommend_trace']
    assert trace['stage_counts']['deepfm_scored'] > 0 and trace['stage_counts']['bge_reranked'] == 96
    assert trace['config']['ranking_degraded'] == 0
deliveries = [row['response']['card_set_id'] for row in rows]
assert len(deliveries) == len(set(deliveries))

sample = final['single'][1]
token = users[0]['accessToken']
replayed = http('/api/agent/chat', sample['request_payload'], token)
assert replayed == sample['response'], '重试必须返回同一完整结果和同一交付 ID'
assert http('/api/agent/sessions/' + sample['session_id'] + '/history', token=token) == sample['history']

session = sample['session_id']
database = state['database']
assert re.fullmatch(r'sess_[a-z0-9]{32}', session)
assert re.fullmatch(r'rs_e2e_[a-f0-9]{8}', database)
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
ack = http('/api/recommend/feedback/event', event, token)
duplicate = http('/api/recommend/feedback/event', event, token)
assert ack['application_status'] == 'APPLIED'
assert duplicate['duplicate'] and duplicate['feedback_id'] == ack['feedback_id']

ttl = subprocess.run(['docker', 'exec', state['redis'], 'redis-cli', '-p', '18279',
        'PTTL', 'agent:session:' + session + ':events'], text=True, capture_output=True, check=True).stdout
assert 0 < int(ttl) <= 86400000
subprocess.run(['docker', 'exec', state['redis'], 'redis-cli', '-p', '18279', 'DEL',
        'agent:session:' + session + ':events', 'agent:session:' + session + ':snapshot'], check=True, capture_output=True)
subprocess.run(['python3', str(ROOT / 'replace_fast.py')], check=True)
for _ in range(60):
    try:
        if http('/actuator/health', base='http://127.0.0.1:18214')['status'] == 'UP':
            break
    except Exception:
        pass
    time.sleep(1)
else:
    raise RuntimeError('重启后 Agent 未就绪')
history = http('/api/agent/sessions/' + session + '/history', token=token)
assert history == sample['history']
assert http('/api/agent/chat', sample['request_payload'], token) == sample['response']
report = {'successful_complete_requests': len(rows), 'steady_state_failed_requests': 0,
          'five_real_items_each': True, 'separate_deliveries': True, 'deepfm_and_96_bge_each': True,
          'scylla_transcript': cql, 'mysql_projection': projection,
          'retry_without_new_delivery_or_history': True, 'feedback_applied_and_deduplicated': True,
          'redis_ttl_ms': int(ttl), 'recovered_without_hot_state_or_process_cache': True}
(ROOT / 'audit.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
print('AUDIT PASSED', len(rows), 'complete requests', flush=True)
