"""按Java实际默认Milvus REST参数验证ANN；检查HTTP模型契约和并发延迟。"""
import argparse,concurrent.futures,json,os,time,urllib.request,urllib.error
from pathlib import Path
import numpy as np
import torch
import torch.nn.functional as F
ROOT=Path('/mnt/data/luo/remote_runs/product_v14_training')
V7=Path('/mnt/data/luo/remote_runs/product_v7_expansion')
V4=Path('/mnt/data/luo/remote_runs/three_tower_dataset_v4')
MODEL='product_three_tower_v14_expanded'

def post(url,payload):
    request=urllib.request.Request(url,data=json.dumps(payload).encode(),headers={'Content-Type':'application/json'})
    with urllib.request.urlopen(request,timeout=30) as f:return json.load(f)

def main(ef=0):
    assert os.environ.get('CUDA_VISIBLE_DEVICES')=='2'
    torch.set_num_threads(2);torch.cuda.set_per_process_memory_fraction(.20);torch.backends.cuda.matmul.allow_tf32=False
    ids=[json.loads(l)['item_id'] for l in (ROOT/'export/item_ids.jsonl').open()]
    rows=[json.loads(l) for l in (V7/'data/full_history_replay.jsonl').open()][:64]
    q=F.normalize(torch.tensor(np.load(V4/'data/query_features.npy')[:64]),dim=-1).numpy()
    base='http://172.21.0.1:18132/internal/model/'
    payloads=[(base+'two-tower/user-embedding',{'model_key':MODEL,'request_id':'v9-ann','history_item_ids':[ids[i] for i in reversed(r['history'])]}) for r in rows]
    payloads += [(base+'product/query-embedding',{'model_key':MODEL,'embedding':v.tolist()}) for v in q]
    def invoke(args):
        start=time.monotonic();result=post(*args)
        assert result['model_key']==MODEL and len(result['embedding'])==1024
        return result['embedding'],(time.monotonic()-start)*1000
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as executor:responses=list(executor.map(invoke,payloads))
    requests=torch.tensor([v[0] for v in responses],device='cuda')
    assert bool(torch.isfinite(requests).all()) and bool((requests.norm(dim=-1)-1).abs().max()<1e-4)
    vectors=np.load(ROOT/'export/item_vectors.npy',mmap_mode='r')
    best_scores=torch.empty(len(requests),0,device='cuda');best_ids=torch.empty(len(requests),0,device='cuda',dtype=torch.long)
    with torch.inference_mode():
        for start in range(0,len(vectors),4096):
            block=torch.tensor(np.asarray(vectors[start:start+4096]),device='cuda');scores=requests@block.T
            values,indices=scores.topk(min(100,len(block)),dim=1);indices+=start
            all_scores=torch.cat([best_scores,values],1);all_ids=torch.cat([best_ids,indices],1)
            best_scores,order=all_scores.topk(min(100,all_scores.shape[1]),dim=1);best_ids=all_ids.gather(1,order)
    exact=[{ids[i] for i in row} for row in best_ids.cpu().tolist()]
    recall=[];timings=[]
    for i,query in enumerate(requests.cpu().tolist()):
        begin=time.monotonic()
        payload={'collectionName':'rs_agent_product_three_tower_v14_20261012','data':[query],'annsField':'vector','limit':100,'outputFields':['item_id']}
        if ef:payload['searchParams']={'params':{'ef':max(ef,100)}}
        result=post('http://127.0.0.1:19530/v2/vectordb/entities/search',payload)
        timings.append((time.monotonic()-begin)*1000);assert result['code']==0 and len(result['data'])==100
        returned={str(v.get('item_id',v.get('id'))) for v in result['data']};recall.append(len(returned&exact[i])/100)
    rejected=0
    for path,payload in [(base+'product/query-embedding',{'model_key':'wrong','embedding':q[0].tolist()}),
                         (base+'product/query-embedding',{'model_key':MODEL,'embedding':[0.]*1024}),
                         (base+'product/query-embedding',{'model_key':MODEL,'embedding':[1.]*4})]:
        try:post(path,payload)
        except urllib.error.HTTPError as e:assert e.code==400;rejected+=1
    cold=post(base+'two-tower/user-embedding',{'model_key':MODEL,'request_id':'cold','history_item_ids':['__unknown_v9__']})
    assert rejected==3 and cold['embedding']==[]
    result={'state':'PASS' if np.mean(recall)>=.95 and min(recall)>=.80 else 'FAIL','queries':len(recall),
        'ann_overlap_at100_mean':float(np.mean(recall)),'ann_overlap_at100_min':min(recall),'ann_overlap_at100_each':recall,
        'user_overlap_mean':float(np.mean(recall[:64])),'query_overlap_mean':float(np.mean(recall[64:])),
        'milvus_rest_p95_ms':float(np.quantile(timings,.95)),'runtime_http_concurrency8_p95_ms':float(np.quantile([v[1] for v in responses],.95)),
        'invalid_query_rejected':rejected,'unknown_history_fallback':True,'ef':ef,'search_parameters':'limit100；ef=0时为Java现有默认参数，非零为待验证配置；仅评估ANN检索精度，不评估业务相关性'}
    name='ann_verification.json'
    (ROOT/name).write_text(json.dumps(result,ensure_ascii=False,indent=2));print(json.dumps({k:v for k,v in result.items() if k!='ann_overlap_at100_each'},ensure_ascii=False),flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--ef',type=int,default=1024);args=p.parse_args();main(args.ef)

