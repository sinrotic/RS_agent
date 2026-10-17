"""汇总离线与隔离服务门槛，故障注入仅停止新运行时；不触碰旧运行时。"""
import json,subprocess,sys,time,urllib.request
from pathlib import Path
import numpy as np
ROOT=Path('/mnt/data/luo/remote_runs/product_v14_training')
sys.path.insert(0,str(ROOT/'scripts'))
from serve_product_v14 import wait_health
sys.path.insert(0,'/tmp/rs-agent-e2e-20261010-llm-opt-20261011')
from probe import http,accounts

def main():
    live=json.loads(subprocess.check_output(['docker','inspect','rs-e2e-857e8b14-recommend-fast']))[0]
    original=json.loads((ROOT/'deployment/original.private.json').read_text())
    if live['Id']!=original['Id']:raise RuntimeError('线上容器已切换；禁止对活跃运行时执行隔离故障注入')
    final=json.loads((ROOT/'final_validation.json').read_text())
    ann=json.loads((ROOT/'ann_verification.json').read_text())
    baseline=json.loads((ROOT/'baseline_replay.json').read_text())
    candidate=json.loads((ROOT/'candidate_replay.json').read_text())
    checks={'frozen_test_regression':final['state']=='PASS','ann':ann['state']=='PASS','candidate_replay':candidate['state']=='PASS',
        'semantic_type_smoke_vs_online':sum(x['type_title_matches'] for x in candidate['semantic'])>=sum(x['type_title_matches'] for x in baseline['semantic']),
        'home_latency':np.quantile([r['elapsed_ms'] for r in candidate['home']],.95)<=max(4000,2*np.quantile([r['elapsed_ms'] for r in baseline['home']],.95))}
    import hashlib
    metadata=json.loads((ROOT/'data/manifest.json').read_text())
    ready=ROOT/'data/sealed_snapshot_ready.json'
    selection=json.loads((ROOT/'selection.json').read_text())
    snapshot=ready if ready.exists() else ROOT/'data/manifest.json'
    sealed_rows=[json.loads(line) for line in (ROOT/'data/sealed_future.jsonl').open()]
    checks['sealed_snapshot_integrity']=snapshot.stat().st_mtime<selection['timestamp'] and len(sealed_rows)==metadata['sealed_count'] and all(len(x['history_full'])>=2 for x in sealed_rows) and hashlib.sha256((ROOT/'data/sealed_future.jsonl').read_bytes()).hexdigest()==metadata.get('sealed_sha256',metadata.get('sha256'))
    sealed=json.loads((ROOT/'results.json').read_text())['sealed']
    current=sealed['candidate']['sealed_future']['metrics']
    reference=sealed['online_expanded']['sealed_future']['metrics']
    initial=sealed['initial']['sealed_future']['metrics']
    actual=sealed['online_actual']['sealed_future']['metrics']
    checks['sealed_hit100']=current['hit@100']>=max(reference['hit@100'],actual['hit@100'])
    checks['sealed_hit10']=current['hit@10']>=actual['hit@10']
    checks['sealed_mrr']=current['mrr']>=max(reference['mrr'],actual['mrr'])
    # 缓存尚未出现过新model_key的第四个测试账号，保证用户塔真正遇到不可用。
    account=accounts()[4];token=account['accessToken'];base='http://127.0.0.1:18238'
    session=http('/api/sessions',{'entryScene':'v11-fallback-test'},token)['sessionId']
    try:
        subprocess.run(['systemctl','--user','stop','rs-product-v14-runtime.service'],check=True)
        request=urllib.request.Request(base+'/api/recommend/home',data=json.dumps({'session_id':session,'scene':'home','page_size':6,'debug':True}).encode(),
            headers={'Content-Type':'application/json','X-Account-Id':account['accountId'],'X-Profile-User-Id':account['profileUserId']})
        with urllib.request.urlopen(request,timeout=60) as response:home=json.load(response)
        checks['user_fault_fallback']=len(home['items'])==6 and 'two_tower_unavailable' in home['degradation_reasons']
        payload={'agent_id':'rs_agent','task_id':'v11-fault-'+str(time.time_ns()),'session_id':session,'account_id':account['accountId'],
            'profile_user_id':account['profileUserId'],'query':'wireless silent mouse','return_count':6,'recall_limit':120,'scene':'agent_chat'}
        semantic=http('/agent/recommend/semantic-recall',payload,base=base)
        checks['query_fault_fallback']=len(semantic['candidates'])==6
        (ROOT/'fault_replay.json').write_text(json.dumps({'home':home,'semantic':semantic},ensure_ascii=False,indent=2))
    finally:
        subprocess.run(['systemctl','--user','start','rs-product-v14-runtime.service'],check=True)
        wait_health(18132,'172.21.0.1','/health')
    checks['old_service_healthy']=wait_health(18213)['status']=='UP'
    from load_product_v14 import compare
    checks['concurrency8']=compare()['state']=='PASS'
    checks['guard_ann']=json.loads((ROOT/'guard_ann_verification.json').read_text())['state']=='PASS'
    checks={k:bool(v) for k,v in checks.items()}
    result={'state':'PASS' if all(checks.values()) else 'FAIL','checks':checks,'jar_sha256':hashlib.sha256((ROOT/'rs-service-recommend.jar').read_bytes()).hexdigest(),'guarded_route_ann':json.loads((ROOT/'guard_ann_verification.json').read_text())['state'],'model_sha256':json.loads((ROOT/'export/manifest.json').read_text())['output_hashes']['model.pt'],'timestamp':time.time()}
    (ROOT/'serving_gate.json').write_text(json.dumps(result,indent=2));print(json.dumps(result),flush=True)

if __name__=='__main__':main()

