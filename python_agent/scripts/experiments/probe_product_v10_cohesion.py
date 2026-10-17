"""开发集验证跨品类离群历史降权；不读封存目标或历史测试指标选择参数。"""
import json,os,types
import numpy as np
import torch
from product_v10_model import SequenceResidualTowers
from train_product_v10 import ROOT,V9,V7,rows,evaluate_rec
from evaluate_product_v7_catalog import save
def forward(self,h,mask):
    lengths=mask.sum(1,keepdim=True)
    pair=h@h.transpose(1,2)
    support=((pair*mask[:,None,:]).sum(2)-1)/(lengths-1).clamp_min(1)
    weights=(support/.15).masked_fill(mask==0,-torch.inf).softmax(1)
    mean=(h*weights[:,:,None]).sum(1)
    return torch.nn.functional.normalize(mean+self.user(mean),dim=-1)
def main():
    assert os.environ.get('CUDA_VISIBLE_DEVICES')=='2'
    torch.set_num_threads(1);torch.cuda.set_per_process_memory_fraction(.10);torch.backends.cuda.matmul.allow_tf32=False
    v=np.load(V7/'candidate_v6_item_vectors.npy',mmap_mode='r')
    model=SequenceResidualTowers(1024,256,len(v),0).cuda().eval();model.load_state_dict(torch.load(V9/'initial.pt',map_location='cpu',weights_only=True)['model'])
    model.encode_user=types.MethodType(forward,model)
    cohorts={'existing_dev':rows(V7/'data/rec_dev.jsonl'),'fresh_dev':rows(V9/'data/fresh_dev.jsonl'),'future_dev':rows(ROOT/'data/future_dev.jsonl')}
    excluded={r['index'] for r in json.loads((V7/'data/text_audit.json').read_text())['ineligible']}
    out=evaluate_rec(model,v,cohorts,excluded)
    save(ROOT/'cohesion_probe.json',{'scope':'只在开发集验证离群历史假设；温度固定0.15；无训练和封存评估','evaluation':out})
    print(json.dumps({k:x['metrics'] for k,x in out.items()}),flush=True)
if __name__=='__main__':main()
