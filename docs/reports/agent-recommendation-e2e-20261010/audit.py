"""验收真实阶段、独立交付、Scylla 最终提交、反馈与热状态丢失后的恢复。"""
import json
import re
import subprocess
import time
from pathlib import Path
from probe import ROOT, accounts, http

state=json.loads((ROOT/'state.json').read_text()); users=accounts()
report={'checks':{},'metrics':{}}
names=['optimized-mouse','optimized-cold-warm','optimized-cold-concurrent',
       'baseline-five-1','baseline-five-2','fallback-headphones','baseline-concurrent']
successful=[]; failed=[]
for name in names:
    data=json.loads((ROOT/(name+'.json')).read_text())
    rows=data.get('single',[])+data.get('concurrent_8',[]) if 'single' in data else [data]
    for row in rows:
        if not row['response']:
            failed.append({'source':name,'session_id':row['session_id'],'error':row['error'],'elapsed_ms':row['agent_done_ms']})
            continue
        final=row['response']; ids=[v['item_id'] for v in final['recommended_items']]
        assert len(ids)==5 and len(set(ids))==5
        assert final['assistant_message'] and not final['degradation_reasons']
        assert {v['item_id'] for v in row['catalog']}==set(ids)
        assert len(row['history']['turns'])==1 and row['history']['turns'][0]['finish_reason']=='FINAL_ANSWER'
        assert row['history']['turns'][0]['recommended_item_ids']==ids
        stages=row['recommend_trace']['stage_counts']
        assert stages['deepfm_scored']>0 and stages['bge_reranked']==96
        assert row['recommend_trace']['config']['ranking_degraded']==0
        successful.append(row)
deliveries=[r['response']['card_set_id'] for r in successful]
assert len(deliveries)==len(set(deliveries))
report['checks'].update(successful_complete_requests=len(successful),failed_requests=failed,
   five_real_items_each=True,separate_deliveries=True,real_deepfm_and_96_bge=True,final_history_each=True)
sample=json.loads((ROOT/'optimized-cold-warm.json').read_text())['single'][1]
session=sample['session_id']; assert re.fullmatch(r'sess_[a-z0-9]{32}',session)
database=state['database']; assert re.fullmatch(r'rs_e2e_[a-f0-9]{8}',database)
query=f"SELECT seq,entry_type FROM {database}.agent_transcript_entries_by_session WHERE session_id='{session}';"
cql=subprocess.run(['docker','exec','-i','rs-agent-java-scylla','cqlsh'],input=query,text=True,
                   capture_output=True,check=True,timeout=30).stdout
assert 'ASSISTANT_FINAL' in cql and 'USER_MESSAGE' in cql
report['checks']['scylla_transcript']=cql
event={'request_id':sample['response']['card_set_id'],'session_id':session,
       'item_id':sample['response']['recommended_items'][0]['item_id'],'event_type':'like',
       'event_value':1,'occurred_at':int(time.time()*1000)}
ack=http('/api/recommend/feedback/event',event,users[0]['accessToken'])
assert ack['application_status']=='APPLIED'
duplicate=http('/api/recommend/feedback/event',event,users[0]['accessToken'])
assert duplicate['duplicate'] and duplicate['feedback_id']==ack['feedback_id']
report['checks']['feedback_delivery_attribution_and_idempotency']=True
for cache in ['recommend_query_embedding','recommend_bge_scores']:
    for result in ['hit','miss']:
        try:
            report['metrics'][cache+'_'+result]=http('/actuator/metrics/cache.gets?tag=cache:'+cache+'&tag=result:'+result,
                                                   base='http://127.0.0.1:18213')['measurements']
        except Exception as ex: report['metrics'][cache+'_'+result]={'unavailable':str(ex)}
subprocess.run(['docker','exec',state['redis'],'redis-cli','-p','18279','DEL',
                'agent:session:'+session+':events','agent:session:'+session+':snapshot'],check=True,capture_output=True)
subprocess.run(['python3',str(ROOT/'replace_fast.py')],check=True)
for _ in range(60):
    try:
        if http('/actuator/health',base='http://127.0.0.1:18214')['status']=='UP': break
    except Exception: pass
    time.sleep(1)
else: raise RuntimeError('restarted Agent not ready')
history=http('/api/agent/sessions/'+session+'/history',token=users[0]['accessToken'])
assert history==sample['history'], 'Redis 和进程缓存清除后必须恢复相同的最终历史'
report['checks']['history_recovered_without_redis_hot_state_or_process_cache']=True
(ROOT/'audit.json').write_text(json.dumps(report,ensure_ascii=False,indent=2))
print('AUDIT PASSED',len(successful),'complete; failures',len(failed),flush=True)
