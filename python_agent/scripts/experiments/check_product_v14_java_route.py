"""实际Java召回接口与两个HTTP模型/两个Milvus查询的逐项顺序对照。"""
import argparse,hashlib,json,sys,time
from pathlib import Path
from check_product_v14_ann import post
sys.path.insert(0,'/tmp/rs-agent-e2e-20261010-llm-opt-20261011')
from probe import accounts,http
ROOT=Path('/mnt/data/luo/remote_runs/product_v14_training')

def main(port=18238,output='actual_java_route_replay.json'):
    records=[]
    for a in accounts()[:8]:
        user=a['profileUserId'];history=http('/internal/users/context/positive-history',{'profile_user_id':user,'limit':80},base='http://127.0.0.1:18201')
        assert len(history)>=2
        seen=set(history)
        def infer(port,key):
            return post(f'http://172.21.0.1:{port}/internal/model/two-tower/user-embedding',
                        {'model_key':key,'request_id':'actual-java-replay','history_item_ids':history})['embedding']
        main=infer(18132,'product_three_tower_v14_expanded');legacy=infer(18120,'product_three_tower_v4_seed42_step6000')
        def search(collection,vector,limit):
            value=post('http://127.0.0.1:19530/v2/vectordb/entities/search',{'collectionName':collection,'data':[vector],
                'annsField':'vector','limit':limit,'outputFields':['item_id'],'searchParams':{'params':{'ef':4096}}})
            assert value['code']==0
            return [str(x.get('item_id',x.get('id'))) for x in value['data']]
        newer=search('rs_agent_product_three_tower_v14_20261012',main,min(500,400+len(seen)+10))
        older=search('rs_agent_product_three_tower_v4_20261011',legacy,min(500,10+len(seen))) if legacy else []
        expected=[]
        for x in older:
            if x not in seen and x not in expected:expected.append(x)
            if len(expected)==10:break
        protected=len(expected)
        for x in newer:
            if len(expected)>=400:break
            if x not in seen and x not in expected:expected.append(x)
        start=time.monotonic()
        value=post(f'http://127.0.0.1:{port}/internal/recommend/pipeline/recall',{'profile_user_id':user,'session_id':'v14-route-check','limit':400,'sources':['two_tower']})
        actual=[x['item_id'] for x in value['candidates']]
        assert actual==expected,'实际Java装配未复现冻结保护路线'
        assert value['source_distribution']['two_tower']==value['candidate_count']==len(actual)==400
        records.append({'profile_hash':hashlib.sha256(user.encode()).hexdigest(),'same_order':True,'count':len(actual),
                        'protected_count':protected,'main_count':len(actual)-protected,'elapsed_ms':(time.monotonic()-start)*1000})
    report={'state':'PASS','port':port,'accounts':len(records),'records':records,'route':'实际部署jar的InternalRecommendPipelineController到TwoTowerRecallProvider，非本地合并模拟'}
    (ROOT/output).write_text(json.dumps(report,ensure_ascii=False,indent=2));print('ACTUAL_JAVA_ROUTE_REPLAY',report['state'],len(records))

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=18238);p.add_argument('--output',default='actual_java_route_replay.json');args=p.parse_args()
    main(args.port,args.output)
