"""只验收冻结的整轮三塔；历史与语义是已用回归集，新封存为未见未来事件。"""
import hashlib,json,os,time
from pathlib import Path
import numpy as np
import torch
import torch.nn.functional as F
from three_tower_residual import rows,metrics
from prepare_product_v12 import stream,SOURCE
from product_v10_model import SequenceResidualTowers
from train_product_v10 import evaluate_rec
from evaluate_product_v14 import evaluate as evaluate_current
from evaluate_product_v7_catalog import exact_ranks,save
BASE=Path('/mnt/data/luo/remote_runs');ROOT=BASE/'product_v15_training';V7=BASE/'product_v7_expansion';V4=BASE/'three_tower_dataset_v4'

def historical():
    item_ids=[r['item_id'] for r in stream(V7/'data/items.jsonl')];mapping={s:i for i,s in enumerate(item_ids)}
    original_ids=item_ids[:203887]+json.loads((V4/'final_test/extra_history_ids.json').read_text())
    original=list(stream(V4/'final_test/confirmation_rows.jsonl'));users={r['user_hash'] for r in original};targets={}
    for r in stream(SOURCE/'canonical_interactions.test.jsonl'):
        if r['label_binary']!=1:continue
        uid=hashlib.sha256(r['user_id'].encode()).hexdigest()
        if uid not in users:continue
        value=(r['timestamp'],r['parent_asin'])
        if uid not in targets or value<targets[uid]:targets[uid]=value
    cohort=[]
    for r in original:
        t,iid=targets[r['user_hash']];assert t==r['target_ts']
        cohort.append({'user_hash':r['user_hash'],'old_target':r['target'],'target':mapping.get(iid,-1),
                      'history_old':[i for i in r['history'] if i<203887],
                      'history_full':[mapping[original_ids[i]] for i in r['history']]})
    return cohort

@torch.inference_mode()
def semantic(model,vectors,excluded):
    records=rows(V4/'data/semantic_test.jsonl');q=F.normalize(torch.tensor(np.load(BASE/'product_v11_training/semantic_test_query_features.npy'),device='cuda'),dim=-1)
    assert len(q)==len(records)==344
    requests=torch.cat([model.encode_query(q[s:s+64]) for s in range(0,len(q),64)])
    ranks,error=exact_ranks(requests,vectors,[r['item_index'] for r in records],[[] for r in records],excluded=excluded)
    return {'metrics':metrics(ranks),'ranks':ranks,'target_score_replay_error':error}

def main():
    assert os.environ.get('CUDA_VISIBLE_DEVICES')=='1'
    torch.set_num_threads(2);torch.set_num_interop_threads(1);torch.cuda.set_per_process_memory_fraction(.2);torch.backends.cuda.matmul.allow_tf32=False
    assert not (ROOT/'final_validation.json').exists(),'冻结检查点只验收一次'
    selection=json.loads((ROOT/'selection.json').read_text());result=json.loads((ROOT/'results.json').read_text())
    assert selection['state']=='FROZEN' and result['state']=='COMPLETE'
    audit=json.loads((ROOT/'trained_tower_audit.json').read_text());assert audit['state']=='PASS' and all(audit['changed_towers'].values())
    metadata=json.loads((ROOT/'data/manifest.json').read_text());seal=ROOT/'data/sealed_future.jsonl'
    integrity=(ROOT/'data/sealed_snapshot_ready.json').stat().st_mtime<selection['timestamp'] and hashlib.sha256(seal.read_bytes()).hexdigest()==metadata['sealed_sha256']
    cohorts={'historical':historical(),'sealed_future':rows(seal)};assert len(cohorts['sealed_future'])==metadata['sealed_count']
    excluded={r['index'] for r in json.loads((V7/'data/text_audit.json').read_text())['ineligible']}
    # 逐群体复评，使封存对照与训练后首次复评使用同样的GEMM形状。
    # 极近分数可能随请求矩阵形状产生FP32排名差异，不混合历史与封存请求。
    current={}
    for key,cohort in cohorts.items():
        evaluated=evaluate_current({key:cohort})
        for name in ['candidate','initial','online_actual','online_expanded']:
            current.setdefault(name,{})[key]=evaluated[name][key]
    state=torch.load(selection['checkpoint'],map_location='cpu',weights_only=True)
    model=SequenceResidualTowers(1024,256,763086,0,pooling='cohesion').cuda().eval();model.load_state_dict(state['model'])
    vectors=np.load(selection['vectors'],mmap_mode='r');candidate=evaluate_rec(model,vectors,{'historical':cohorts['historical']},excluded)
    candidate['sealed_future']=result['sealed']['candidate']['sealed_future'];candidate_sem=semantic(model,vectors,excluded)
    initial_vectors=np.load(V7/'candidate_v6_item_vectors.npy',mmap_mode='r');initial=torch.load(BASE/'product_v14_training/export/model.pt',map_location='cpu',weights_only=True)
    model.load_state_dict(initial['model']);initial_sem=semantic(model,initial_vectors,excluded)
    # 对照起始纯三塔，现网带保护和老小词表只是报告对照，不恢复18人的旧保护门槛。
    baseline=current['initial'];s=candidate['sealed_future']['metrics'];b=baseline['sealed_future']['metrics'];h=candidate['historical']['metrics'];hb=baseline['historical']['metrics']
    expected_initial=result['sealed']['initial']['sealed_future']['metrics']
    assert all(abs(b[k]-expected_initial[k])<1e-12 for k in ['mrr','hit@10','hit@100'])
    policy=json.loads((ROOT/'verification_policy.json').read_text())
    assert policy['timestamp']<selection['timestamp'],'工程/语义回归策略必须冻结在新封存之前'
    checks={'sealed_integrity':integrity,'all_three_towers_trained':all(audit['changed_towers'].values()),
            'three_whole_epochs':len(result['epochs'])==3 and all(e['full_dataset_coverage']==1. for e in result['epochs']),
            'sealed_mrr_vs_pure':s['mrr']>=.95*b['mrr'],'sealed_hit10_vs_pure':s['hit@10']>=.9*b['hit@10'],
            'sealed_hit100_vs_pure':s['hit@100']>=.98*b['hit@100'],
            'historical_mrr_vs_pure':h['mrr']>=.95*hb['mrr'],'historical_head_vs_pure':round(h['hit@10']*h['count'])>=round(hb['hit@10']*hb['count']),
            'semantic_hit10':round(candidate_sem['metrics']['hit@10']*344)>=round(initial_sem['metrics']['hit@10']*344)-policy['semantic_max_lost_queries']}
    out={'state':'PASS' if all(checks.values()) else 'FAIL','checks':checks,'candidate':candidate,'initial_pure':baseline,
         'current_guarded':current['candidate'],'old_small_catalog':current['online_actual'],
         'semantic':{'candidate':candidate_sem,'initial_pure':initial_sem},'selected_epoch':selection['epoch'],
         'policy':json.loads((ROOT/'experiment_plan.json').read_text())['release_policy'],'timestamp':time.time(),
         'selection_correction':selection.get('selection_correction'),
         'limitations':'历史1632和语义344已经多轮使用。1890封存为评论评分序列未来事件，用户训练前缀可能已参与训练。若selection_correction非空，原epoch3曾计算封存，开发规则数值纠错后为同封存重放，不是全新独立第二封存；不代表购买转化或线上收益。'}
    save(ROOT/'final_validation.json',out);print('V15_FROZEN_VALIDATION',out['state'],checks,flush=True)
    for name in ['candidate','initial_pure','current_guarded','old_small_catalog']:
        print(name,{k:v['metrics'] for k,v in out[name].items()},flush=True)

if __name__=='__main__':main()
