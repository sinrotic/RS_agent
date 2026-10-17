"""只诊断已见历史头部样本的近邻竞争与同文本，不参与新封存选型。"""
import hashlib,json,os
from pathlib import Path
import numpy as np
import torch
from three_tower_residual import ResidualTowers,rows
from evaluate_product_v7_catalog import save
ROOT=Path('/mnt/data/luo/remote_runs/product_v10_training');V9=ROOT.parent/'product_v9_training';V7=ROOT.parent/'product_v7_expansion';V4=ROOT.parent/'three_tower_dataset_v4'
def main():
    assert os.environ.get('CUDA_VISIBLE_DEVICES')=='2'
    torch.set_num_threads(1);torch.cuda.set_per_process_memory_fraction(.12)
    torch.backends.cuda.matmul.allow_tf32=False
    d=json.loads((V9/'final_validation.json').read_text());a=d['models']['online_actual']['test/old_catalog']['ranks'];b=d['models']['candidate']['test/expanded_full_history']['ranks']
    chosen=sorted([i for i,v in enumerate(a) if 0<v<=10],key=lambda i:(1/b[i] if b[i] else 0)-1/a[i])[:12]
    catalog=rows(V7/'data/items.jsonl');mapping={r['item_id']:r['index'] for r in catalog}
    extra=json.loads((V4/'final_test/extra_history_ids.json').read_text());original=rows(V4/'final_test/confirmation_rows.jsonl')
    ids=[r['item_id'] for r in catalog[:203887]]+extra
    vectors=np.load(V7/'candidate_v6_item_vectors.npy',mmap_mode='r')
    model=ResidualTowers(1024,256,len(vectors),0).cuda().eval();model.load_state_dict(torch.load(V9/'initial.pt',map_location='cpu',weights_only=True)['model'])
    requests=[];histories=[]
    with torch.inference_mode():
        for i in chosen:
            h=[mapping[ids[j]] for j in original[i]['history']];histories.append(h)
            mean=torch.tensor(np.asarray(vectors[h]),device='cuda').mean(0)
            requests.append(torch.nn.functional.normalize(mean+model.user(mean),dim=-1))
        q=torch.stack(requests);values=torch.full((len(chosen),30),-torch.inf,device='cuda');indexes=torch.zeros((len(chosen),30),device='cuda',dtype=torch.long)
        for start in range(0,len(vectors),8192):
            scores=q@torch.tensor(np.asarray(vectors[start:start+8192]),device='cuda').T
            for j,h in enumerate(histories):
                cols=[x-start for x in h if start<=x<start+scores.shape[1]];scores[j,cols]=-torch.inf
            val,ix=scores.topk(30,dim=1);ix=ix+start
            merged=torch.cat([values,val],1);mi=torch.cat([indexes,ix],1);values,order=merged.topk(30,dim=1);indexes=mi.gather(1,order)
        out=[]
        for row,i in enumerate(chosen):
            target=original[i]['target'];assert target>=0
            text=catalog[target]['text'].strip();fp=hashlib.sha256(text.encode()).hexdigest()
            matches=sum(hashlib.sha256(r['text'].strip().encode()).hexdigest()==fp for r in catalog)
            neighbors=[]
            for ix,score in zip(indexes[row].cpu().tolist(),values[row].cpu().tolist()):
                neighbors.append({'index':ix,'new_catalog_item':ix>=203887,'score':score,'cosine_to_target':float(vectors[ix]@vectors[target]),'same_text':catalog[ix]['text'].strip()==text,'text':catalog[ix]['text'][:240]})
            out.append({'row':i,'old_rank':a[i],'new_rank':b[i],'history_length':len(histories[row]),'target_index':target,'target_text':text[:240],'catalog_same_text_count':matches,'neighbors':neighbors})
    save(ROOT/'head_competition.json',{'scope':'已见历史失败样本，诊断用，非独立验证','samples':out})
    print(json.dumps([{k:v for k,v in x.items() if k not in ['neighbors','target_text']} for x in out]),flush=True)
if __name__=='__main__':main()
