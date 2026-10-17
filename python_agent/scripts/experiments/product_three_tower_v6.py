"""商品三塔校准与受约束联合训练；固定词表，开发/确认分开，禁止线上修改。"""
import argparse, hashlib, json, os, random, time
from pathlib import Path
import numpy as np
import torch
import torch.nn.functional as F
from three_tower_residual import ResidualTowers, history_tensor, metrics, rows
from product_recall_v5 import candidate_ids, epoch_indices


def save(path,value):
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(path)


def parameter_groups(model,mode,lr,query_lr):
    model.item.requires_grad_(mode in ('rec','joint'))
    model.user.requires_grad_(mode in ('rec','joint'))
    model.query.requires_grad_(mode in ('query','joint'))
    groups=[]
    for name,module,rate in [('item',model.item,lr),('user',model.user,lr),('query',model.query,query_lr)]:
        if any(p.requires_grad for p in module.parameters()):groups.append({'params':module.parameters(),'lr':rate,'weight_decay':.01})
    return groups


def contrastive(model,features,batch,rng,task,query_features=None):
    ids=torch.tensor(candidate_ids(batch,rng,len(features),127 if task=='semantic' else 32,'random'),device=features.device)
    if task=='rec':
        history,mask=history_tensor(batch,features.device)
        combined=torch.cat([ids.flatten(),history.flatten()])
    else:combined=ids.flatten()
    unique,inverse=torch.unique(combined,return_inverse=True)
    encoded=model.encode_items(features[unique])
    items=encoded[inverse[:ids.numel()]].reshape(*ids.shape,-1)
    if task=='rec':request=model.encode_user(encoded[inverse[ids.numel():]].reshape(*history.shape,-1),mask)
    else:request=model.encode_query(query_features[[r['query_index'] for r in batch]])
    loss=F.cross_entropy(torch.einsum('bd,bnd->bn',request,items)/.07,torch.zeros(len(batch),dtype=torch.long,device=features.device))
    if not torch.isfinite(loss):raise ValueError('nonfinite contrastive loss')
    return loss


@torch.inference_mode()
def evaluate(model,features,valid,semantic,queries):
    model.eval()
    item_vectors=torch.cat([model.encode_items(features[s:s+512]) for s in range(0,len(features),512)])
    ranks=[0]*len(valid)
    usable=[i for i,r in enumerate(valid) if r['history'] and r['target']>=0]
    for offset in range(0,len(usable),16):
        indexes=usable[offset:offset+16];batch=[valid[i] for i in indexes]
        ids,mask=history_tensor(batch,features.device)
        scores=model.encode_user(item_vectors[ids],mask)@item_vectors.T
        for j,(i,r) in enumerate(zip(indexes,batch)):
            assert r['target'] not in r['history']
            scores[j,r['history']]=-torch.inf
            ranks[i]=int((scores[j]>=scores[j,r['target']]).sum())
    sem_indices=[i for i,r in enumerate(semantic) if r['split']=='valid'];sem_ranks=[]
    for offset in range(0,len(sem_indices),16):
        selected=sem_indices[offset:offset+16]
        scores=model.encode_query(queries[selected])@item_vectors.T
        for j,i in enumerate(selected):sem_ranks.append(int((scores[j]>=scores[j,semantic[i]['item_index']]).sum()))
    recommendation=metrics(ranks)
    recommendation['candidate_target_coverage']=sum(r['target']>=0 for r in valid)/len(valid)
    recommendation['known_history_coverage']=sum(bool(r['history']) for r in valid)/len(valid)
    return {'rec':recommendation,'rec_ranks':ranks,'semantic':metrics(sem_ranks),'semantic_ranks':sem_ranks,
        'semantic_scope':'合成查询的来源商品恢复，不是人工相关性标注'}


def run(args):
    if os.environ.get('CUDA_VISIBLE_DEVICES')!='2':raise RuntimeError('GPU2 only')
    torch.set_num_threads(2);torch.set_num_interop_threads(1)
    torch.cuda.set_per_process_memory_fraction(.20);torch.backends.cuda.matmul.allow_tf32=False
    args.output.mkdir(parents=True,exist_ok=False)
    (args.output/'training_source.py').write_bytes(Path(__file__).read_bytes())
    random.seed(args.seed);np.random.seed(args.seed);torch.manual_seed(args.seed)
    features=F.normalize(torch.from_numpy(np.load(args.data/'item_features.npy')).cuda(),dim=-1)
    queries=F.normalize(torch.from_numpy(np.load(args.data/'query_features.npy')).cuda(),dim=-1)
    semantic=rows(args.data/'semantic_clean.jsonl');valid=rows(args.evaluation)
    assert len(queries)==len(semantic) and len({r['user_hash'] for r in valid})==len(valid)
    model=ResidualTowers(features.shape[1],256,len(features),0).cuda()
    if args.checkpoint:
        checkpoint=torch.load(args.checkpoint,map_location='cpu',weights_only=True)
        model.load_state_dict(checkpoint['model'],strict=True)
    config={k:str(v) if isinstance(v,Path) else v for k,v in vars(args).items()}
    result={'state':'RUNNING','config':config,'evaluation_sha256':hashlib.sha256(args.evaluation.read_bytes()).hexdigest(),
        'code_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'checkpoints':[]}
    result['checkpoint_sha256']=hashlib.sha256(args.checkpoint.read_bytes()).hexdigest() if args.checkpoint else None
    result['semantic_sha256']=hashlib.sha256((args.data/'semantic_clean.jsonl').read_bytes()).hexdigest()
    result['initial']=evaluate(model,features,valid,semantic,queries);save(args.output/'results.json',result)
    if args.mode=='evaluate':
        result.update(state='COMPLETE',final=result['initial']);save(args.output/'results.json',result);return
    train=rows(args.data/'rec_train.jsonl') if args.mode in ('rec','joint') else []
    known={}
    for i,r in enumerate(semantic):
        if r['split']=='train':known.setdefault(r['query'].strip().lower(),set()).add(r['item_index'])
    sem_train=[{'target':r['item_index'],'known_train_positives':list(known[r['query'].strip().lower()]),'query_index':i}
               for i,r in enumerate(semantic) if r['split']=='train']
    assert not ({r['query'].strip().lower() for r in semantic if r['split']=='train'} & {r['query'].strip().lower() for r in semantic if r['split']=='valid'})
    groups=parameter_groups(model,args.mode,args.lr,args.query_lr)
    optimizer=torch.optim.AdamW(groups)
    rec_rng=random.Random(args.seed+1);sem_rng=random.Random(args.seed+2)
    source_item={k:v.detach().clone() for k,v in model.item.state_dict().items()}
    source_user={k:v.detach().clone() for k,v in model.user.state_dict().items()}
    # 完整遍历推荐样本；两个任务的随机数流分离，rec与joint使用相同推荐样本/负例。
    order=[];offset=0;epoch=0;start=time.time();semantic_updates=0
    for step in range(1,args.steps+1):
        model.train();optimizer.zero_grad(set_to_none=True);losses={}
        if args.mode in ('rec','joint'):
            if offset>=len(order):
                epoch+=1;order=epoch_indices(len(train),args.seed,epoch,'shuffle');offset=0
            batch=[train[i] for i in order[offset:offset+64]];offset+=len(batch)
            loss=contrastive(model,features,batch,rec_rng,'rec');loss.backward();losses['rec']=float(loss.detach())
            assert all(p.grad is None for p in model.query.parameters())
        if args.mode=='query' or (args.mode=='joint' and step%args.semantic_every==0):
            batch=sem_rng.choices(sem_train,k=64)
            loss=contrastive(model,features,batch,sem_rng,'semantic',queries)
            (loss*(args.semantic_weight if args.mode=='joint' else 1.)).backward()
            losses['semantic']=float(loss.detach());semantic_updates+=1
        if args.mode in ('rec','joint') and args.anchor:
            # 约束商品残差权重偏离初始推荐模型；不是利用开发标签的蒸馏。
            penalty=sum((v-source_item[k]).square().sum() for k,v in model.item.named_parameters())
            (args.anchor*penalty).backward();losses['anchor']=float(penalty.detach())
        torch.nn.utils.clip_grad_norm_([p for p in model.parameters() if p.requires_grad],5);optimizer.step()
        if step%100==0 or step==1:
            progress={'state':'TRAINING','step':step,'steps':args.steps,'semantic_updates':semantic_updates,'seconds':time.time()-start,'losses':losses}
            save(args.output/'progress.json',progress);print(json.dumps(progress),flush=True)
        if step%args.eval_every==0 or step==args.steps:
            evaluation=evaluate(model,features,valid,semantic,queries)
            if args.mode=='query':
                assert all(torch.equal(v,source_item[k]) for k,v in model.item.state_dict().items())
                assert all(torch.equal(v,source_user[k]) for k,v in model.user.state_dict().items())
                assert evaluation['rec_ranks']==result['initial']['rec_ranks']
            result['checkpoints'].append({'step':step,'semantic_updates':semantic_updates,'seconds':time.time()-start,'evaluation':evaluation})
            payload={'model':model.state_dict(),'optimizer':optimizer.state_dict(),'config':config,'step':step,'semantic_updates':semantic_updates,
                     'rec_rng':rec_rng.getstate(),'sem_rng':sem_rng.getstate(),'epoch':epoch,'offset':offset}
            torch.save(payload,args.output/f'step_{step}.pt');save(args.output/'results.json',result)
            print('EVAL',step,evaluation['rec'],evaluation['semantic'],flush=True)
    result.update(state='COMPLETE',final=result['checkpoints'][-1]['evaluation'],seconds=time.time()-start,peak_cuda_gib=torch.cuda.max_memory_allocated()/2**30)
    save(args.output/'results.json',result);save(args.output/'progress.json',{'state':'COMPLETE','step':args.steps})


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data',type=Path,required=True);p.add_argument('--evaluation',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--checkpoint',type=Path);p.add_argument('--mode',choices=['evaluate','query','rec','joint'],default='evaluate')
    p.add_argument('--seed',type=int,default=42);p.add_argument('--steps',type=int,default=600);p.add_argument('--eval-every',type=int,default=200)
    p.add_argument('--lr',type=float,default=2e-6);p.add_argument('--query-lr',type=float,default=1e-5);p.add_argument('--semantic-every',type=int,default=5);p.add_argument('--semantic-weight',type=float,default=.1);p.add_argument('--anchor',type=float,default=.01)
    run(p.parse_args())
