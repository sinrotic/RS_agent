"""分解既有MRR回归；仅开发集试验聚合策略，历史测试只作已见诊断。"""
import json,os,sys,time
from pathlib import Path
import numpy as np
import torch
import torch.nn.functional as F
from three_tower_residual import ResidualTowers,metrics,rows
from evaluate_product_v7_catalog import exact_ranks,save

ROOT=Path('/mnt/data/luo/remote_runs/product_v10_training')
V9=ROOT.parent/'product_v9_training'
V7=ROOT.parent/'product_v7_expansion'
V4=ROOT.parent/'three_tower_dataset_v4'

def rr(ranks):
    x=np.asarray(ranks,dtype=float);return np.divide(1,x,out=np.zeros_like(x),where=x>0)

def cached_diagnosis():
    d=json.loads((V9/'final_validation.json').read_text());v=d['models']
    arrays={'actual':v['online_actual']['test/old_catalog']['ranks'],
        'online_fixed':v['online_expanded']['test/expanded_fixed_history']['ranks'],
        'online_full':v['online_expanded']['test/expanded_full_history']['ranks'],
        'candidate_fixed':v['candidate']['test/expanded_fixed_history']['ranks'],
        'candidate_full':v['candidate']['test/expanded_full_history']['ranks']}
    original=rows(V4/'final_test/confirmation_rows.jsonl');assert len(original)==len(arrays['actual'])
    out={'scope':'既有历史测试已开封，只作诊断，不用于聚合超参数选择','decomposition':{},'groups':{}}
    for name,a,b in [('expansion','actual','online_fixed'),('online_history','online_fixed','online_full'),
                     ('weights_fixed_history','online_fixed','candidate_fixed'),('candidate_history','candidate_fixed','candidate_full')]:
        delta=rr(arrays[b])-rr(arrays[a]);indexes=np.argsort(delta)[:12]
        out['decomposition'][name]={'mrr_delta':float(delta.mean()),'worst':[{'row':int(i),'before':arrays[a][i],'after':arrays[b][i],'rr_delta':float(delta[i])} for i in indexes]}
    groups={'history_1_3':[i for i,r in enumerate(original) if len(r['history'])<=3],
            'history_4_10':[i for i,r in enumerate(original) if 4<=len(r['history'])<=10],
            'history_11_50':[i for i,r in enumerate(original) if len(r['history'])>10],
            'old_target':[i for i,r in enumerate(original) if r['target']>=0],
            'new_or_uncovered_target':[i for i,r in enumerate(original) if r['target']<0]}
    for key,ix in groups.items():
        if ix:out['groups'][key]={k:metrics(np.asarray(a)[ix].tolist()) for k,a in arrays.items()}
    delta=rr(arrays['candidate_full'])-rr(arrays['actual']);rng=np.random.default_rng(20261011)
    boot=[float(rng.choice(delta,len(delta),replace=True).mean()) for _ in range(2000)]
    out['mrr_paired_delta']={'mean':float(delta.mean()),'ci95':np.quantile(boot,[.025,.975]).tolist(),'selection_adjusted':False}
    save(ROOT/'diagnosis.json',out);print(json.dumps(out['decomposition']),flush=True)

@torch.inference_mode()
def probe():
    assert os.environ.get('CUDA_VISIBLE_DEVICES')=='2'
    torch.set_num_threads(2);torch.set_num_interop_threads(1);torch.cuda.set_per_process_memory_fraction(.20)
    torch.backends.cuda.matmul.allow_tf32=False
    vectors=np.load(V7/'candidate_v6_item_vectors.npy',mmap_mode='r')
    model=ResidualTowers(1024,256,len(vectors),0).cuda().eval()
    model.load_state_dict(torch.load(V9/'initial.pt',map_location='cpu',weights_only=True)['model'])
    excluded={r['index'] for r in json.loads((V7/'data/text_audit.json').read_text())['ineligible']}
    cohorts={'existing_dev':rows(V7/'data/rec_dev.jsonl'),'fresh_dev':rows(V9/'data/fresh_dev.jsonl')}
    out={'scope':'仅已有两个开发集；不读v9封存用户或历史测试选择聚合策略','variants':{}}
    for name in ['mean','last3','last10','decay08','blend_recent']:
        qs=[];targets=[];histories=[];positions=[];ranks={k:[0]*len(v) for k,v in cohorts.items()}
        for key,records in cohorts.items():
            for i,r in enumerate(records):
                history=[x for x in r['history_full'] if x not in excluded][-50:]
                if not history or r['target']<0:continue
                assert r['target'] not in history
                h=torch.tensor(np.asarray(vectors[history]),device='cuda')
                if name=='last3':mean=h[-3:].mean(0)
                elif name=='last10':mean=h[-10:].mean(0)
                elif name=='decay08':
                    weights=.8**torch.arange(len(h)-1,-1,-1,device='cuda');mean=(h*weights[:,None]).sum(0)/weights.sum()
                elif name=='blend_recent':mean=.75*h.mean(0)+.25*h[-3:].mean(0)
                else:mean=h.mean(0)
                q=F.normalize(mean+model.user(mean),dim=-1)
                qs.append(q);targets.append(r['target']);histories.append(history);positions.append((key,i))
        found,_=exact_ranks(torch.stack(qs),vectors,targets,histories,excluded=excluded)
        for (key,i),rank in zip(positions,found):ranks[key][i]=rank
        out['variants'][name]={k:{'metrics':metrics(x),'ranks':x} for k,x in ranks.items()}
        save(ROOT/'pooling_probe.json',out);print('POOL',name,{k:x['metrics'] for k,x in out['variants'][name].items()},flush=True)

if __name__=='__main__':
    ROOT.mkdir(exist_ok=True);cached_diagnosis();probe()
