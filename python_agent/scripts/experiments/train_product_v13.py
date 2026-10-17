"""32维协同分量对照：文本三塔冻结，GPU2完整前缀训练，未来用户封存。"""
import hashlib,json,math,os,random,time
from pathlib import Path
import numpy as np
import torch
import torch.nn.functional as F
from three_tower_residual import rows,history_tensor,metrics
from product_v13_model import CollaborativeTowers
from product_v10_model import SequenceResidualTowers,sample_hard_ids,head_loss
from train_product_v10 import evaluate_rec
from train_product_v9 import compact_batch
from train_product_v8 import negatives,health
from evaluate_product_v7_catalog import exact_ranks,save

BASE=Path('/mnt/data/luo/remote_runs');ROOT=BASE/'product_v13_training';V7=BASE/'product_v7_expansion';V9=BASE/'product_v9_training';V4=BASE/'three_tower_dataset_v4'

class CompositeVectors:
    def __init__(self,text,cf,alpha):self.text=text;self.cf=cf;self.alpha=alpha
    def __len__(self):return len(self.text)
    def __getitem__(self,index):
        return np.concatenate([np.float32((1-self.alpha)**.5)*self.text[index],np.float32(self.alpha**.5)*self.cf[index]],axis=-1)

@torch.inference_mode()
def evaluate(model,text,cohorts,excluded,alphas):
    device=next(model.parameters()).device
    cf=np.empty((len(text),model.collab_dim),dtype='float32')
    for s in range(0,len(cf),8192):cf[s:s+8192]=model.collab_items(torch.arange(s,min(s+8192,len(cf)),device=device)).cpu().numpy()
    result={}
    for alpha in alphas:
        model.alpha=alpha;req=[];targets=[];histories=[];positions=[];out={k:{'ranks':[0]*len(v)} for k,v in cohorts.items()}
        for key,records in cohorts.items():
            usable=[]
            for i,r in enumerate(records):
                history=[j for j in r['history_full'] if j not in excluded][-50:]
                if history and r['target']>=0:usable.append((i,{'history':history,'target':r['target']}))
            for s in range(0,len(usable),64):
                part=usable[s:s+64];batch=[r for _,r in part];h,mask=history_tensor(batch,device)
                hv=torch.tensor(np.asarray(text[h.cpu().numpy()]),device=device)
                q=model.encode_user_with_ids(hv,h,mask)
                req.extend(q.unbind());targets.extend(r['target'] for r in batch);histories.extend(r['history'] for r in batch);positions.extend((key,i) for i,_ in part)
        ranks,_=exact_ranks(torch.stack(req),CompositeVectors(text,cf,alpha),targets,histories,excluded=excluded)
        for (key,i),rank in zip(positions,ranks):out[key]['ranks'][i]=rank
        for k,v in out.items():v['metrics']=metrics(v['ranks'])
        result[str(alpha)]=out
    return result

def main():
    assert os.environ.get('CUDA_VISIBLE_DEVICES')=='2'
    torch.set_num_threads(2);torch.set_num_interop_threads(1);torch.cuda.set_per_process_memory_fraction(.25)
    torch.backends.cuda.matmul.allow_tf32=False;torch.manual_seed(42);health()
    assert not (ROOT/'selection.json').exists()
    mmap=np.load(V7/'candidate_v6_item_vectors.npy',mmap_mode='r')
    vectors=torch.empty(mmap.shape,device='cuda')
    for s in range(0,len(vectors),8192):vectors[s:s+8192].copy_(torch.tensor(np.asarray(mmap[s:s+8192])))
    source=torch.load(BASE/'product_v10_training/initial_cohesion.pt',map_location='cpu',weights_only=True)
    model=CollaborativeTowers(1024,256,len(vectors),0,alpha=.2).cuda()
    missing,extra=model.load_state_dict(source['model'],strict=False)
    assert not extra and all(k.startswith('collab_') for k in missing)
    initial={k:v.cpu().clone() for k,v in model.state_dict().items()}
    excluded={r['index'] for r in json.loads((V7/'data/text_audit.json').read_text())['ineligible']}
    fp=np.empty(len(vectors),dtype='uint64')
    with (V7/'data/items.jsonl').open() as f:
        for i,line in enumerate(f):fp[i]=int.from_bytes(hashlib.sha256(json.loads(line)['text'].strip().encode()).digest()[:8],'big')
    examples=np.load(V9/'data/train_examples.npy',mmap_mode='r');items=np.load(V9/'data/sequence_items.npy',mmap_mode='r');offsets=np.load(V9/'data/sequence_offsets.npy',mmap_mode='r')
    order=np.random.default_rng(42).permutation(len(examples));total=math.ceil(len(order)/128)
    cohorts={'existing_dev':rows(V7/'data/rec_dev.jsonl'),'fresh_dev':rows(V9/'data/fresh_dev.jsonl'),
             'future_short_dev':rows(BASE/'product_v10_training/data/future_dev.jsonl'),
             'future_snapshot_dev':rows(BASE/'product_v12_training/data/future_dev.jsonl'),
             'future_dev':rows(ROOT/'data/future_dev.jsonl')}
    keys=list(cohorts);future=[k for k in keys if k.startswith('future')]
    baseline=evaluate_rec(model,mmap,cohorts,excluded)
    result={'state':'TRAINING','baseline':baseline,'runs':{},'plan':{
        'train_examples':len(examples),'batch':128,'screen_steps':2000,'full_steps':total,'embedding_dimension':1056,'collab_dimension':32,
        'frozen':['BGE','item text MLP','user text MLP','query MLP'],'trainable':['collab_item','collab_user'],
        'objective':'推荐CE：0.8*冻结文本余弦+0.2*协同余弦，另加0.2*协同CE；温度0.07。仅train严格时间前缀。',
        'learning_rate':.002,'alpha_development':[.01,.03,.05,.15,.3],
        'selection':'5个开发群体MRR>=基线95%，Hit100最多降0.2百分点，Hit10最多降0.1百分点；3个未来开发MRR均不低于文本基线，滚动未来Hit100不退；最大化最小MRR比再总比。始终保留alpha0文本基线。',
        'online_modified':False,'sealed_policy':'冻结最优检查点与协同权重之后，仅打开新滚动封存一次。'}}
    if (ROOT/'results.json').exists():result=json.loads((ROOT/'results.json').read_text())
    result['plan']['alpha_development']=[.01,.03,.05,.15,.3]
    result['plan']['development_adjustment']='初筛发现0.05协同权重在较早未来开发群体产生较大MRR损失；冻结之前增设0.01/0.03，所有已有检查点用同一新网格复评。仅开发调整，封存仍不打开。'
    config={**source['config'],'collab_dim':32,'output_dimension':1056,'input_dimension':1024,'alpha':0.}
    base_path=ROOT/'initial.pt'
    if not base_path.exists():torch.save({'model':initial,'config':config},base_path)
    finalists=[('initial',str(base_path),0.,baseline)]
    for n,r in result['runs'].items():
        for e in r['checkpoints']:
            for alpha,ev in e['evaluation'].items():finalists.append((n+'_'+str(e['step']),e['checkpoint'],float(alpha),ev))
    def eligible(ev):
        return all(ev[k]['metrics']['mrr']>=.95*baseline[k]['metrics']['mrr'] and ev[k]['metrics']['hit@100']>=baseline[k]['metrics']['hit@100']-.002 and ev[k]['metrics']['hit@10']>=baseline[k]['metrics']['hit@10']-.001 for k in keys) and all(ev[k]['metrics']['mrr']>=baseline[k]['metrics']['mrr'] for k in future) and ev['future_dev']['metrics']['hit@100']>=baseline['future_dev']['metrics']['hit@100']
    def score(ev):
        ratios=[ev[k]['metrics']['mrr']/baseline[k]['metrics']['mrr'] for k in keys]
        return (min(ratios),sum(ratios),ev['future_dev']['metrics']['hit@100'])
    def run(name,hard,end=2000):
        directory=ROOT/name;directory.mkdir(exist_ok=True)
        model.load_state_dict(initial);model.alpha=.2;model.requires_grad_(False)
        model.collab_item.requires_grad_(True);model.collab_user.requires_grad_(True)
        optimizer=torch.optim.AdamW([{'params':model.collab_item.parameters(),'weight_decay':0.},
                                    {'params':model.collab_user.parameters(),'weight_decay':.01}],lr=.002)
        rng=random.Random(43);start=0;record=result['runs'].setdefault(name,{'hard':hard,'checkpoints':[]})
        if (directory/'last.pt').exists():
            cp=torch.load(directory/'last.pt',map_location='cpu',weights_only=True)
            model.load_state_dict(cp['model']);optimizer.load_state_dict(cp['optimizer']);rng.setstate(cp['rng']);start=cp['step']
        began=time.time()
        for step in range(start+1,end+1):
            model.alpha=.2;optimizer.zero_grad(set_to_none=True)
            batch=compact_batch(examples,order[(step-1)*128:step*128],items,offsets)
            h,mask=history_tensor(batch,'cuda')
            with torch.no_grad():
                textq=SequenceResidualTowers.encode_user(model,vectors[h],mask)
                uniform=negatives(batch,rng,len(vectors),excluded,fp,127)
                ids=sample_hard_ids(batch,textq,vectors,random.Random(100000+step),excluded,fp,uniform) if hard else uniform
                ids=torch.tensor(ids,device='cuda');text_scores=torch.einsum('bd,bnd->bn',textq,vectors[ids])
            cfq=model.collab_request(vectors[h],h,mask);cf=model.collab_items(ids)
            cf_scores=torch.einsum('bd,bnd->bn',cfq,cf)
            logits=(.8*text_scores+.2*cf_scores)/.07;cf_logits=cf_scores/.07
            if hard:
                penalty=torch.zeros_like(logits);penalty[:,97:]=math.log(.05);logits=logits+penalty;cf_logits=cf_logits+penalty
            target=torch.zeros(len(batch),device='cuda',dtype=torch.long)
            ce=F.cross_entropy(logits,target);loss=ce+.2*F.cross_entropy(cf_logits,target)
            assert bool(torch.isfinite(loss));loss.backward();torch.nn.utils.clip_grad_norm_([*model.collab_item.parameters(),*model.collab_user.parameters()],5);optimizer.step()
            if step==1 or step%200==0:
                health();p={'state':'TRAINING','run':name,'step':step,'steps':end,'full_steps':total,'loss':float(loss.detach()),'ce':float(ce.detach()),
                            'seconds':time.time()-began,'pid':os.getpid(),'cuda_reserved_gib':torch.cuda.memory_reserved()/2**30}
                save(ROOT/'progress.json',p);print(json.dumps(p),flush=True)
            if step%500==0 or step==end:
                cp={'model':model.state_dict(),'config':{**config,'alpha':.2},'optimizer':optimizer.state_dict(),'rng':rng.getstate(),'step':step}
                tmp=directory/'last.tmp';torch.save(cp,tmp);tmp.replace(directory/'last.pt')
            if step in [2000,5000,10000,15000,total] or step==end:
                path=directory/f'step_{step}.pt';torch.save(cp,path)
                ev=evaluate(model,mmap,cohorts,excluded,[.01,.03,.05,.15,.3]);record['checkpoints'].append({'step':step,'checkpoint':str(path),'evaluation':ev})
                for alpha,x in ev.items():finalists.append((name+'_'+str(step),str(path),float(alpha),x))
                save(ROOT/'results.json',result)
                print('V13_EVAL',name,step,{a:{k:v['metrics'] for k,v in x.items()} for a,x in ev.items()},flush=True)
        record['state']='COMPLETE';save(ROOT/'results.json',result)
    specs=[('collab_random',False),('collab_soft_hard',True)]
    for spec in specs:run(*spec)
    # 已完成的旧网格初筛也补齐新开发对照，不能只让后跑的组享受更多选择。
    for name,record in result['runs'].items():
        for entry in record['checkpoints']:
            if not {'0.01','0.03'}.issubset(entry['evaluation']):
                cp=torch.load(entry['checkpoint'],map_location='cpu',weights_only=True);model.load_state_dict(cp['model'])
                entry['evaluation'].update(evaluate(model,mmap,cohorts,excluded,[.01,.03]))
                for a in ['0.01','0.03']:finalists.append((name+'_'+str(entry['step']),entry['checkpoint'],float(a),entry['evaluation'][a]))
                save(ROOT/'results.json',result)
    trained=[x for x in finalists if x[0]!='initial' and eligible(x[3])]
    if trained:
        best=max(trained,key=lambda x:score(x[3]));name=best[0].rsplit('_',1)[0]
        save(ROOT/'screen_selection.json',{'run':name,'state':'FIXED','timestamp':time.time()})
        run(*next(s for s in specs if s[0]==name),end=total)
    chosen=max((x for x in finalists if eligible(x[3])),key=lambda x:score(x[3]))
    cp=torch.load(chosen[1],map_location='cpu',weights_only=True);cp['config']['alpha']=chosen[2]
    selected=ROOT/'selected.pt';torch.save({'model':cp['model'],'config':cp['config']},selected)
    save(ROOT/'selection.json',{'state':'FROZEN','selected':chosen[0],'checkpoint':str(selected),'source_checkpoint':chosen[1],'alpha':chosen[2],
                              'development':chosen[3],'rule':result['plan'],'timestamp':time.time()})
    for k,v in cp['model'].items():
        if not k.startswith('collab_'):assert torch.equal(v,source['model'][k])
    model.load_state_dict(cp['model']);cohorts={'sealed_future':rows(ROOT/'data/sealed_future.jsonl')}
    sealed={'candidate':evaluate(model,mmap,cohorts,excluded,[chosen[2]])[str(chosen[2])],
            'initial':evaluate_rec(model,mmap,cohorts,excluded)}
    old=torch.load(V4/'export_joint_full_seed42/model.pt',map_location='cpu',weights_only=True)
    reference=SequenceResidualTowers(1024,256,len(vectors),0).cuda().eval();reference.load_state_dict(old['model'])
    sealed['online_expanded']=evaluate_rec(reference,np.load(V7/'online_v4_item_vectors.npy',mmap_mode='r'),cohorts,excluded)
    sealed['online_actual']=evaluate_rec(reference,np.load(V4/'export_joint_full_seed42/item_vectors.npy',mmap_mode='r'),cohorts,excluded,False)
    result.update(state='COMPLETE',selected=chosen[0],alpha=chosen[2],sealed=sealed,peak_cuda_gib=torch.cuda.max_memory_allocated()/2**30)
    save(ROOT/'results.json',result);save(ROOT/'progress.json',{'state':'COMPLETE','selected':chosen[0],'alpha':chosen[2]})

if __name__=='__main__':
    try:main()
    except Exception as e:save(ROOT/'failure.json',{'error':repr(e),'time':time.time()});raise
