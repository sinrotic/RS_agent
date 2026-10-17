"""全量用户、紧凑前缀样本的GPU2训练；固定商品/查询，双开发集约束和封存用户验收。"""
import hashlib,json,math,os,random,time
from pathlib import Path
import numpy as np
import torch
import torch.nn.functional as F
from three_tower_residual import ResidualTowers,history_tensor,rows,paired_interval
from evaluate_product_v7_catalog import build_requests,exact_ranks,summarize,save
from train_product_v8 import negatives,sampled_loss,health
ROOT=Path('/mnt/data/luo/remote_runs/product_v9_training')
V7=Path('/mnt/data/luo/remote_runs/product_v7_expansion')
V8=Path('/mnt/data/luo/remote_runs/product_v8_training')
OLD=Path('/mnt/data/luo/remote_runs/three_tower_dataset_v4/data')

def compact_batch(examples,indices,items,offsets):
    output=[]
    for index in indices:
        user,j,end=map(int,examples[index]);sequence=items[offsets[user]:offsets[user+1]]
        output.append({'target':int(sequence[j]),'history':sequence[max(0,end-50):end].tolist(),'known_train_positives':sequence.tolist()})
    return output

def main():
    assert os.environ.get('CUDA_VISIBLE_DEVICES')=='2'
    torch.set_num_threads(2);torch.set_num_interop_threads(1);torch.cuda.set_per_process_memory_fraction(.20);torch.backends.cuda.matmul.allow_tf32=False
    health();torch.manual_seed(42)
    data=ROOT/'data';manifest=json.loads((data/'manifest.json').read_text());assert manifest['state']=='COMPLETE'
    examples=np.load(data/'train_examples.npy',mmap_mode='r');items=np.load(data/'sequence_items.npy',mmap_mode='r');offsets=np.load(data/'sequence_offsets.npy',mmap_mode='r')
    source=torch.load(V7/'export_candidate_v6/model.pt',map_location='cpu',weights_only=True)
    calibrated=torch.load(V8/'uniform/query_400.pt',map_location='cpu',weights_only=True)
    source['model'].update({k:v for k,v in calibrated['model'].items() if k.startswith('query.')})
    torch.save({'model':source['model'],'config':source['config']},ROOT/'initial.pt')
    vectors_mmap=np.load(V7/'candidate_v6_item_vectors.npy',mmap_mode='r')
    vectors=torch.empty(vectors_mmap.shape,device='cuda')
    for s in range(0,len(vectors),8192):vectors[s:s+8192].copy_(torch.tensor(np.asarray(vectors_mmap[s:s+8192])))
    excluded={r['index'] for r in json.loads((V7/'data/text_audit.json').read_text())['ineligible']}
    fp=np.empty(len(vectors),dtype='uint64')
    with (V7/'data/items.jsonl').open() as f:
        for i,line in enumerate(f):fp[i]=int.from_bytes(hashlib.sha256(json.loads(line)['text'].strip().encode()).digest()[:8],'big')
    cohorts={'existing_dev':rows(V7/'data/rec_dev.jsonl'),'fresh_dev':rows(data/'fresh_dev.jsonl')}
    semantic=rows(OLD/'semantic_clean.jsonl');queries=F.normalize(torch.tensor(np.load(OLD/'query_features.npy')),dim=-1).numpy()
    model=ResidualTowers(1024,256,len(vectors),0).cuda()
    @torch.inference_mode()
    def evaluate(universe=vectors_mmap,expanded=True):
        model.eval();req,t,h,pos,out=build_requests(model,universe,cohorts,semantic,queries,expanded,excluded)
        ranks,_=exact_ranks(req,universe,t,h,excluded=excluded)
        for (k,i),rank in zip(pos,ranks):out[k]['ranks'][i]=rank
        return summarize(out)
    model.load_state_dict(source['model']);baseline=evaluate()
    online=torch.load(OLD.parent/'export_joint_full_seed42/model.pt',map_location='cpu',weights_only=True)
    model.load_state_dict(online['model'])
    online_expanded=evaluate(np.load(V7/'online_v4_item_vectors.npy',mmap_mode='r'))
    online_actual=evaluate(np.load(OLD.parent/'export_joint_full_seed42/item_vectors.npy',mmap_mode='r'),False)
    result={'state':'TRAINING','data':manifest,'baseline':baseline,'online_expanded':online_expanded,'online_actual':online_actual,
        'plan':'各完整遍历2656780样本一次；用户塔lr2e-6与5e-7，batch128，127全库随机负例；商品/查询冻结；两开发群体Hit100不低于基线0.1个百分点且MRR不低于98%，最大化两群体最小MRR相对基线比例。仅最后封存验收。', 'runs':{}}
    if (ROOT/'results.json').exists():result=json.loads((ROOT/'results.json').read_text())
    finalists=[('initial',str(ROOT/'initial.pt'),baseline)]
    order=np.random.default_rng(42).permutation(len(examples));steps=math.ceil(len(order)/128)
    for name,lr in [('full_lr2e6',2e-6),('full_lr5e7',5e-7)]:
        directory=ROOT/name;directory.mkdir(exist_ok=True)
        model.load_state_dict(source['model']);model.requires_grad_(False);model.user.requires_grad_(True)
        optimizer=torch.optim.AdamW(model.user.parameters(),lr=lr,weight_decay=.01);rng=random.Random(43)
        anchor={k:v.detach().clone() for k,v in model.user.named_parameters()}
        record=result['runs'].setdefault(name,{'checkpoints':[]});start_step=0
        if (directory/'last.pt').exists():
            checkpoint=torch.load(directory/'last.pt',map_location='cpu',weights_only=True)
            assert checkpoint['learning_rate']==lr and checkpoint['total_steps']==steps
            model.load_state_dict(checkpoint['model']);optimizer.load_state_dict(checkpoint['optimizer']);rng.setstate(checkpoint['rng']);start_step=checkpoint['step']
        for entry in record['checkpoints']:finalists.append((name+'_'+str(entry['step']),entry['checkpoint'],entry['evaluation']))
        began=time.time()
        for step in range(start_step+1,steps+1):
            model.train();optimizer.zero_grad(set_to_none=True)
            batch=compact_batch(examples,order[(step-1)*128:step*128],items,offsets)
            ids=torch.tensor(negatives(batch,rng,len(vectors),excluded,fp,127),device='cuda')
            h,mask=history_tensor(batch,'cuda');request=model.encode_user(vectors[h],mask)
            loss=sampled_loss(request,vectors[ids],False)+.01*sum((v-anchor[k]).square().sum() for k,v in model.user.named_parameters())
            assert bool(torch.isfinite(loss));loss.backward();torch.nn.utils.clip_grad_norm_(model.user.parameters(),5);optimizer.step()
            if step%200==0 or step==1:
                health();progress={'state':'TRAINING','run':name,'step':step,'steps':steps,'examples_seen':min(step*128,len(order)),
                    'seconds_this_process':time.time()-began,'loss':float(loss.detach()),'pid':os.getpid()}
                save(ROOT/'progress.json',progress);print(json.dumps(progress),flush=True)
            if step%1000==0 or step==steps:
                checkpoint={'model':model.state_dict(),'config':source['config'],'optimizer':optimizer.state_dict(),'rng':rng.getstate(),'step':step,'learning_rate':lr,'total_steps':steps}
                temporary=directory/'last.tmp';torch.save(checkpoint,temporary);temporary.replace(directory/'last.pt')
            if step%5000==0 or step==steps:
                path=directory/f'step_{step}.pt';torch.save(checkpoint,path)
                evaluation=evaluate();entry={'step':step,'checkpoint':str(path),'evaluation':evaluation}
                record['checkpoints'].append(entry);finalists.append((name+'_'+str(step),str(path),evaluation));save(ROOT/'results.json',result)
                print('EVAL',name,step,{k:v['metrics'] for k,v in evaluation.items() if k.endswith('full_history')},flush=True)
        record['state']='COMPLETE';save(ROOT/'results.json',result)
    keys=['existing_dev/expanded_full_history','fresh_dev/expanded_full_history']
    def eligible(x):
        return all(x[2][k]['metrics']['hit@100']>=baseline[k]['metrics']['hit@100']-.001 and x[2][k]['metrics']['mrr']>=.98*baseline[k]['metrics']['mrr'] for k in keys)
    def score(x):
        ratios=[x[2][k]['metrics']['mrr']/baseline[k]['metrics']['mrr'] for k in keys]
        return (min(ratios),sum(x[2][k]['metrics']['hit@100'] for k in keys),sum(ratios))
    chosen=max(filter(eligible,finalists),key=score)
    save(ROOT/'selection.json',{'state':'FROZEN','selected':chosen[0],'checkpoint':chosen[1],'development':chosen[2],'timestamp':time.time(),'rule':result['plan']})
    model.load_state_dict(torch.load(chosen[1],map_location='cpu',weights_only=True)['model'])
    for key,value in model.state_dict().items():
        if not key.startswith('user.'):assert torch.equal(value.cpu(),source['model'][key])
    # 仅在选型冻结后读取封存群体；不能据其结果换成另一checkpoint。
    cohorts.clear();cohorts['sealed']=rows(data/'sealed_users.jsonl')
    sealed={'candidate':evaluate()}
    model.load_state_dict(source['model']);sealed['initial']=evaluate()
    model.load_state_dict(online['model']);sealed['online_expanded']=evaluate(np.load(V7/'online_v4_item_vectors.npy',mmap_mode='r'))
    sealed['online_actual']=evaluate(np.load(OLD.parent/'export_joint_full_seed42/item_vectors.npy',mmap_mode='r'),False)
    result.update(state='COMPLETE',selected=chosen[0],sealed=sealed,peak_cuda_gib=torch.cuda.max_memory_allocated()/2**30)
    save(ROOT/'results.json',result);save(ROOT/'progress.json',{'state':'COMPLETE','selected':chosen[0]})

if __name__=='__main__':
    try:main()
    except Exception as e:
        save(ROOT/'failure.json',{'error':repr(e),'time':time.time()});raise
