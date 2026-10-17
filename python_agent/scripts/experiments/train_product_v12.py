"""全训练期序列、排序蒸馏和降权困难负例；选型冻结后才打开新未来验收。"""
import hashlib,json,math,os,random,time
from pathlib import Path
import numpy as np
import torch
import torch.nn.functional as F
from three_tower_residual import ResidualTowers,history_tensor,rows
from product_v10_model import SequenceResidualTowers,sample_hard_ids,head_loss
from product_v12_distillation import ranking_distillation,teacher_candidates
from train_product_v10 import evaluate_rec
from train_product_v9 import compact_batch
from train_product_v8 import negatives,health
from evaluate_product_v7_catalog import save

BASE=Path('/mnt/data/luo/remote_runs');ROOT=BASE/'product_v12_training'
V7=BASE/'product_v7_expansion';V9=BASE/'product_v9_training';V4=BASE/'three_tower_dataset_v4'

def main():
    assert os.environ.get('CUDA_VISIBLE_DEVICES')=='2'
    torch.set_num_threads(2);torch.set_num_interop_threads(1);torch.cuda.set_per_process_memory_fraction(.25)
    torch.backends.cuda.matmul.allow_tf32=False;torch.manual_seed(42);health()
    assert not (ROOT/'selection.json').exists(),'模型已冻结，禁止据封存结果续训'
    mmap=np.load(V7/'candidate_v6_item_vectors.npy',mmap_mode='r')
    vectors=torch.empty(mmap.shape,device='cuda')
    for s in range(0,len(vectors),8192):vectors[s:s+8192].copy_(torch.tensor(np.asarray(mmap[s:s+8192])))
    old_vectors=np.load(V4/'export_joint_full_seed42/item_vectors.npy',mmap_mode='r')
    old=torch.load(V4/'export_joint_full_seed42/model.pt',map_location='cpu',weights_only=True)
    teacher=ResidualTowers(1024,256,len(old_vectors),0).cuda().eval();teacher.load_state_dict(old['model']);teacher.requires_grad_(False)
    excluded={r['index'] for r in json.loads((V7/'data/text_audit.json').read_text())['ineligible']}
    fp=np.empty(len(vectors),dtype='uint64')
    with (V7/'data/items.jsonl').open() as f:
        for i,line in enumerate(f):fp[i]=int.from_bytes(hashlib.sha256(json.loads(line)['text'].strip().encode()).digest()[:8],'big')
    examples=np.load(V9/'data/train_examples.npy',mmap_mode='r');items=np.load(V9/'data/sequence_items.npy',mmap_mode='r');offsets=np.load(V9/'data/sequence_offsets.npy',mmap_mode='r')
    order=np.random.default_rng(42).permutation(len(examples));total=math.ceil(len(order)/128)
    cohorts={'existing_dev':rows(V7/'data/rec_dev.jsonl'),'fresh_dev':rows(V9/'data/fresh_dev.jsonl'),
             'future_short_dev':rows(BASE/'product_v10_training/data/future_dev.jsonl'),'future_dev':rows(ROOT/'data/future_dev.jsonl')}
    probe=json.loads((ROOT/'probe.json').read_text());assert probe['state']=='COMPLETE'
    baseline=probe['variants']['v6_cohesion']['evaluation'];keys=list(cohorts)
    def eligible(ev):
        return all(ev[k]['metrics']['mrr']>=.95*baseline[k]['metrics']['mrr'] and ev[k]['metrics']['hit@100']>=baseline[k]['metrics']['hit@100']-.002 and ev[k]['metrics']['hit@10']>=baseline[k]['metrics']['hit@10']-.001 for k in keys) and all(ev[k]['metrics']['mrr']>=baseline[k]['metrics']['mrr'] for k in ['future_dev','future_short_dev'])
    def score(ev):
        ratios=[ev[k]['metrics']['mrr']/baseline[k]['metrics']['mrr'] for k in keys]
        return (min(ratios),sum(ratios),ev['future_dev']['metrics']['hit@100'])
    starts=[(n,v) for n,v in probe['variants'].items() if eligible(v['evaluation'])]
    start_name,start=max(starts,key=lambda x:score(x[1]['evaluation']))
    source=torch.load(start['checkpoint'],map_location='cpu',weights_only=True)
    save(ROOT/'training_start.json',{'state':'FIXED','selected':start_name,'checkpoint':start['checkpoint'],
                                    'scope':'仅固定开发比较，未打开新封存','timestamp':time.time()})
    model=SequenceResidualTowers(1024,256,len(vectors),0,pooling=source['config']['pooling']).cuda()
    result={'state':'TRAINING','start':start_name,'baseline':baseline,'runs':{},'plan':{
        'screen_steps':2000,'full_steps':total,'train_examples':len(examples),'batch':128,'learning_rate':2e-6,
        'distillation':'同一训练前缀的现网用户向量，在4096旧商品随机池中取前64项，KL对齐相对得分；已见商品排除，旧历史为空不参与。现网教师冻结；未来标签完全不进入梯度。',
        'selection':'四开发MRR>=初始95%、Hit100最多降0.2百分点、Hit10最多降0.1百分点；两个未来开发MRR不退；最大化最小MRR比，再总比。保留所有固定权重候选。',
        'frozen':['BGE','item','query'],'trainable':'user MLP','online_modified':False}}
    if (ROOT/'results.json').exists():result=json.loads((ROOT/'results.json').read_text())
    finalists=[(n,v['checkpoint'],v['evaluation']) for n,v in starts]
    for name,r in result['runs'].items():
        for e in r['checkpoints']:finalists.append((name+'_'+str(e['step']),e['checkpoint'],e['evaluation']))
    def run(name,distill,hard,end=2000):
        directory=ROOT/name;directory.mkdir(exist_ok=True)
        model.load_state_dict(source['model']);model.requires_grad_(False);model.user.requires_grad_(True)
        optimizer=torch.optim.AdamW(model.user.parameters(),lr=2e-6,weight_decay=.01);rng=random.Random(43);start_step=0
        record=result['runs'].setdefault(name,{'distillation':distill,'hard':hard,'checkpoints':[]})
        if (directory/'last.pt').exists():
            state=torch.load(directory/'last.pt',map_location='cpu',weights_only=True)
            model.load_state_dict(state['model']);optimizer.load_state_dict(state['optimizer']);rng.setstate(state['rng']);start_step=state['step']
        began=time.time()
        for step in range(start_step+1,end+1):
            optimizer.zero_grad(set_to_none=True);model.train()
            batch=compact_batch(examples,order[(step-1)*128:step*128],items,offsets)
            h,mask=history_tensor(batch,'cuda');request=model.encode_user(vectors[h],mask)
            uniform=negatives(batch,rng,len(vectors),excluded,fp,127)
            neg=sample_hard_ids(batch,request,vectors,random.Random(100000+step),excluded,fp,uniform) if hard else uniform
            neg=torch.tensor(neg,device='cuda');ce,_=head_loss(request,vectors[neg],hard_weight=.05 if hard else 1.)
            kl=torch.zeros((),device='cuda')
            if distill:
                histories=[[i for i in r['history'] if i<len(old_vectors)] for r in batch]
                active=torch.tensor([bool(hh) for hh in histories],device='cuda')
                teacher_batch=[{'history':hh or [0]} for hh in histories]
                th,tm=history_tensor(teacher_batch,'cuda')
                with torch.no_grad():
                    tv=torch.tensor(np.asarray(old_vectors[th.cpu().numpy()]),device='cuda')
                    tq=teacher.encode_user(tv,tm)
                    pool=torch.tensor(random.Random(200000+step).sample(range(len(old_vectors)),4096),device='cuda')
                    pv=torch.tensor(np.asarray(old_vectors[pool.cpu().numpy()]),device='cuda')
                    ids,teacher_scores=teacher_candidates(tq,pool,pv,batch,active)
                kl=ranking_distillation(request,tq,vectors[ids],teacher_scores,active)
            loss=ce+distill*kl
            assert bool(torch.isfinite(loss));loss.backward();torch.nn.utils.clip_grad_norm_(model.user.parameters(),5);optimizer.step()
            if step==1 or step%200==0:
                health();progress={'state':'TRAINING','run':name,'step':step,'steps':end,'full_steps':total,'pid':os.getpid(),
                                  'loss':float(loss.detach()),'ce':float(ce.detach()),'kl':float(kl.detach()),'seconds':time.time()-began,
                                  'cuda_reserved_gib':torch.cuda.memory_reserved()/2**30}
                save(ROOT/'progress.json',progress);print(json.dumps(progress),flush=True)
            if step%500==0 or step==end:
                payload={'model':model.state_dict(),'config':source['config'],'optimizer':optimizer.state_dict(),
                         'rng':rng.getstate(),'step':step,'full_steps':total,'learning_rate':2e-6}
                tmp=directory/'last.tmp';torch.save(payload,tmp);tmp.replace(directory/'last.pt')
            if step in [500,2000,5000,10000,15000,total] or step==end:
                path=directory/f'step_{step}.pt';torch.save(payload,path)
                ev=evaluate_rec(model,mmap,cohorts,excluded);record['checkpoints'].append({'step':step,'checkpoint':str(path),'evaluation':ev})
                finalists.append((name+'_'+str(step),str(path),ev));save(ROOT/'results.json',result)
                print('V12_EVAL',name,step,{k:v['metrics'] for k,v in ev.items()},flush=True)
        record['state']='COMPLETE';save(ROOT/'results.json',result)
    specs=[('random',0.,False),('distill_random',1.,False),('distill_soft_hard',1.,True)]
    for spec in specs:run(*spec)
    trained=[x for x in finalists if x[0].rsplit('_',1)[0] in {s[0] for s in specs} and eligible(x[2])]
    if trained:
        best=max(trained,key=lambda x:score(x[2]));name=best[0].rsplit('_',1)[0]
        save(ROOT/'screen_selection.json',{'state':'FIXED','run':name,'scope':'仅开发选参','timestamp':time.time()})
        run(*next(s for s in specs if s[0]==name),end=total)
    chosen=max((x for x in finalists if eligible(x[2])),key=lambda x:score(x[2]))
    save(ROOT/'selection.json',{'state':'FROZEN','selected':chosen[0],'checkpoint':chosen[1],'development':chosen[2],
                              'rule':result['plan'],'timestamp':time.time()})
    state=torch.load(chosen[1],map_location='cpu',weights_only=True);model.load_state_dict(state['model']);model.pooling=state['config']['pooling']
    for k,v in state['model'].items():
        if not k.startswith('user.'):assert torch.equal(v,source['model'][k])
    cohorts={'sealed_future':rows(ROOT/'data/sealed_future.jsonl')}
    sealed={'candidate':evaluate_rec(model,mmap,cohorts,excluded)}
    model.load_state_dict(source['model']);model.pooling=source['config']['pooling'];sealed['initial']=evaluate_rec(model,mmap,cohorts,excluded)
    model.load_state_dict(old['model']);model.pooling='mean'
    sealed['online_expanded']=evaluate_rec(model,np.load(V7/'online_v4_item_vectors.npy',mmap_mode='r'),cohorts,excluded)
    sealed['online_actual']=evaluate_rec(model,old_vectors,cohorts,excluded,False)
    result.update(state='COMPLETE',selected=chosen[0],sealed=sealed,peak_cuda_gib=torch.cuda.max_memory_allocated()/2**30)
    save(ROOT/'results.json',result);save(ROOT/'progress.json',{'state':'COMPLETE','selected':chosen[0]})

if __name__=='__main__':
    try:main()
    except Exception as e:save(ROOT/'failure.json',{'error':repr(e),'time':time.time()});raise
