"""五组负样本/位置衰减/头部损失对照；开发筛选后继续全遍历，封存冻结后验收。"""
import json,math,os,random,sys,time
from pathlib import Path
import numpy as np
import torch
from three_tower_residual import history_tensor,rows,metrics
from evaluate_product_v7_catalog import exact_ranks,save
from product_v10_model import SequenceResidualTowers,sample_hard_ids,head_loss
ROOT=Path('/mnt/data/luo/remote_runs/product_v10_training')
V7=ROOT.parent/'product_v7_expansion';V9=ROOT.parent/'product_v9_training';V4=ROOT.parent/'three_tower_dataset_v4'
sys.path.insert(0,str(V9/'scripts'))
from train_product_v9 import compact_batch
from train_product_v8 import health,negatives

@torch.inference_mode()
def evaluate_rec(model,vectors,cohorts,excluded,expanded=True):
    requests=[];targets=[];histories=[];positions=[];out={}
    device=next(model.parameters()).device
    for key,records in cohorts.items():
        out[key]={'ranks':[0]*len(records)}
        usable=[]
        for i,r in enumerate(records):
            history=[x for x in r['history_full' if expanded else 'history_old'] if x not in excluded][-50:]
            target=r['target' if expanded else 'old_target']
            if history and target>=0:
                assert target not in history
                usable.append((i,{'history':history,'target':target}))
        for start in range(0,len(usable),64):
            part=usable[start:start+64];batch=[r for _,r in part];ids,mask=history_tensor(batch,device)
            h=torch.tensor(np.asarray(vectors[ids.cpu().numpy()]),device=device)
            q=model.encode_user(h,mask)
            requests.extend(q.unbind());targets.extend(r['target'] for r in batch);histories.extend(r['history'] for r in batch);positions.extend((key,i) for i,_ in part)
    ranks,_=exact_ranks(torch.stack(requests),vectors,targets,histories,excluded=excluded)
    for (key,i),rank in zip(positions,ranks):out[key]['ranks'][i]=rank
    for key,value in out.items():value['metrics']=metrics(value['ranks'])
    return out

def main():
    assert os.environ.get('CUDA_VISIBLE_DEVICES')=='2'
    torch.set_num_threads(2);torch.set_num_interop_threads(1);torch.cuda.set_per_process_memory_fraction(.20)
    torch.backends.cuda.matmul.allow_tf32=False;torch.manual_seed(42);health()
    while not (ROOT/'data/manifest.json').exists():time.sleep(5)
    source=torch.load(V9/'initial.pt',map_location='cpu',weights_only=True)
    mmap=np.load(V7/'candidate_v6_item_vectors.npy',mmap_mode='r');vectors=torch.empty(mmap.shape,device='cuda')
    for s in range(0,len(vectors),8192):vectors[s:s+8192].copy_(torch.tensor(np.asarray(mmap[s:s+8192])))
    excluded={r['index'] for r in json.loads((V7/'data/text_audit.json').read_text())['ineligible']}
    import hashlib
    fp=np.empty(len(vectors),dtype='uint64')
    with (V7/'data/items.jsonl').open() as f:
        for i,line in enumerate(f):fp[i]=int.from_bytes(hashlib.sha256(json.loads(line)['text'].strip().encode()).digest()[:8],'big')
    examples=np.load(V9/'data/train_examples.npy',mmap_mode='r');items=np.load(V9/'data/sequence_items.npy',mmap_mode='r');offsets=np.load(V9/'data/sequence_offsets.npy',mmap_mode='r')
    order=np.random.default_rng(42).permutation(len(examples));total=math.ceil(len(examples)/128)
    cohorts={'existing_dev':rows(V7/'data/rec_dev.jsonl'),'fresh_dev':rows(V9/'data/fresh_dev.jsonl'),'future_dev':rows(ROOT/'data/future_dev.jsonl')}
    result={'state':'TRAINING','runs':{},'plan':{'screen_steps':4000,'full_steps':total,'batch':128,'learning_rate':5e-7,
        'selection':'三个开发群体MRR至少初始95%，未来开发MRR不低于初始；Hit100最多下降0.2个百分点、Hit10最多下降0.1个百分点。最大化三个群体最小MRR相对值，再未来MRR、Hit10。始终保留未续训起始模型。封存只在选型冻结后打开。',
        'hard':'96随机+31用户近邻，共享4096池；排除已知正例、空文本、同文本、正商品余弦>=.97的近重复；不排除得分高于正商品的竞争项。'}}
    assert not (ROOT/'selection.json').exists(),'selection already frozen'
    if (ROOT/'results.json').exists():result=json.loads((ROOT/'results.json').read_text())
    model=SequenceResidualTowers(1024,256,len(vectors),0).cuda();model.load_state_dict(source['model'])
    baseline=evaluate_rec(model,mmap,cohorts,excluded);result['baseline']=baseline
    finalists=[]
    for name,record in result['runs'].items():
        for entry in record.get('checkpoints',[]):finalists.append((name+'_'+str(entry['step']),entry['checkpoint'],entry['evaluation']))
    def add_initial(pooling):
        model.load_state_dict(source['model']);model.pooling=pooling
        path=ROOT/('initial_'+pooling+'.pt');torch.save({'model':model.state_dict(),'config':{**source['config'],'pooling':pooling}},path)
        ev=baseline if pooling=='mean' else evaluate_rec(model,mmap,cohorts,excluded)
        finalists.append(('initial_'+pooling,str(path),ev));result['runs']['initial_'+pooling]={'evaluation':ev}
    add_initial('mean');add_initial('decay08');add_initial('blend_recent');add_initial('cohesion');save(ROOT/'results.json',result)
    def train_run(name,pooling,hard,extra,start=0,end=4000,resume=False):
        directory=ROOT/name;directory.mkdir(exist_ok=True);model.pooling=pooling
        model.load_state_dict(source['model']);model.requires_grad_(False);model.user.requires_grad_(True)
        optimizer=torch.optim.AdamW(model.user.parameters(),lr=5e-7,weight_decay=.01);rng=random.Random(43)
        anchor={k:v.detach().clone() for k,v in model.user.named_parameters()}
        record=result['runs'].setdefault(name,{'pooling':pooling,'hard':hard,'extra_head':extra,'checkpoints':[]})
        if resume or (directory/'last.pt').exists():
            state=torch.load(directory/'last.pt',map_location='cpu',weights_only=True)
            assert state['config']['pooling']==pooling
            model.load_state_dict(state['model']);optimizer.load_state_dict(state['optimizer']);rng.setstate(state['rng']);start=state['step']
        began=time.time()
        for step in range(start+1,end+1):
            model.train();optimizer.zero_grad(set_to_none=True)
            batch=compact_batch(examples,order[(step-1)*128:step*128],items,offsets)
            h,mask=history_tensor(batch,'cuda');request=model.encode_user(vectors[h],mask)
            # 随机流固定，额外矿池使用独立rng，保证各组随机负样本一致。
            uniform=negatives(batch,rng,len(vectors),excluded,fp,127)
            ids=sample_hard_ids(batch,request,vectors,random.Random(100000+step),excluded,fp,uniform) if hard else uniform
            ids=torch.tensor(ids,device='cuda')
            loss,scores=head_loss(request,vectors[ids],extra,hard_weight=.1 if 'soft_hard' in name else 1.)
            loss=loss+.01*sum((v-anchor[k]).square().sum() for k,v in model.user.named_parameters())
            assert bool(torch.isfinite(loss));loss.backward();torch.nn.utils.clip_grad_norm_(model.user.parameters(),5);optimizer.step()
            if step%200==0 or step==1:
                health();progress={'state':'TRAINING','run':name,'step':step,'steps':end,'full_steps':total,'pid':os.getpid(),
                    'loss':float(loss.detach()),'hard_above_positive':float((scores[:,1:].max(1).values>scores[:,0]).float().mean()),'seconds':time.time()-began}
                save(ROOT/'progress.json',progress);print(json.dumps(progress),flush=True)
            if step%1000==0 or step==end:
                payload={'model':model.state_dict(),'config':{**source['config'],'pooling':pooling,'hidden':256,'id_dim':0,'history_half_life_days':0},
                    'optimizer':optimizer.state_dict(),'rng':rng.getstate(),'step':step,'learning_rate':5e-7,'full_steps':total}
                tmp=directory/'last.tmp';torch.save(payload,tmp);tmp.replace(directory/'last.pt')
            if step in [1000,2000,4000,8000,12000,16000,total] or step==end:
                path=directory/f'step_{step}.pt';torch.save(payload,path)
                ev=evaluate_rec(model,mmap,cohorts,excluded);record['checkpoints'].append({'step':step,'checkpoint':str(path),'evaluation':ev})
                finalists.append((name+'_'+str(step),str(path),ev));save(ROOT/'results.json',result)
                print('EVAL',name,step,{k:v['metrics'] for k,v in ev.items()},flush=True)
        record['state']='COMPLETE';save(ROOT/'results.json',result)
    specs=[('mean_random','mean',False,False),('mean_hard','mean',True,False),
        ('decay_random','decay08',False,False),('decay_hard','decay08',True,False),('decay_hard_head','decay08',True,True),
        ('mean_soft_hard','mean',True,False),('blend_soft_hard','blend_recent',True,False),('cohesion_soft_hard','cohesion',True,False)]
    for spec in specs:train_run(*spec)
    keys=list(cohorts)
    def eligible(x):
        ev=x[2]
        return all(ev[k]['metrics']['mrr']>=.95*baseline[k]['metrics']['mrr'] and ev[k]['metrics']['hit@100']>=baseline[k]['metrics']['hit@100']-.002 and ev[k]['metrics']['hit@10']>=baseline[k]['metrics']['hit@10']-.001 for k in keys) and ev['future_dev']['metrics']['mrr']>=baseline['future_dev']['metrics']['mrr']
    def score(x):
        ratios=[x[2][k]['metrics']['mrr']/baseline[k]['metrics']['mrr'] for k in keys]
        return (min(ratios),x[2]['future_dev']['metrics']['mrr'],x[2]['future_dev']['metrics']['hit@10'],sum(ratios))
    # 筛选最好的已训练配置续跑余下同一epoch，不以封存决定是否续跑。
    trained=[x for x in finalists if not x[0].startswith('initial_') and eligible(x)]
    if trained:
        best=max(trained,key=score);name=best[0].rsplit('_',1)[0]
        save(ROOT/'screen_selection.json',{'state':'FROZEN_HYPERPARAMETERS','run':name,'checkpoint':best[1],'rule':result['plan']})
        spec=next(s for s in specs if s[0]==name);train_run(*spec,end=total,resume=True)
    chosen=max(filter(eligible,finalists),key=score)
    save(ROOT/'selection.json',{'state':'FROZEN','selected':chosen[0],'checkpoint':chosen[1],'development':chosen[2],'rule':result['plan'],'timestamp':time.time()})
    state=torch.load(chosen[1],map_location='cpu',weights_only=True);model.load_state_dict(state['model']);model.pooling=state['config']['pooling']
    for k,v in model.state_dict().items():
        if not k.startswith('user.'):assert torch.equal(v.cpu(),source['model'][k])
    cohorts.clear();cohorts['sealed_future']=rows(ROOT/'data/sealed_future.jsonl')
    sealed={'candidate':evaluate_rec(model,mmap,cohorts,excluded)}
    model.load_state_dict(source['model']);model.pooling='mean';sealed['initial']=evaluate_rec(model,mmap,cohorts,excluded)
    old=torch.load(V4/'export_joint_full_seed42/model.pt',map_location='cpu',weights_only=True);model.load_state_dict(old['model'])
    sealed['online_expanded']=evaluate_rec(model,np.load(V7/'online_v4_item_vectors.npy',mmap_mode='r'),cohorts,excluded)
    sealed['online_actual']=evaluate_rec(model,np.load(V4/'export_joint_full_seed42/item_vectors.npy',mmap_mode='r'),cohorts,excluded,False)
    result.update(state='COMPLETE',selected=chosen[0],sealed=sealed,peak_cuda_gib=torch.cuda.max_memory_allocated()/2**30)
    save(ROOT/'results.json',result);save(ROOT/'progress.json',{'state':'COMPLETE','selected':chosen[0]})
if __name__=='__main__':
    try:main()
    except Exception as e:save(ROOT/'failure.json',{'error':repr(e),'timestamp':time.time()});raise
