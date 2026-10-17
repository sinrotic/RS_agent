"""8个不同测试账号、独立会话的主页并发回放；仅用于候选与现网延迟对照。"""
import concurrent.futures,json,sys,time,urllib.request
from pathlib import Path
import numpy as np
sys.path.insert(0,'/tmp/rs-agent-e2e-20261010-llm-opt-20261011')
from probe import accounts,http
ROOT=Path('/mnt/data/luo/remote_runs/product_v16_final')

def compare():
    users=accounts()[:8];assert len(users)==8
    history={u['profileUserId']:set(http('/internal/users/context/positive-history',{'profile_user_id':u['profileUserId'],'limit':80},base='http://127.0.0.1:18201')) for u in users}
    results={}
    for name,port in [('baseline',18213),('candidate',18242)]:
        inputs=[(u,http('/api/sessions',{'entryScene':'v9-concurrency8'},u['accessToken'])['sessionId']) for u in users]
        def request(pair):
            account,session=pair
            req=urllib.request.Request(f'http://127.0.0.1:{port}/api/recommend/home',
                data=json.dumps({'session_id':session,'scene':'home','page_size':6,'debug':True}).encode(),
                headers={'Content-Type':'application/json','X-Account-Id':account['accountId'],'X-Profile-User-Id':account['profileUserId']})
            start=time.monotonic()
            with urllib.request.urlopen(req,timeout=60) as f:value=json.load(f)
            elapsed=(time.monotonic()-start)*1000;ids={r['item_id'] for r in value['items']}
            assert len(ids)==6 and not ids&history[account['profileUserId']]
            assert 'two_tower_unavailable' not in value['degradation_reasons']
            return {'elapsed_ms':elapsed,'request_id':value['request_id'],'count':len(ids),'degradation_reasons':value['degradation_reasons']}
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:rows=list(pool.map(request,inputs))
        results[name]={'rows':rows,'p95_ms':float(np.quantile([r['elapsed_ms'] for r in rows],.95)),'success':len(rows)}
    results['state']='PASS' if results['candidate']['p95_ms']<=max(5000,2*results['baseline']['p95_ms']) else 'FAIL'
    (ROOT/'concurrency_replay.json').write_text(json.dumps(results,ensure_ascii=False,indent=2))
    return results

if __name__=='__main__':print(json.dumps(compare(),ensure_ascii=False),flush=True)
