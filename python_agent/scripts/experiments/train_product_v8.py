"""扩库后固定商品塔，分阶段训练用户/查询塔；开发选型、断点保存、显存限额。"""
import hashlib,json,os,random,time,urllib.request
from pathlib import Path
import numpy as np
import torch
import torch.nn.functional as F
from three_tower_residual import ResidualTowers,history_tensor,rows
from product_recall_v5 import candidate_ids,epoch_indices
from evaluate_product_v7_catalog import build_requests,exact_ranks,summarize,save

ROOT=Path('/mnt/data/luo/remote_runs/product_v8_training')
V7=Path('/mnt/data/luo/remote_runs/product_v7_expansion')
OLD=Path('/mnt/data/luo/remote_runs/three_tower_dataset_v4/data')

def health():
    for url in ['http://127.0.0.1:18213/actuator/health/readiness','http://172.21.0.1:18120/health']:
        with urllib.request.urlopen(url,timeout=5) as response:
            assert json.load(response)['status']=='UP'

def negatives(batch,rng,count,excluded,fingerprints,pool):
    enriched=[]
    for r in batch:
        enriched.append({**r,'known_train_positives':list(set(r['known_train_positives'])|excluded)})
    ids=np.asarray(candidate_ids(enriched,rng,count,pool,'random'))
    # 同文本不同商品不作为明确负例；重新采样仍同时排除已知正例。
    for k,r in enumerate(enriched):
        blocked=set(r['known_train_positives'])|set(ids[k]);target_fp=fingerprints[r['target']]
        for j in range(1,ids.shape[1]):
            if fingerprints[ids[k,j]]==target_fp:
                while True:
                    v=rng.randrange(count)
                    if v not in blocked and fingerprints[v]!=target_fp:break
                ids[k,j]=v;blocked.add(v)
    return ids

def sampled_loss(request,items,hard):
    scores=torch.einsum('bd,bnd->bn',request,items)/.07
    if hard:
        # 保留96随机负例，再取31个低于正例分数的较难负例；不强推疑似相关的最难项。
        tail=scores[:,97:]
        eligible=tail.detach() < scores[:,:1].detach()-.02/.07
        choices=tail.detach().masked_fill(~eligible,-torch.inf).topk(31,dim=1).indices
        mined=tail.gather(1,choices).masked_fill(~eligible.gather(1,choices),-torch.inf)
        scores=torch.cat([scores[:,:97],mined],dim=1)
    return F.cross_entropy(scores,torch.zeros(len(request),device=request.device,dtype=torch.long))

def main():
    assert os.environ.get('CUDA_VISIBLE_DEVICES')=='2'
    ROOT.mkdir(exist_ok=True)
    torch.set_num_threads(2);torch.set_num_interop_threads(1)
    torch.cuda.set_per_process_memory_fraction(.20);torch.backends.cuda.matmul.allow_tf32=False
    torch.manual_seed(42);health()
    source=V7/'export_candidate_v6/model.pt'
    base=torch.load(source,map_location='cpu',weights_only=True)
    mmap=np.load(V7/'candidate_v6_item_vectors.npy',mmap_mode='r')
    vectors=torch.empty(mmap.shape,device='cuda')
    for start in range(0,len(mmap),8192):vectors[start:start+8192].copy_(torch.tensor(np.asarray(mmap[start:start+8192])))
    excluded={r['index'] for r in json.loads((V7/'data/text_audit.json').read_text())['ineligible']}
    fingerprints=np.empty(len(mmap),dtype='uint64')
    with (V7/'data/items.jsonl').open() as stream:
        for i,line in enumerate(stream):
            r=json.loads(line);assert i==r['index']
            fingerprints[i]=int.from_bytes(hashlib.sha256(r['text'].strip().encode()).digest()[:8],'big')
    semantic=rows(OLD/'semantic_clean.jsonl')
    queries=F.normalize(torch.tensor(np.load(OLD/'query_features.npy'),device='cuda'),dim=-1)
    known={}
    for r in semantic:
        if r['split']=='train':known.setdefault(r['query'].strip().lower(),set()).add(r['item_index'])
    sem_train=[{'target':r['item_index'],'known_train_positives':list(known[r['query'].strip().lower()]),'query_index':i} for i,r in enumerate(semantic) if r['split']=='train']
    train=rows(OLD/'rec_train.jsonl')
    cohorts={'rec_dev':rows(V7/'data/rec_dev.jsonl')}
    model=ResidualTowers(1024,256,len(mmap),0).cuda()
    result={'state':'RUNNING','source':str(source),'train_examples':len(train),'candidate_count':len(mmap)-len(excluded),
        'selection_rule':'开发推荐Hit100、MRR、语义Hit10均不低于v6扩库基线；合格者先推荐Hit100再MRR再语义MRR；不使用确认用户选型',
        'scope':'冻结商品塔；用户完整遍历一轮，再查询校准600步；仅训练期标签，官方test不参与选型','runs':{}}
    def evaluate():
        model.eval()
        with torch.inference_mode():
            requests,targets,histories,positions,outputs=build_requests(model,mmap,cohorts,semantic,queries.cpu().numpy(),True,excluded)
            ranks,error=exact_ranks(requests,mmap,targets,histories,excluded=excluded)
            for (key,i),rank in zip(positions,ranks):outputs[key]['ranks'][i]=rank
        return summarize(outputs)
    model.load_state_dict(base['model']);result['baseline']=evaluate();save(ROOT/'results.json',result)
    finalists=[('baseline',str(source),result['baseline'])]
    order=epoch_indices(len(train),42,1,'shuffle')
    for hard in [False,True]:
        name='semihard' if hard else 'uniform';directory=ROOT/name;directory.mkdir(exist_ok=True)
        model.load_state_dict(base['model']);rng=random.Random(43);started=time.time()
        record={'checkpoints':[]};result['runs'][name]=record
        for task,total in [('rec',(len(train)+63)//64),('query',600)]:
            model.requires_grad_(False);module=model.user if task=='rec' else model.query;module.requires_grad_(True)
            optimizer=torch.optim.AdamW(module.parameters(),lr=2e-6 if task=='rec' else 1e-5,weight_decay=.01)
            anchor={k:v.detach().clone() for k,v in module.named_parameters()}
            for step in range(1,total+1):
                model.train();optimizer.zero_grad(set_to_none=True)
                batch=[train[i] for i in order[(step-1)*64:step*64]] if task=='rec' else rng.choices(sem_train,k=64)
                ids=torch.tensor(negatives(batch,rng,len(mmap),excluded,fingerprints,511 if hard else 127),device='cuda')
                if task=='rec':
                    h,mask=history_tensor(batch,'cuda');request=model.encode_user(vectors[h],mask)
                else:request=model.encode_query(queries[[r['query_index'] for r in batch]])
                loss=sampled_loss(request,vectors[ids],hard)
                loss=loss+.01*sum((v-anchor[k]).square().sum() for k,v in module.named_parameters())
                assert bool(torch.isfinite(loss));loss.backward();torch.nn.utils.clip_grad_norm_(module.parameters(),5);optimizer.step()
                if step==1 or step%100==0:
                    health();progress={'state':'TRAINING','run':name,'task':task,'step':step,'steps':total,'loss':float(loss.detach()),'seconds':time.time()-started,'pid':os.getpid()}
                    save(ROOT/'progress.json',progress);print(json.dumps(progress),flush=True)
                if step%1000==0 or step==total or (task=='query' and step%200==0):
                    path=directory/f'{task}_{step}.pt'
                    payload={'model':model.state_dict(),'config':{**base['config'],'hidden':256,'id_dim':0,'history_half_life_days':0},'optimizer':optimizer.state_dict(),'rng':rng.getstate(),'step':step,'task':task}
                    torch.save(payload,path)
                    if step==total or task=='query':
                        evaluation=evaluate();record['checkpoints'].append({'task':task,'step':step,'checkpoint':str(path),'evaluation':evaluation})
                        finalists.append((name+'_'+task+str(step),str(path),evaluation));save(ROOT/'results.json',result)
                        print('EVALUATION',name,task,step,evaluation['rec_dev/expanded_full_history']['metrics'],evaluation['semantic']['metrics'],flush=True)
        record['seconds']=time.time()-started
    b=result['baseline'];rec_key='rec_dev/expanded_full_history'
    def eligible(x):
        e=x[2];return all(e[k]['metrics'][metric]>=b[k]['metrics'][metric]-1e-12 for k,metric in [(rec_key,'hit@100'),(rec_key,'mrr'),('semantic','hit@10')])
    chosen=max(filter(eligible,finalists),key=lambda x:(x[2][rec_key]['metrics']['hit@100'],x[2][rec_key]['metrics']['mrr'],x[2]['semantic']['metrics']['mrr']))
    save(ROOT/'selection.json',{'state':'FROZEN','selected':chosen[0],'checkpoint':chosen[1],'development':chosen[2],'timestamp':time.time()})
    # 选定后复评曾经使用的确认用户，不冒充新的独立测试集。
    model.load_state_dict(torch.load(chosen[1],map_location='cpu',weights_only=True)['model'])
    cohorts.clear();cohorts['rec_confirm']=rows(V7/'data/rec_confirm.jsonl')
    result['confirmation']=evaluate();result.update(state='COMPLETE',selected=chosen[0],peak_cuda_gib=torch.cuda.max_memory_allocated()/2**30)
    assert all(torch.equal(v.cpu(),base['model']['item.'+k]) for k,v in model.item.state_dict().items())
    save(ROOT/'results.json',result);save(ROOT/'progress.json',{'state':'COMPLETE','selected':chosen[0]});health()

if __name__=='__main__':
    try:main()
    except Exception as e:
        ROOT.mkdir(exist_ok=True);save(ROOT/'failure.json',{'error':repr(e),'time':time.time()});raise
