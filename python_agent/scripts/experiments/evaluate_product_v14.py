"""先验证固定头部保护策略，再冻结并打开新的滚动验收；不靠历史目标逐例调参。"""
import argparse,hashlib,json,os,time
from pathlib import Path
import numpy as np
import torch
from three_tower_residual import ResidualTowers,rows,history_tensor,metrics
from product_v10_model import SequenceResidualTowers
from product_v14_guard import legacy_heads,exact_guarded_ranks
from train_product_v10 import evaluate_rec
from evaluate_product_v7_catalog import save

BASE=Path('/mnt/data/luo/remote_runs');ROOT=BASE/'product_v14_training';V7=BASE/'product_v7_expansion';V4=BASE/'three_tower_dataset_v4'

@torch.inference_mode()
def evaluate(cohorts):
    text=np.load(V7/'candidate_v6_item_vectors.npy',mmap_mode='r')
    oldtext=np.load(V4/'export_joint_full_seed42/item_vectors.npy',mmap_mode='r')
    excluded={r['index'] for r in json.loads((V7/'data/text_audit.json').read_text())['ineligible']}
    source=torch.load(BASE/'product_v10_training/initial_cohesion.pt',map_location='cpu',weights_only=True)
    main=SequenceResidualTowers(1024,256,len(text),0,pooling='cohesion').cuda().eval();main.load_state_dict(source['model'])
    old=torch.load(V4/'export_joint_full_seed42/model.pt',map_location='cpu',weights_only=True)
    legacy=ResidualTowers(1024,256,len(oldtext),0).cuda().eval();legacy.load_state_dict(old['model'])
    out={k:{'ranks':[0]*len(v)} for k,v in cohorts.items()};requests=[];targets=[];histories=[];positions=[];old_hist=[]
    for key,records in cohorts.items():
        usable=[]
        for i,r in enumerate(records):
            h=[j for j in r['history_full'] if j not in excluded][-50:]
            if h and r['target']>=0:usable.append((i,{'history':h,'target':r['target']}))
        for s in range(0,len(usable),64):
            part=usable[s:s+64];batch=[r for _,r in part];ids,mask=history_tensor(batch,'cuda')
            hv=torch.tensor(np.asarray(text[ids.cpu().numpy()]),device='cuda');q=main.encode_user(hv,mask)
            requests.extend(q.unbind());targets.extend(r['target'] for r in batch);histories.extend(r['history'] for r in batch)
            old_hist.extend([j for j in r['history'] if j<len(oldtext)] for r in batch);positions.extend((key,i) for i,_ in part)
    head_ids=np.full((len(requests),10),-1,dtype='int64');head_scores=np.full((len(requests),10),-np.inf,dtype='float32')
    known=[i for i,h in enumerate(old_hist) if h]
    oldq=[]
    for s in range(0,len(known),64):
        batch=[{'history':old_hist[i]} for i in known[s:s+64]];h,mask=history_tensor(batch,'cuda')
        hv=torch.tensor(np.asarray(oldtext[h.cpu().numpy()]),device='cuda');oldq.extend(legacy.encode_user(hv,mask).unbind())
    if known:
        ids,scores=legacy_heads(torch.stack(oldq),oldtext,[old_hist[i] for i in known],k=10)
        head_ids[known]=ids;head_scores[known]=scores
    ranked,proof=exact_guarded_ranks(torch.stack(requests),text,targets,histories,head_ids,head_scores,excluded)
    main_out={k:{'ranks':[0]*len(v)} for k,v in cohorts.items()}
    for (key,i),rank,main_rank in zip(positions,ranked,proof['main_ranks']):
        out[key]['ranks'][i]=rank;main_out[key]['ranks'][i]=main_rank
    for container in [out,main_out]:
        for k,v in container.items():v['metrics']=metrics(v['ranks'])
    reference=SequenceResidualTowers(1024,256,len(text),0,pooling='mean').cuda().eval();reference.load_state_dict(old['model'])
    actual=evaluate_rec(reference,oldtext,cohorts,excluded,False)
    expanded=evaluate_rec(reference,np.load(V7/'online_v4_item_vectors.npy',mmap_mode='r'),cohorts,excluded)
    # 上线保护依据所有用户同一固定规则，不可使用目标、封存结果或每用户策略表。
    assert all(v['metrics']['hit@10']>=actual[k]['metrics']['hit@10'] for k,v in out.items())
    return {'candidate':out,'initial':main_out,'online_actual':actual,'online_expanded':expanded,
            'numerical_proof':{'target_score_replay_error':proof['target_score_replay_error'],'legacy_head_count':10}}

def cohorts_for_development():
    paths={'existing_dev':'product_v7_expansion/data/rec_dev.jsonl','fresh_dev':'product_v9_training/data/fresh_dev.jsonl',
           'future_short_dev':'product_v10_training/data/future_dev.jsonl','future_snapshot_dev':'product_v12_training/data/future_dev.jsonl',
           'future_rolling_dev':'product_v13_training/data/future_dev.jsonl','future_dev':'product_v14_training/data/future_dev.jsonl'}
    return {k:rows(BASE/p) for k,p in paths.items()}

def checks(e,strict=False):
    result={}
    for k,value in e['candidate'].items():
        c=value['metrics'];a=e['online_actual'][k]['metrics'];b=e['online_expanded'][k]['metrics']
        result[k]={'mrr_vs_actual':c['mrr']>=a['mrr']*(1 if strict else .95),
                   'head_hit10_vs_actual':c['hit@10']>=a['hit@10'],
                   'hit100_vs_actual':c['hit@100']>=a['hit@100'],
                   'hit100_vs_same_catalog':c['hit@100']>=b['hit@100']}
        if strict:result[k]['mrr_vs_same_catalog']=c['mrr']>=b['mrr']
    return result

def main(stage):
    assert os.environ.get('CUDA_VISIBLE_DEVICES')=='2'
    torch.set_num_threads(2);torch.set_num_interop_threads(1);torch.cuda.set_per_process_memory_fraction(.20);torch.backends.cuda.matmul.allow_tf32=False
    if stage=='development':
        assert not (ROOT/'selection.json').exists()
        policy={'state':'FIXED_BEFORE_DEVELOPMENT','main_checkpoint':str(BASE/'product_v10_training/initial_cohesion.pt'),
                'main_catalog_count':763080,'legacy_count':203887,'legacy_head_count':10,
                'route':'固定10个现网未看过头部候选，其余均来自扩库三塔，按ID去重，查询仍走三塔。主体预算约260/270由新三塔提供。不是新单模型胜过现网的声明。',
                'dev_gate':'六开发群体MRR>=实际旧库95%；Hit10不退；Hit100>=实际旧库与同扩库现网。',
                'final_gate':'历史MRR>=实际旧库95%，历史Hit10/100不退；新3000滚动封存MRR和Hit100>=实际旧库及同扩库现网，Hit10不退。工程另验收。',
                'timestamp':time.time(),'online_modified':False}
        save(ROOT/'experiment_policy.json',policy)
        ev=evaluate(cohorts_for_development());gate=checks(ev);passed=all(all(v.values()) for v in gate.values())
        save(ROOT/'development.json',{'state':'PASS' if passed else 'FAIL','models':ev,'checks':gate})
        print('GUARDED_DEVELOPMENT',passed,gate,flush=True)
        for k,v in ev['candidate'].items():print(k,v['metrics'],flush=True)
    elif stage=='freeze':
        dev=json.loads((ROOT/'development.json').read_text());assert dev['state']=='PASS','开发未通过，不打开封存'
        assert not (ROOT/'selection.json').exists()
        policy=json.loads((ROOT/'experiment_policy.json').read_text())
        checkpoint=Path(policy['main_checkpoint']);save(ROOT/'selection.json',{'state':'FROZEN','selected':'cohesion_with_legacy_head10',
            'checkpoint':str(checkpoint),'model_sha256':hashlib.sha256(checkpoint.read_bytes()).hexdigest(),
            'guarded_head_count':10,'development':dev['models']['candidate'],'rule':policy,'timestamp':time.time()})
        ev=evaluate({'sealed_future':rows(ROOT/'data/sealed_future.jsonl')});gate=checks(ev,strict=True)
        save(ROOT/'results.json',{'state':'COMPLETE','selected':'cohesion_with_legacy_head10','sealed':ev,'sealed_checks':gate,
                                 'sealed_state':'PASS' if all(all(x.values()) for x in gate.values()) else 'FAIL'})
        print('GUARDED_SEALED',gate,flush=True)
        for k,e in ev.items():
            if k!='numerical_proof':print(k,e['sealed_future']['metrics'],flush=True)

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['development','freeze']);main(p.parse_args().stage)
