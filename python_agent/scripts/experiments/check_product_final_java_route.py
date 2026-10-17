"""实际Java单模型召回与新用户塔HTTP、新Milvus集合逐项对照；不调用旧模型。"""
import argparse,hashlib,json,sys,time
from pathlib import Path
from check_product_final_ann import post
sys.path.insert(0,'/tmp/rs-agent-e2e-20261010-llm-opt-20261011')
from probe import accounts,http
ROOT=Path('/mnt/data/luo/remote_runs/product_v16_final')

def main(port=18242,output='actual_java_route_replay.json'):
    records=[]
    for a in accounts()[:8]:
        user=a['profileUserId'];history=http('/internal/users/context/positive-history',{'profile_user_id':user,'limit':80},base='http://127.0.0.1:18201')
        assert len(history)>=2;seen=set(history)
        vector=post('http://172.21.0.1:18138/internal/model/two-tower/user-embedding',
                    {'model_key':'product_three_tower_final_v1','request_id':'pure-java-replay','history_item_ids':history})['embedding']
        value=post('http://127.0.0.1:19530/v2/vectordb/entities/search',{'collectionName':'rs_agent_product_three_tower_final_v1_20261013','data':[vector],
            'annsField':'vector','limit':min(500,400+len(seen)),'outputFields':['item_id'],'searchParams':{'params':{'ef':4096}}})
        assert value['code']==0
        expected=[]
        for row in value['data']:
            iid=str(row.get('item_id',row.get('id')))
            if iid not in seen and iid not in expected:expected.append(iid)
            if len(expected)==400:break
        started=time.monotonic()
        response=post(f'http://127.0.0.1:{port}/internal/recommend/pipeline/recall',{'profile_user_id':user,'session_id':'v15-route-check','limit':400,'sources':['two_tower']})
        actual=[x['item_id'] for x in response['candidates']]
        assert actual==expected,'Java实际召回没有复现新三塔独立顺序'
        assert response['source_distribution']['two_tower']==response['candidate_count']==len(actual)==400
        assert not set(actual)&seen
        records.append({'profile_hash':hashlib.sha256(user.encode()).hexdigest(),'same_order':True,'count':400,
                        'protected_count':0,'main_count':400,'elapsed_ms':(time.monotonic()-started)*1000})
    report={'state':'PASS','port':port,'accounts':len(records),'records':records,'route':'实际Java单模型召回；一个用户塔、一个新索引、历史80过滤、零保护位'}
    (ROOT/output).write_text(json.dumps(report,ensure_ascii=False,indent=2));print('PURE_JAVA_ROUTE_REPLAY',report['state'],len(records),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=18242);p.add_argument('--output',default='actual_java_route_replay.json');args=p.parse_args();main(args.port,args.output)
