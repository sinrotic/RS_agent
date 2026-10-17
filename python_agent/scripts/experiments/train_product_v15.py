"""完整三轮联合训练三塔MLP；固定BGE，取消旧头部保护，完成整轮后选择模型。"""
import hashlib,json,math,os,random,time,urllib.request
from pathlib import Path
import numpy as np
import torch
import torch.nn.functional as F
from three_tower_residual import rows,history_tensor,metrics
from product_v10_model import SequenceResidualTowers
from product_v15_joint import joint_loss
from train_product_v10 import evaluate_rec
from train_product_v9 import compact_batch
from train_product_v8 import negatives
from evaluate_product_v7_catalog import exact_ranks,save

BASE=Path('/mnt/data/luo/remote_runs');ROOT=BASE/'product_v15_training';V7=BASE/'product_v7_expansion';V9=BASE/'product_v9_training';V4=BASE/'three_tower_dataset_v4'
EPOCHS=3;BATCH=128;SEMANTIC_EVERY=10;SEMANTIC_WEIGHT=.1
RATES={'item':1e-7,'user':2e-7,'query':1e-6}

def health():
    for url in ['http://127.0.0.1:18213/actuator/health/readiness','http://172.21.0.1:18132/health']:
        with urllib.request.urlopen(url,timeout=5) as f:assert json.load(f)['status']=='UP'

@torch.inference_mode()
def export_raw_vectors(model,features,path):
    mmap=np.lib.format.open_memmap(path,mode='w+',dtype='float32',shape=tuple(features.shape))
    model.eval()
    for s in range(0,len(features),4096):
        v=model.encode_items(features[s:s+4096])
        assert bool(torch.isfinite(v).all()) and bool((v.norm(dim=1)-1).abs().max()<1e-4)
        mmap[s:s+len(v)]=v.cpu().numpy()
    mmap.flush();return mmap

@torch.inference_mode()
def evaluate_semantic(model,vectors,semantic,queries):
    selected=[i for i,r in enumerate(semantic) if r['split']=='valid']
    encoded=[]
    for s in range(0,len(selected),64):encoded.extend(model.encode_query(queries[selected[s:s+64]]).unbind())
    ranks,error=exact_ranks(torch.stack(encoded),vectors,[semantic[i]['item_index'] for i in selected],[[] for _ in selected])
    return {'metrics':metrics(ranks),'ranks':ranks,'target_score_replay_error':error}

def select_full_epoch(result):
    """按完整整轮开发指标选型；离散命中门槛使用整数，避免1ULP误淘汰。"""
    future=[k for k in result['baseline'] if k.startswith('future')]
    base=result['baseline_semantic']['metrics'];floor=round(base['hit@10']*base['count'])-2
    candidates=[r for r in result['epochs'] if round(r['semantic']['metrics']['hit@10']*r['semantic']['metrics']['count'])>=floor]
    if not candidates:raise RuntimeError('完整训练完成，但全部整轮检查点语义退步超过门槛；不发布')
    def score(record):
        ratios=[record['evaluation'][k]['metrics']['mrr']/result['baseline'][k]['metrics']['mrr'] for k in future]
        return min(ratios),sum(ratios)/len(ratios),record['evaluation']['future_dev']['metrics']['hit@100']
    return max(candidates,key=score)

def main():
    assert os.environ.get('CUDA_VISIBLE_DEVICES') in ['1','2']
    torch.set_num_threads(2);torch.set_num_interop_threads(1);torch.cuda.set_per_process_memory_fraction(.35)
    torch.backends.cuda.matmul.allow_tf32=False;torch.manual_seed(42);health()
    assert not (ROOT/'selection.json').exists(),'模型已冻结，禁止根据封存续训'
    while not (ROOT/'data/manifest.json').exists():time.sleep(5)
    data=json.loads((V9/'data/manifest.json').read_text());assert data['state']=='COMPLETE'
    examples=np.load(V9/'data/train_examples.npy',mmap_mode='r');items=np.load(V9/'data/sequence_items.npy',mmap_mode='r');offsets=np.load(V9/'data/sequence_offsets.npy',mmap_mode='r')
    total=math.ceil(len(examples)/BATCH);goal=EPOCHS*total
    mmap=np.load(V7/'data/item_features.npy',mmap_mode='r');features=torch.empty(mmap.shape,device='cuda')
    for s in range(0,len(features),8192):features[s:s+8192]=F.normalize(torch.tensor(np.asarray(mmap[s:s+8192]),device='cuda'),dim=-1)
    source_path=BASE/'product_v14_training/export/model.pt';source=torch.load(source_path,map_location='cpu',weights_only=True)
    teacher=SequenceResidualTowers(1024,256,len(features),0,pooling='cohesion').cuda().eval();teacher.load_state_dict(source['model']);teacher.requires_grad_(False)
    model=SequenceResidualTowers(1024,256,len(features),0,pooling='cohesion').cuda();model.load_state_dict(source['model'])
    initial_vectors=np.load(V7/'candidate_v6_item_vectors.npy',mmap_mode='r')
    with torch.inference_mode():assert np.allclose(teacher.encode_items(features[:32]).cpu().numpy(),initial_vectors[:32],atol=2e-6)
    excluded={r['index'] for r in json.loads((V7/'data/text_audit.json').read_text())['ineligible']}
    fingerprints=np.empty(len(features),dtype='uint64')
    with (V7/'data/items.jsonl').open() as f:
        for i,line in enumerate(f):fingerprints[i]=int.from_bytes(hashlib.sha256(json.loads(line)['text'].strip().encode()).digest()[:8],'big')
    semantic=rows(V4/'data/semantic_clean.jsonl')
    queries=F.normalize(torch.tensor(np.load(V4/'data/query_features.npy'),device='cuda'),dim=-1)
    sem_indices=[i for i,r in enumerate(semantic) if r['split']=='train'];known={}
    for i in sem_indices:known.setdefault(semantic[i]['query'].strip().lower(),set()).add(semantic[i]['item_index'])
    sem_train=[{'target':semantic[i]['item_index'],'known_train_positives':list(known[semantic[i]['query'].strip().lower()]),'query_index':i} for i in sem_indices]
    cohorts={'existing_dev':rows(V7/'data/rec_dev.jsonl'),'fresh_dev':rows(V9/'data/fresh_dev.jsonl'),
             'future_short_dev':rows(BASE/'product_v10_training/data/future_dev.jsonl'),
             'future_snapshot_dev':rows(BASE/'product_v12_training/data/future_dev.jsonl'),
             'future_rolling13_dev':rows(BASE/'product_v13_training/data/future_dev.jsonl'),
             'future_rolling14_dev':rows(BASE/'product_v14_training/data/future_dev.jsonl'),
             'future_dev':rows(ROOT/'data/future_dev.jsonl')}
    plan={'state':'FIXED_BEFORE_TRAINING','epochs':EPOCHS,'train_examples_per_epoch':len(examples),'train_users':data['train_users'],
          'batch':BATCH,'rec_steps_per_epoch':total,'total_rec_steps':goal,'learning_rates':RATES,
          'scheduler':'500推荐步warmup，之后cosine到20%基础学习率','semantic_every':SEMANTIC_EVERY,'semantic_weight':SEMANTIC_WEIGHT,
          'semantic_train_queries':len(sem_train),'negative_count':127,'negative_policy':'全词表随机，排除整个train用户正序列、空文本、同文本目标副本；负例是未观测商品，不等于真实不喜欢。',
          'initial_checkpoint':str(source_path),'initial_sha256':hashlib.sha256(source_path.read_bytes()).hexdigest(),
          'frozen':['BGE-M3'],'trained':['item MLP','user MLP','query MLP'],'pooling':'固定一致性聚合，<=2历史用均值，温度0.15',
          'old_head_protection':0,'old_model_teacher':False,'anchor_teacher':'起始纯三塔固定表示，非旧v4保护模型',
          'selection':'只从完成整轮的epoch1/2/3检查点选择；优先五个未来开发MRR最小相对起始值，再均值和Hit100。语义Hit10最多丢2条开发查询。历史测试不参与选择。',
          'release_policy':'纯三塔独立 serving。新封存MRR至少起始纯三塔95%，Hit10至少90%，Hit100至少98%；历史MRR至少起始纯三塔95%，Hit10不低于起始纯三塔17人；语义与工程隔离验收后发布。当前带保护路线只作同群体比较，不强制保留旧头部零退步门槛。',
          'gpu':'physical GPU'+os.environ['CUDA_VISIBLE_DEVICES']+'，显存上限约8.6GB','online_modified':False,'timestamp':time.time()}
    if not (ROOT/'experiment_plan.json').exists():save(ROOT/'experiment_plan.json',plan)
    else:
        previous=json.loads((ROOT/'experiment_plan.json').read_text())
        for k in ['epochs','train_examples_per_epoch','learning_rates','semantic_every','initial_sha256']:assert previous[k]==plan[k]
    result={'state':'TRAINING','plan':plan,'epochs':[]}
    if (ROOT/'results.json').exists():result=json.loads((ROOT/'results.json').read_text())
    if 'baseline' not in result:
        result['baseline']=evaluate_rec(teacher,initial_vectors,cohorts,excluded)
        result['baseline_semantic']=evaluate_semantic(teacher,initial_vectors,semantic,queries);save(ROOT/'results.json',result)
    optimizer=torch.optim.AdamW([{'params':getattr(model,n).parameters(),'lr':lr,'name':n,'weight_decay':.01} for n,lr in RATES.items()])
    rng=random.Random(43);srng=random.Random(44);first_epoch=1;first_step=0;global_step=0;semantic_steps=0
    if (ROOT/'last.pt').exists():
        state=torch.load(ROOT/'last.pt',map_location='cpu',weights_only=True)
        model.load_state_dict(state['model']);optimizer.load_state_dict(state['optimizer']);rng.setstate(state['rng']);srng.setstate(state['semantic_rng'])
        first_epoch=state['epoch'];first_step=state['step_in_epoch'];global_step=state['rec_steps'];semantic_steps=state['semantic_steps']
    config={**source['config'],'pooling':'cohesion','mode':'full_joint','epochs':EPOCHS,'trained_towers':['item','user','query'],'old_head_protection':0}
    began=time.time();steps_this_process=0
    def payload(epoch,step):
        return {'model':model.state_dict(),'config':config,'optimizer':optimizer.state_dict(),'rng':rng.getstate(),'semantic_rng':srng.getstate(),
                'epoch':epoch,'step_in_epoch':step,'rec_steps':global_step,'semantic_steps':semantic_steps,'rec_steps_per_epoch':total,'total_epochs':EPOCHS}
    for epoch in range(first_epoch,EPOCHS+1):
        order=np.random.default_rng(42+epoch).permutation(len(examples));start=first_step if epoch==first_epoch else 0
        assert len(order)==len(examples) and len(np.unique(order))==len(examples)
        for step in range(start+1,total+1):
            global_step=(epoch-1)*total+step;steps_this_process+=1;model.train()
            scale=min(1.,global_step/500)*(.2+.8*(1+math.cos(math.pi*global_step/goal))/2)
            for group in optimizer.param_groups:group['lr']=RATES[group['name']]*scale
            batch=compact_batch(examples,order[(step-1)*BATCH:step*BATCH],items,offsets)
            assert all(r['target'] not in r['history'] and r['target'] not in excluded for r in batch)
            h,mask=history_tensor(batch,'cuda');cand=torch.tensor(negatives(batch,rng,len(features),excluded,fingerprints,127),device='cuda')
            optimizer.zero_grad(set_to_none=True);loss,stats=joint_loss(model,teacher,features,cand,'rec',h,mask)
            assert bool(torch.isfinite(loss));loss.backward();torch.nn.utils.clip_grad_norm_(model.parameters(),5);optimizer.step()
            semantic_loss=None
            if global_step%SEMANTIC_EVERY==0:
                sem_batch=srng.choices(sem_train,k=BATCH);sem_cand=torch.tensor(negatives(sem_batch,srng,len(features),excluded,fingerprints,127),device='cuda')
                optimizer.zero_grad(set_to_none=True);semantic_loss,_=joint_loss(model,teacher,features,sem_cand,'semantic',query_features=queries[[r['query_index'] for r in sem_batch]])
                assert bool(torch.isfinite(semantic_loss));(SEMANTIC_WEIGHT*semantic_loss).backward();torch.nn.utils.clip_grad_norm_(model.parameters(),5);optimizer.step();semantic_steps+=1
            if global_step%100==0 or step==1 or step==total:
                elapsed=time.time()-began;eta=(goal-global_step)*elapsed/max(1,steps_this_process)
                p={'state':'TRAINING','task':'full_three_tower_joint','epoch':epoch,'epochs':EPOCHS,'step_in_epoch':step,'rec_steps_per_epoch':total,
                   'rec_steps':global_step,'total_rec_steps':goal,'semantic_steps':semantic_steps,'examples_seen':(epoch-1)*len(examples)+min(step*BATCH,len(examples)),
                   'loss':float(loss.detach()),'ce':float(stats['ce']),'kl':float(stats['kl']),'semantic_loss':float(semantic_loss.detach()) if semantic_loss is not None else None,
                   'learning_rates':{g['name']:g['lr'] for g in optimizer.param_groups},'seconds_this_process':elapsed,'estimated_remaining_seconds':eta,
                   'pid':os.getpid(),'physical_gpu':os.environ['CUDA_VISIBLE_DEVICES'],'cuda_allocated_gib':torch.cuda.memory_allocated()/2**30,'cuda_reserved_gib':torch.cuda.memory_reserved()/2**30,'online_modified':False}
                save(ROOT/'progress.json',p);print(json.dumps(p),flush=True)
            if global_step%1000==0 or step==total:
                health();tmp=ROOT/'last.tmp';torch.save(payload(epoch,step),tmp);tmp.replace(ROOT/'last.pt')
        path=ROOT/f'epoch_{epoch}.pt';torch.save(payload(epoch,total),path)
        vector_path=ROOT/f'epoch_{epoch}_item_vectors.npy';vectors=export_raw_vectors(model,features,vector_path)
        ev=evaluate_rec(model,vectors,cohorts,excluded);sem_ev=evaluate_semantic(model,vectors,semantic,queries)
        record={'epoch':epoch,'checkpoint':str(path),'vectors':str(vector_path),'rec_steps':global_step,'examples_seen_this_epoch':len(order),
                'full_dataset_coverage':1.,'evaluation':ev,'semantic':sem_ev}
        result['epochs']=[r for r in result['epochs'] if r['epoch']!=epoch]+[record];save(ROOT/'results.json',result)
        print('FULL_EPOCH_COMPLETE',epoch,{k:v['metrics'] for k,v in ev.items()},sem_ev['metrics'],flush=True)
        del vectors;torch.cuda.empty_cache()
    assert len(result['epochs'])==EPOCHS and all(r['full_dataset_coverage']==1. for r in result['epochs'])
    chosen=select_full_epoch(result)
    save(ROOT/'selection.json',{'state':'FROZEN','selected':'full_joint_epoch_'+str(chosen['epoch']),'checkpoint':chosen['checkpoint'],
         'vectors':chosen['vectors'],'epoch':chosen['epoch'],'development':chosen['evaluation'],'semantic_development':chosen['semantic'],
         'rule':plan,'timestamp':time.time()})
    state=torch.load(chosen['checkpoint'],map_location='cpu',weights_only=True);model.load_state_dict(state['model'])
    changed={n:any(not torch.equal(v,source['model'][k]) for k,v in state['model'].items() if k.startswith(n+'.')) for n in RATES}
    assert all(changed.values());save(ROOT/'trained_tower_audit.json',{'state':'PASS','changed_towers':changed,'full_epochs_completed':EPOCHS,'source_sha256':plan['initial_sha256']})
    cohorts={'sealed_future':rows(ROOT/'data/sealed_future.jsonl')};vectors=np.load(chosen['vectors'],mmap_mode='r')
    sealed={'candidate':evaluate_rec(model,vectors,cohorts,excluded),'initial':evaluate_rec(teacher,initial_vectors,cohorts,excluded)}
    result.update(state='COMPLETE',selected='full_joint_epoch_'+str(chosen['epoch']),sealed=sealed,peak_cuda_gib=torch.cuda.max_memory_allocated()/2**30)
    save(ROOT/'results.json',result);save(ROOT/'progress.json',{'state':'COMPLETE','selected':result['selected'],'full_epochs_completed':EPOCHS,'rec_steps':goal,'semantic_steps':semantic_steps})

if __name__=='__main__':
    try:main()
    except Exception as e:save(ROOT/'failure.json',{'error':repr(e),'timestamp':time.time()});raise
