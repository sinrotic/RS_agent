"""真实账号主页与语义回放；保留历史排除/分页/主召回证据，不输出凭据。"""
import argparse,concurrent.futures,json,re,sys,time,urllib.request
from pathlib import Path
ROOT=Path('/mnt/data/luo/remote_runs/product_v8_training')
sys.path.insert(0,'/tmp/rs-agent-e2e-20261010-llm-opt-20261011')
from probe import http,accounts

QUERIES=[('办公用的静音鼠标',r'mouse|mice'),('silent wireless mouse for office',r'mouse|mice'),
    ('适合电脑的机械键盘',r'keyboard'),('mechanical keyboard for PC',r'keyboard'),
    ('运动用的无线蓝牙耳机',r'headphone|headset|earbud|earphone'),('wireless bluetooth earbuds for running',r'headphone|headset|earbud|earphone'),
    ('USB-C转HDMI扩展坞',r'hub|dock|adapter'),('USB C hub with HDMI',r'hub|dock|adapter'),
    ('便携式固态硬盘',r'ssd|solid state|solid-state'),('portable external SSD',r'ssd|solid state|solid-state')]

def main(args):
    users=accounts();base=f'http://127.0.0.1:{args.port}';records=[];semantic=[]
    for account in users[:3]:
        session=http('/api/sessions',{'entryScene':'product-v8-verification'},account['accessToken'])['sessionId']
        history=set(http('/internal/users/context/positive-history',{'profile_user_id':account['profileUserId'],'limit':80},base='http://127.0.0.1:18201'))
        previous=set();cursor=''
        for page in range(2):
            payload={'session_id':session,'scene':'home','page_size':6,'cursor':cursor,'debug':True}
            headers={'Content-Type':'application/json','X-Account-Id':account['accountId'],'X-Profile-User-Id':account['profileUserId']}
            if args.port==18288:headers={'Content-Type':'application/json','Authorization':'Bearer '+account['accessToken']}
            req=urllib.request.Request(base+'/api/recommend/home',data=json.dumps(payload).encode(),headers=headers)
            start=time.monotonic()
            with urllib.request.urlopen(req,timeout=60) as f:response=json.load(f)
            elapsed=(time.monotonic()-start)*1000;cursor=response['next_cursor']
            trace=http('/api/platform/recommend/'+response['request_id']+'/trace',base=f'http://127.0.0.1:{18213 if args.port==18288 else args.port}')
            ids={x['item_id'] for x in response['items']}
            assert len(ids)==6 and not ids&history and not ids&previous;previous|=ids
            assert trace['stage_counts'].get('primary_recall',0)>=270
            assert not any(d in ['two_tower_unavailable','profile_history_unavailable'] for d in response['degradation_reasons'])
            records.append({'page':page,'elapsed_ms':elapsed,'response':response,'trace':trace})
            print('HOME',page,round(elapsed),'primary',trace['stage_counts'].get('primary_recall'),flush=True)
    service=f'http://127.0.0.1:{18213 if args.port==18288 else args.port}'
    a=users[0]
    for query,pattern in QUERIES:
        payload={'agent_id':'rs_agent','task_id':'v8-'+str(time.time_ns()),'session_id':'v8-validation','account_id':a['accountId'],
            'profile_user_id':a['profileUserId'],'query':query,'return_count':6,'recall_limit':120,'scene':'agent_chat'}
        start=time.monotonic();response=http('/agent/recommend/semantic-recall',payload,base=service)
        candidates=response['candidates'];assert len(candidates)==6 and len({c['item_id'] for c in candidates})==6
        matches=sum(bool(re.search(pattern,c['title'],re.I)) for c in candidates)
        semantic.append({'query':query,'type_title_matches':matches,'count':6,'elapsed_ms':(time.monotonic()-start)*1000,'response':response})
        print('SEMANTIC',query,matches,'/6',flush=True)
    passed=sum(r['type_title_matches'] for r in semantic)>=48
    result={'state':'PASS' if passed else 'FAIL','port':args.port,'home':records,'semantic':semantic,
        'limitations':'语义标题关键词仅做商品类型冒烟检查，不是独立人工相关性评测；测试账号回放不代表真实线上收益'}
    (ROOT/args.output).write_text(json.dumps(result,ensure_ascii=False,indent=2))
    assert passed,'semantic product-type smoke gate failed'

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,required=True);p.add_argument('--output',required=True);main(p.parse_args())
