"""固定商品/查询，交叉检查用户塔版本与聚合；仅开发，不读取新封存。"""
import os,json
from pathlib import Path
import numpy as np
import torch
from three_tower_residual import rows
from product_v10_model import SequenceResidualTowers
from train_product_v10 import evaluate_rec
from evaluate_product_v7_catalog import save
BASE=Path('/mnt/data/luo/remote_runs');ROOT=BASE/'product_v12_training'

def main():
    assert os.environ.get('CUDA_VISIBLE_DEVICES')=='2'
    torch.set_num_threads(2);torch.set_num_interop_threads(1);torch.cuda.set_per_process_memory_fraction(.2)
    torch.backends.cuda.matmul.allow_tf32=False
    vectors=np.load(BASE/'product_v7_expansion/candidate_v6_item_vectors.npy',mmap_mode='r')
    excluded={r['index'] for r in json.loads((BASE/'product_v7_expansion/data/text_audit.json').read_text())['ineligible']}
    cohorts={'existing_dev':rows(BASE/'product_v7_expansion/data/rec_dev.jsonl'),
             'fresh_dev':rows(BASE/'product_v9_training/data/fresh_dev.jsonl'),
             'future_short_dev':rows(BASE/'product_v10_training/data/future_dev.jsonl'),
             'future_dev':rows(ROOT/'data/future_dev.jsonl')}
    candidate=torch.load(BASE/'product_v9_training/initial.pt',map_location='cpu',weights_only=True)
    old=torch.load(BASE/'three_tower_dataset_v4/export_joint_full_seed42/model.pt',map_location='cpu',weights_only=True)
    model=SequenceResidualTowers(1024,256,len(vectors),0).cuda().eval()
    result={'state':'RUNNING','scope':'只使用开发集，固定v6商品与v8查询；用户MLP版本和序列聚合正交对照','variants':{}}
    for name,alpha,pooling in [('v6_mean',1.,'mean'),('v6_cohesion',1.,'cohesion'),
                               ('v4_mean',0.,'mean'),('v4_cohesion',0.,'cohesion'),
                               ('blend_cohesion',.5,'cohesion')]:
        state={k:v.clone() for k,v in candidate['model'].items()}
        for k in state:
            if k.startswith('user.'):state[k]=alpha*state[k]+(1-alpha)*old['model'][k]
        model.load_state_dict(state);model.pooling=pooling
        ev=evaluate_rec(model,vectors,cohorts,excluded)
        path=ROOT/(name+'.pt');torch.save({'model':state,'config':{**candidate['config'],'pooling':pooling}},path)
        result['variants'][name]={'checkpoint':str(path),'evaluation':ev}
        save(ROOT/'probe.json',result)
        print('V12_PROBE',name,{k:v['metrics'] for k,v in ev.items()},flush=True)
    result['state']='COMPLETE';save(ROOT/'probe.json',result)

if __name__=='__main__':main()
