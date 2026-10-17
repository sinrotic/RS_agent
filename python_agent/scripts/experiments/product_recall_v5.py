"""隔离的商品推荐对照：完整遍历、负例与轻量用户聚合；只读 v4 数据。"""
import argparse, collections, hashlib, json, math, os, random, time
from pathlib import Path
import numpy as np
import torch
from torch import nn
import torch.nn.functional as F
from three_tower_residual import ResidualTowers, history_tensor, metrics, rows


def save(path, value):
    temporary=path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value,ensure_ascii=False,indent=2))
    temporary.replace(path)


class AttentionTowers(ResidualTowers):
    def __init__(self, dimension=1024, hidden=256, item_count=0):
        super().__init__(dimension,hidden,item_count,0)
        self.attention=nn.Sequential(nn.Linear(dimension+1,32),nn.Tanh(),nn.Linear(32,1))
        nn.init.zeros_(self.attention[-1].weight);nn.init.zeros_(self.attention[-1].bias)

    def encode_user(self, history_vectors, mask):
        if bool((mask.sum(1)==0).any()):raise ValueError('empty history')
        length=mask.sum(1,keepdim=True)
        position=(torch.arange(mask.shape[1],device=mask.device)[None,:]+1)/length
        logits=self.attention(torch.cat([history_vectors,position.unsqueeze(-1)],dim=-1)).squeeze(-1)
        weights=logits.masked_fill(mask==0,-torch.inf).softmax(1)
        mean=(history_vectors*weights.unsqueeze(-1)).sum(1)
        return F.normalize(mean+self.user(mean),dim=-1)


def candidate_ids(batch,rng,item_count,negative_count,mode,categories=None,pools=None):
    targets=[r['target'] for r in batch];output=[]
    for r in batch:
        blocked=set(r['known_train_positives'])|{r['target']};chosen=[]
        def add(value):
            if value not in blocked and len(chosen)<negative_count:
                chosen.append(value);blocked.add(value)
        if mode=='mixed':
            shuffled=targets.copy();rng.shuffle(shuffled)
            for value in shuffled[:min(63,negative_count//2)]:add(value)
            pool=pools.get(categories[r['target']],[])
            # 同类目仅为弱难负例，不将它当作明确不喜欢的标签。
            for _ in range(min(32,negative_count//4)):
                if pool:add(pool[rng.randrange(len(pool))])
        if item_count-len(blocked)<negative_count-len(chosen):raise ValueError('insufficient distinct negatives')
        while len(chosen)<negative_count:add(rng.randrange(item_count))
        output.append([r['target']]+chosen)
    return output


def epoch_indices(size,seed,epoch,sampler):
    rng=random.Random(seed+1000003*epoch)
    if sampler=='replacement':return [rng.randrange(size) for _ in range(size)]
    order=list(range(size));rng.shuffle(order);return order


@torch.inference_mode()
def evaluate(model,features,valid):
    model.eval()
    vectors=torch.cat([model.encode_items(features[i:i+512]) for i in range(0,len(features),512)])
    ranks=[]
    for i in range(0,len(valid),16):
        batch=valid[i:i+16];ids,mask=history_tensor(batch,features.device)
        scores=model.encode_user(vectors[ids],mask)@vectors.T
        for j,row in enumerate(batch):
            if row['target']<0:ranks.append(0);continue
            assert row['target'] not in row['history']
            scores[j,row['history']]=-torch.inf
            ranks.append(int((scores[j]>=scores[j,row['target']]).sum()))
    groups={}
    for name,predicate in [('history_le3',lambda x:len(x['history'])<=3),('history_4_9',lambda x:4<=len(x['history'])<=9),('history_ge10',lambda x:len(x['history'])>=10)]:
        subset=[rank for row,rank in zip(valid,ranks) if predicate(row)]
        if subset:groups[name]=metrics(subset)
    return {'metrics':metrics(ranks),'ranks':ranks,'groups':groups}


def train(args):
    expected='2' if args.device=='cuda' else ''
    if os.environ.get('CUDA_VISIBLE_DEVICES')!=expected:raise RuntimeError('device visibility mismatch')
    torch.set_num_threads(2);torch.set_num_interop_threads(1)
    if args.device=='cuda':
        torch.cuda.set_per_process_memory_fraction(.20)
        torch.backends.cuda.matmul.allow_tf32=False
        if args.cpu_bf16:raise ValueError('CPU autocast cannot be used on CUDA')
    args.output.mkdir(parents=True,exist_ok=False)
    (args.output/'training_source.py').write_bytes(Path(__file__).read_bytes())
    random.seed(args.seed);np.random.seed(args.seed);torch.manual_seed(args.seed)
    train_rows=rows(args.data/'rec_train.jsonl');valid=rows(args.data/'rec_valid.jsonl')
    assert len(set(r['user_hash'] for r in valid))==len(valid)
    features=F.normalize(torch.from_numpy(np.load(args.data/'item_features.npy')).to(args.device),dim=-1)
    catalog=rows(args.data/'items.jsonl');categories=[str(r.get('category','')) for r in catalog]
    assert [r['index'] for r in catalog]==list(range(len(features)))
    pools=collections.defaultdict(list)
    for i,category in enumerate(categories):pools[category].append(i)
    del catalog
    model=(AttentionTowers if args.user=='attention' else ResidualTowers)(features.shape[1],256,len(features)).to(args.device)
    checkpoint=None
    if args.initial_checkpoint or args.resume_checkpoint:
        checkpoint=torch.load(args.resume_checkpoint or args.initial_checkpoint,map_location='cpu',weights_only=True)
        model.load_state_dict(checkpoint['model'],strict=True)
    optimizer=torch.optim.AdamW(model.parameters(),lr=args.lr,weight_decay=.01)
    config={k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()}
    result={'state':'RUNNING','config':config,'train_rows':len(train_rows),'candidate_count':len(features),
        'evaluation_scope':'existing development cohort only; official final test NOT read',
        'negative_objective':'contrastive sampled discrimination; mixed sampler is not unbiased full-softmax',
        'epochs':[],'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    save(args.output/'results.json',result)
    if args.evaluate_only:
        result['evaluation']=evaluate(model,features,valid);result['state']='COMPLETE';save(args.output/'results.json',result);return
    start=time.monotonic();best=-1.;stale=0;seen=np.zeros(len(train_rows),dtype=bool);step=0;start_epoch=1
    if args.resume_checkpoint:
        for key in ['seed','sampler','negative_mode','negatives','user','batch_size','lr']:
            if checkpoint['config'][key]!=config[key]:raise ValueError('resume config mismatch: '+key)
        optimizer.load_state_dict(checkpoint['optimizer'])
        step=checkpoint['steps'];start_epoch=checkpoint['epoch']+1
        previous=json.loads((args.resume_checkpoint.parent/'results.json').read_text())
        result['epochs']=[e for e in previous['epochs'] if e['epoch']<start_epoch]
        for e in result['epochs']:
            seen[epoch_indices(len(train_rows),args.seed,e['epoch'],args.sampler)]=True
            score=e['evaluation']['metrics']['hit@100']
            if score>best:best=score;stale=0;result['best_epoch']=e['epoch']
            else:stale+=1
        result['resumed_from']=str(args.resume_checkpoint)
        result['previous_best_checkpoint']=str(args.resume_checkpoint.parent/'best.pt')
        save(args.output/'results.json',result)
    for epoch in range(start_epoch,args.epochs+1):
        order=epoch_indices(len(train_rows),args.seed,epoch,args.sampler);rng=random.Random(args.seed+epoch*1009)
        losses=[];epoch_seen=np.zeros(len(train_rows),dtype=bool)
        for offset in range(0,len(order),args.batch_size):
            if args.max_steps and step>=args.max_steps:break
            indexes=order[offset:offset+args.batch_size];batch=[train_rows[i] for i in indexes]
            seen[indexes]=True;epoch_seen[indexes]=True;model.train();optimizer.zero_grad(set_to_none=True)
            candidates=torch.tensor(candidate_ids(batch,rng,len(features),args.negatives,args.negative_mode,categories,pools),device=args.device)
            ids,mask=history_tensor(batch,args.device);combined=torch.cat([candidates.flatten(),ids.flatten()]);unique,inverse=torch.unique(combined,return_inverse=True)
            with torch.autocast(device_type='cpu',dtype=torch.bfloat16,enabled=args.cpu_bf16):
                encoded=model.encode_items(features[unique]);cv=encoded[inverse[:candidates.numel()]].view(*candidates.shape,-1)
                hv=encoded[inverse[candidates.numel():]].view(*ids.shape,-1);user=model.encode_user(hv,mask)
                loss=F.cross_entropy(torch.einsum('bd,bnd->bn',user,cv)/.07,torch.zeros(len(batch),dtype=torch.long,device=args.device))
            if not torch.isfinite(loss):raise ValueError('nonfinite loss')
            loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),5);optimizer.step();losses.append(float(loss.detach()));step+=1
            if step==1 or step%100==0:
                save(args.output/'progress.json',{'state':'TRAINING','epoch':epoch,'step':step,'epoch_unique':int(epoch_seen.sum()),'total_unique':int(seen.sum()),'loss_mean':float(np.mean(losses[-100:])),'elapsed_seconds':time.monotonic()-start})
                print('STEP',step,'epoch',epoch,'loss',float(np.mean(losses[-100:])),flush=True)
        complete=int(epoch_seen.sum())==len(train_rows)
        evaluation=evaluate(model,features,valid) if not args.benchmark_only else None
        entry={'epoch':epoch,'steps':step,'epoch_unique':int(epoch_seen.sum()),'epoch_unique_fraction':float(epoch_seen.mean()),'total_unique':int(seen.sum()),'full_epoch':bool(complete),'loss_mean':float(np.mean(losses)),'evaluation':evaluation,'elapsed_seconds':time.monotonic()-start}
        result['epochs'].append(entry);save(args.output/'results.json',result)
        print('EPOCH',json.dumps({k:v for k,v in entry.items() if k!='evaluation'}),'metrics',evaluation['metrics'] if evaluation else None,flush=True)
        score=evaluation['metrics']['hit@100'] if evaluation else -1
        payload={'model':model.state_dict(),'optimizer':optimizer.state_dict(),'config':config,'epoch':epoch,'steps':step}
        torch.save(payload,args.output/'last.pt')
        if score>best:
            best=score;stale=0;result['best_epoch']=epoch;torch.save(payload,args.output/'best.pt')
        else:stale+=1
        if args.max_steps and step>=args.max_steps:break
        if epoch>=3 and stale>=args.patience:result['early_stopped']=True;break
    result.update(state='COMPLETE',seconds=time.monotonic()-start,unique_training_rows=int(seen.sum()))
    if args.device=='cuda':result['peak_cuda_gib']=torch.cuda.max_memory_allocated()/2**30
    save(args.output/'results.json',result)
    save(args.output/'progress.json',{'state':'COMPLETE','step':step,'elapsed_seconds':result['seconds']})


def main():
    p=argparse.ArgumentParser();p.add_argument('--data',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--epochs',type=int,default=5);p.add_argument('--seed',type=int,default=42);p.add_argument('--batch-size',type=int,default=64)
    p.add_argument('--lr',type=float,default=2e-5);p.add_argument('--negatives',type=int,default=32)
    p.add_argument('--negative-mode',choices=['random','mixed'],default='random');p.add_argument('--user',choices=['mean','attention'],default='mean')
    p.add_argument('--sampler',choices=['shuffle','replacement'],default='shuffle');p.add_argument('--max-steps',type=int,default=0)
    p.add_argument('--patience',type=int,default=2);p.add_argument('--benchmark-only',action='store_true');p.add_argument('--evaluate-only',action='store_true');p.add_argument('--initial-checkpoint',type=Path)
    p.add_argument('--cpu-bf16',action='store_true')
    p.add_argument('--device',choices=['cpu','cuda'],default='cpu')
    p.add_argument('--resume-checkpoint',type=Path,help='restore optimizer and continue after a completed epoch')
    train(p.parse_args())

if __name__=='__main__':main()
