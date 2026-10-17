"""真实 LLM 交付的商品、历史、重试、反馈与 Scylla 冷恢复验收。"""
import json
import re
import subprocess
import sys
import time
from measure import ready
from probe import ROOT,accounts,http,one

state=json.loads((ROOT/'state.json').read_text()); users=accounts(); phases=sys.argv[1:]
assert phases
rows=[]; failures=[]
for phase in phases:
    data=json.loads((ROOT/(phase+'.json')).read_text())
    failures.extend(data['failures'])
    rows.extend(row for group,values in data.items() if group!='failures' for row in values)
wire=[json.loads(line) for line in (ROOT/'model-wire.jsonl').read_text().splitlines()]
for row in rows:
    response=row['response']; assert response and not row['error']
    ids=[item['item_id'] for item in response['recommended_items']]
    assert len(ids)==len(set(ids))==5 and response['assistant_message']
    assert not response['degradation_reasons']
    assert set(ids)=={item['item_id'] for item in row['catalog']}
    assert row['history']['turns'][-1]['recommended_item_ids']==ids
    assert row['history']['turns'][-1]['finish_reason']=='FINAL_ANSWER'
    assert any(call['phase'] in phases and row['start_epoch_ms']<=call['epoch_ms']<=row['start_epoch_ms']+row['agent_done_ms']
               and (not row['label'].startswith('concurrent') or call.get('recommendation_card_set_id')==response['card_set_id']) for call in wire)
    trace=row['recommend_trace']
    assert trace['stage_counts']['deepfm_scored']>0 and trace['stage_counts']['bge_reranked']>0
    assert trace['config']['ranking_degraded']==0
deliveries=[row['response']['card_set_id'] for row in rows]
assert len(deliveries)==len(set(deliveries))
sample=json.loads((ROOT/(phases[0]+'.json')).read_text())['single'][1]
token=users[0]['accessToken']; session=sample['session_id']
(ROOT/'phase.txt').write_text('audit')
before=len((ROOT/'model-wire.jsonl').read_text().splitlines())
assert http('/api/agent/chat',sample['request_payload'],token)==sample['response']
assert http('/api/agent/sessions/'+session+'/history',token=token)==sample['history']
assert len((ROOT/'model-wire.jsonl').read_text().splitlines())==before
database=state['database'];assert re.fullmatch(r'rs_e2e_[a-f0-9]{8}',database)
assert re.fullmatch(r'sess_[a-z0-9]{32}',session)
cql=subprocess.run(['docker','exec','-i','rs-agent-java-scylla','cqlsh'],
    input=f"SELECT seq,entry_type FROM {database}.agent_transcript_entries_by_session WHERE session_id='{session}';",
    text=True,capture_output=True,check=True).stdout
assert 'ASSISTANT_FINAL' in cql and 'USER_MESSAGE' in cql
seqs=[int(value) for value in re.findall(r'^\s*(\d+)\s*\|',cql,re.MULTILINE)]
assert seqs and len(seqs)==max(seqs)
sql=f"USE `{database}`; SELECT last_seq FROM agent_sessions WHERE session_id='{session}'; SELECT first_seq,last_seq FROM agent_turns WHERE session_id='{session}';"
projection=subprocess.run(['docker','exec','-i','rs-agent-java-mysql','sh','-c',
    'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot -N -B'],input=sql,text=True,capture_output=True,check=True).stdout
assert projection.splitlines()==[str(max(seqs)), '1\t'+str(max(seqs))]
event={'request_id':sample['response']['card_set_id'],'session_id':session,
       'item_id':sample['response']['recommended_items'][0]['item_id'],'event_type':'like',
       'event_value':1,'occurred_at':int(time.time()*1000)}
ack=http('/api/recommend/feedback/event',event,token); duplicate=http('/api/recommend/feedback/event',event,token)
assert ack['application_status']=='APPLIED' and duplicate['duplicate'] and duplicate['feedback_id']==ack['feedback_id']
(ROOT/'phase.txt').write_text('after-feedback')
after_feedback=one(users[0],'推荐鼠标','fast','after-feedback')
(ROOT/'after-feedback.json').write_text(json.dumps(after_feedback,ensure_ascii=False,indent=2))
assert after_feedback.get('response') and not after_feedback.get('error')
assert len(after_feedback['response']['recommended_items'])==5 and not after_feedback['response']['degradation_reasons']
assert after_feedback['recommend_trace']['stage_counts']['deepfm_scored']>0
assert after_feedback['recommend_trace']['stage_counts']['bge_reranked']>0
assert after_feedback['recommend_trace']['config']['ranking_degraded']==0
redis_key='agent:session:'+session
ttl=int(subprocess.run(['docker','exec',state['redis'],'redis-cli','-p','18279','PTTL',redis_key+':events'],
    text=True,capture_output=True,check=True).stdout)
assert 0<ttl<=86400000
subprocess.run(['docker','exec',state['redis'],'redis-cli','-p','18279','DEL',redis_key+':events',redis_key+':snapshot'],capture_output=True,check=True)
subprocess.run(['python3',str(ROOT/'restart_services.py'),'control'],check=True)
ready();users=accounts();token=users[0]['accessToken']
(ROOT/'phase.txt').write_text('audit-cold-recovery')
before=len((ROOT/'model-wire.jsonl').read_text().splitlines())
assert http('/api/agent/sessions/'+session+'/history',token=token)==sample['history']
assert http('/api/agent/chat',sample['request_payload'],token)==sample['response']
assert len((ROOT/'model-wire.jsonl').read_text().splitlines())==before
report={'phases':phases,'successful_requests':len(rows)+1,'failed_requests':len(failures),
        'every_fresh_turn_calls_real_qwen':True,'five_real_unique_items_each':True,'independent_deliveries':True,
        'trained_deepfm_and_bge_each':True,'authoritative_scylla':cql,'mysql_projection':projection,
        'redis_ttl_ms':ttl,'retry_returns_identical_delivery_and_history_without_new_llm':True,
        'feedback_applied_and_deduplicated':True,'recommendation_after_feedback':True,
        'recovered_after_deleting_hot_keys_and_restarting':True}
(ROOT/'audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
assert not failures,'存在失败样本，不能通过完整验收'
print('真实 LLM 交付与持久化验收通过',len(rows)+1,'个请求',flush=True)
