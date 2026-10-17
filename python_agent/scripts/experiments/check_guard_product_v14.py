"""真实旧/新运行时和Milvus返回顺序的保护路线验证；不使用离线预计算用户向量。"""
import json,os,time
from pathlib import Path
import numpy as np
import torch
from check_product_v14_ann import post
from product_v14_guard import legacy_heads
ROOT=Path('/mnt/data/luo/remote_runs/product_v14_training');BASE=ROOT.parent

def main():
    assert os.environ.get('CUDA_VISIBLE_DEVICES')=='2'
    torch.set_num_threads(2);torch.cuda.set_per_process_memory_fraction(.2);torch.backends.cuda.matmul.allow_tf32=False
    ids=[json.loads(l)['item_id'] for l in (ROOT/'export/item_ids.jsonl').open()]
    oldids=ids[:203887];lookup={s:i for i,s in enumerate(oldids)}
    records=[json.loads(l) for l in (BASE/'product_v7_expansion/data/full_history_replay.jsonl').open()][:64]
    q=[];histories=[];returned=[];merged_counts=[];latencies=[]
    for r in records:
        history=[ids[i] for i in reversed(r['history'])][:50];seen=set(history);start=time.monotonic()
        main=post('http://172.21.0.1:18132/internal/model/two-tower/user-embedding',
                  {'model_key':'product_three_tower_v14_expanded','request_id':'guard-main','history_item_ids':history})
        legacy=post('http://172.21.0.1:18120/internal/model/two-tower/user-embedding',
                    {'model_key':'product_three_tower_v4_seed42_step6000','request_id':'guard-legacy','history_item_ids':history})
        assert len(main['embedding'])==1024
        def search(collection,vector,limit):
            value=post('http://127.0.0.1:19530/v2/vectordb/entities/search',{'collectionName':collection,'data':[vector],
                'annsField':'vector','limit':limit,'outputFields':['item_id'],'searchParams':{'params':{'ef':4096}}})
            assert value['code']==0
            return [str(x.get('item_id',x.get('id'))) for x in value['data']]
        newhits=search('rs_agent_product_three_tower_v14_20261012',main['embedding'],490)
        oldhits=search('rs_agent_product_three_tower_v4_20261011',legacy['embedding'],90) if legacy['embedding'] else []
        protected=[]
        for x in oldhits:
            if x not in seen and x not in protected:protected.append(x)
            if len(protected)==10:break
        combined=protected.copy()
        for x in newhits:
            if len(combined)==400:break
            if x not in seen and x not in combined:combined.append(x)
        assert len(combined)==len(set(combined))==400 and not seen&set(combined)
        assert combined[:len(protected)]==protected
        merged_counts.append({'protected':len(protected),'main':400-len(protected)})
        if legacy['embedding']:
            q.append(legacy['embedding']);histories.append([lookup[s] for s in history if s in lookup]);returned.append(set(protected))
        latencies.append((time.monotonic()-start)*1000)
    oldvec=np.load(BASE/'three_tower_dataset_v4/export_joint_full_seed42/item_vectors.npy',mmap_mode='r')
    exact,_=legacy_heads(torch.tensor(q,device='cuda'),oldvec,histories,k=10)
    overlaps=[len({oldids[i] for i in row}&found)/10 for row,found in zip(exact,returned)]
    report={'state':'PASS' if np.mean(overlaps)>=.95 and min(overlaps)>=.8 else 'FAIL','queries':len(overlaps),
            'guard_overlap_at10_mean':float(np.mean(overlaps)),'guard_overlap_at10_min':min(overlaps),
            'protected_and_main_counts':merged_counts,'route_http_p95_ms':float(np.quantile(latencies,.95)),
            'space_scores_never_compared':True,'ef':4096,
            'scope':'两运行时HTTP、两个集合真实REST检索与同一保护/去重规则；Java实际bean与双HTTP依赖由集成单测验证。'}
    (ROOT/'guard_ann_verification.json').write_text(json.dumps(report,ensure_ascii=False,indent=2));print('GUARD_ROUTE_ANN',report['state'],report['guard_overlap_at10_mean'],report['guard_overlap_at10_min'])

if __name__=='__main__':main()
