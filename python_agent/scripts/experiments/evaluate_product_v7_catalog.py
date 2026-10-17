"""固定两版模型，统一旧/扩展词表与历史条件；两遍分块精确计rank，无ANN误差。"""
import argparse,hashlib,json,os,time
from pathlib import Path
import numpy as np
import torch
import torch.nn.functional as F
from three_tower_residual import ResidualTowers,history_tensor,metrics,paired_interval,rows


def save(path,value):
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(value,ensure_ascii=False,indent=2),encoding='utf-8');tmp.replace(path)


@torch.inference_mode()
def exact_ranks(requests,vectors,targets,histories,block=2048,excluded=()):
    """两遍使用同形状矩阵乘法；从第一遍真实矩阵元素取目标分数，第二遍计数。"""
    device=requests.device;targets=np.asarray(targets,dtype=np.int64)
    assert all(0<=t<len(vectors) and t not in h for t,h in zip(targets,histories))
    assert not set(targets)&set(excluded)
    blocks={};masks={}
    for i,(target,history) in enumerate(zip(targets,histories)):
        blocks.setdefault(int(target//block),[]).append(i)
        for item in history:masks.setdefault(item//block,[]).append((i,item%block))
    thresholds=torch.empty(len(targets),device=device)
    for b,indexes in blocks.items():
        start=b*block;v=torch.tensor(np.asarray(vectors[start:start+block]),device=device)
        scores=requests@v.T;ix=torch.tensor(indexes,device=device);columns=torch.tensor(targets[indexes]-start,device=device)
        thresholds[ix]=scores[ix,columns]
    counts=torch.zeros(len(targets),dtype=torch.long,device=device);max_replay_error=0.
    for start in range(0,len(vectors),block):
        b=start//block;v=torch.tensor(np.asarray(vectors[start:start+block]),device=device);scores=requests@v.T
        if b in blocks:
            indexes=blocks[b];ix=torch.tensor(indexes,device=device);columns=torch.tensor(targets[indexes]-start,device=device)
            max_replay_error=max(max_replay_error,float((scores[ix,columns]-thresholds[ix]).abs().max()))
        if b in masks:
            positions=torch.tensor(masks[b],device=device);scores[positions[:,0],positions[:,1]]=-torch.inf
        blocked=[i-start for i in excluded if start<=i<start+scores.shape[1]]
        if blocked:scores[:,blocked]=-torch.inf
        counts+=(scores>=thresholds[:,None]).sum(1)
    assert max_replay_error==0., 'target scores did not reproduce exactly'
    assert bool((counts>=1).all())
    return counts.cpu().tolist(),max_replay_error


@torch.inference_mode()
def build_requests(model,vectors,cohorts,semantic,queries,expanded,excluded=()):
    device=next(model.parameters()).device;outputs={};requests=[];targets=[];histories=[];positions=[]
    for cohort,batch in cohorts.items():
        scenarios=['expanded_fixed_history','expanded_full_history'] if expanded else ['old_catalog']
        for scenario in scenarios:
            key=cohort+'/'+scenario;records=[]
            for r in batch:
                history=r['history_full'] if scenario=='expanded_full_history' else r['history_old']
                target=r['target'] if expanded else r['old_target']
                history=[i for i in history if i not in excluded]
                if target in excluded:target=-1
                records.append({'history':history,'target':target,'old_target':r['old_target']})
            outputs[key]={'records':records,'ranks':[0]*len(records)}
            usable=[i for i,r in enumerate(records) if r['history'] and r['target']>=0]
            for start in range(0,len(usable),64):
                indexes=usable[start:start+64];selected=[records[i] for i in indexes];ids,mask=history_tensor(selected,device)
                h=torch.tensor(np.asarray(vectors[ids.cpu().numpy()]),device=device)
                encoded=model.encode_user(h,mask)
                requests.extend(encoded.unbind(0));targets.extend(r['target'] for r in selected);histories.extend(r['history'] for r in selected);positions.extend((key,i) for i in indexes)
    selected=[i for i,r in enumerate(semantic) if r['split']=='valid']
    q=model.encode_query(torch.tensor(np.asarray(queries[selected]),device=device))
    requests.extend(q.unbind(0));targets.extend(semantic[i]['item_index'] for i in selected);histories.extend([] for _ in selected);positions.extend(('semantic',i) for i in range(len(selected)))
    outputs['semantic']={'ranks':[0]*len(selected)}
    return torch.stack(requests),targets,histories,positions,outputs


def summarize(outputs):
    result={}
    for key,value in outputs.items():
        entry={'metrics':metrics(value['ranks']),'ranks':value['ranks']}
        if key!='semantic':
            records=value['records'];entry['metrics']['candidate_target_coverage']=sum(r['target']>=0 for r in records)/len(records)
            entry['metrics']['known_history_coverage']=sum(bool(r['history']) for r in records)/len(records)
            entry['target_groups']={name:metrics([rank for r,rank in zip(records,value['ranks']) if predicate(r)]) for name,predicate in [
                ('old_catalog_targets',lambda r:r['old_target']>=0),('newly_covered_targets',lambda r:r['old_target']<0 and r['target']>=0),
                ('still_uncovered_targets',lambda r:r['target']<0)] if any(predicate(r) for r in records)}
        result[key]=entry
    return result


def main(args):
    assert os.environ.get('CUDA_VISIBLE_DEVICES')=='2'
    torch.set_num_threads(2);torch.set_num_interop_threads(1);torch.cuda.set_per_process_memory_fraction(.20);torch.backends.cuda.matmul.allow_tf32=False
    root=args.root;data=root/'data';old=Path('/mnt/data/luo/remote_runs/three_tower_dataset_v4/data');v6=Path('/mnt/data/luo/remote_runs/product_three_tower_v6_20261011')
    manifest=json.loads((data/'manifest.json').read_text());old_count=manifest['old_count'];features=np.load(data/'item_features.npy',mmap_mode='r')
    text_audit=json.loads((data/'text_audit.json').read_text());excluded={r['index'] for r in text_audit['ineligible']}
    assert features.shape==(manifest['total_count'],1024)
    assert json.loads((data/'encoding_progress.json').read_text())['state']=='COMPLETE'
    cohorts={n:rows(data/(n+'.jsonl')) for n in ['rec_dev','rec_confirm']};semantic=rows(old/'semantic_clean.jsonl');queries=F.normalize(torch.tensor(np.load(old/'query_features.npy')),dim=-1).numpy()
    exports={'online_v4':old.parent/'export_joint_full_seed42','candidate_v6':v6/'export_candidate'}
    result={'state':'RUNNING','catalog':manifest,'eligible_candidate_count':manifest['total_count']-len(excluded),'excluded_empty_text':text_audit['ineligible'],'models':{},'scope':'固定checkpoint；旧/扩库共用用户，已复评的valid用户；语义仍为合成开发代理，未读官方test'}
    for name,directory in exports.items():
        started=time.time();checkpoint=torch.load(directory/'model.pt',map_location='cpu',weights_only=True)
        checkpoint_sha=hashlib.sha256((directory/'model.pt').read_bytes()).hexdigest()
        if name=='online_v4':assert checkpoint_sha==json.loads((root/'online_before.json').read_text())[1]['model_sha256']
        model=ResidualTowers(1024,256,len(features),0).cuda().eval();model.load_state_dict(checkpoint['model'],strict=True)
        output=root/(name+'_item_vectors.npy');vectors=np.lib.format.open_memmap(output,mode='w+',dtype='float32',shape=features.shape)
        prefix=np.load(directory/'item_vectors.npy',mmap_mode='r');assert prefix.shape==(old_count,1024)
        for s in range(0,old_count,8192):vectors[s:min(s+8192,old_count)]=prefix[s:min(s+8192,old_count)]
        with torch.inference_mode():
            check=model.encode_items(F.normalize(torch.tensor(np.asarray(features[:32]),device='cuda'),dim=-1)).cpu().numpy()
            assert np.allclose(check,prefix[:32],atol=2e-6)
            for s in range(old_count,len(features),512):
                f=F.normalize(torch.tensor(np.asarray(features[s:s+512]),device='cuda'),dim=-1)
                encoded=model.encode_items(f)
                assert bool(torch.isfinite(encoded).all()) and bool((encoded.norm(dim=-1)-1).abs().max()<1e-4)
                vectors[s:s+len(f)]=encoded.cpu().numpy()
        vectors.flush();evaluations={}
        for expanded in [False,True]:
            universe=vectors if expanded else vectors[:old_count]
            requests,targets,histories,positions,outputs=build_requests(model,universe,cohorts,semantic,queries,expanded,excluded)
            ranks,error=exact_ranks(requests,universe,targets,histories,excluded=excluded)
            for (key,index),rank in zip(positions,ranks):outputs[key]['ranks'][index]=rank
            evaluations['expanded' if expanded else 'old']=summarize(outputs)
            save(root/(name+'_progress.json'),{'stage':'expanded' if expanded else 'old','seconds':time.time()-started,'target_score_replay_error':error})
        for cohort,batch in cohorts.items():
            a=evaluations['old'][cohort+'/old_catalog']['ranks'];b=evaluations['expanded'][cohort+'/expanded_fixed_history']['ranks']
            assert all(after>=before for before,after,r in zip(a,b,batch) if before>0), 'adding candidates cannot improve old target rank with fixed histories'
        reproduction={}
        reference_names={'online_v4':{'rec_dev':'eval_online_v4','rec_confirm':'confirm_online'},'candidate_v6':{'rec_dev':'query_lr1e5','rec_confirm':'confirm_candidate'}}
        for cohort in cohorts:
            reference=json.loads((v6/reference_names[name][cohort]/'results.json').read_text())['final']
            current=evaluations['old'][cohort+'/old_catalog'];delta=current['metrics']['hit@100']-reference['rec']['hit@100']
            reproduction[cohort]={'hit100_delta':delta,'rank_difference_count':sum(a!=b for a,b in zip(current['ranks'],reference['rec_ranks'])),'semantic_hit10_delta':evaluations['old']['semantic']['metrics']['hit@10']-reference['semantic']['hit@10'],
                'note':'分块/全矩阵FP32算子可拆开极近分数；记录差异，Hit100超过1用户需检查'}
            assert abs(delta)<.001 and abs(reproduction[cohort]['semantic_hit10_delta'])<.003, 'old catalog reproduction drift'
        result['models'][name]={'checkpoint_sha256':checkpoint_sha,'evaluations':evaluations,'old_catalog_reproduction':reproduction,'seconds':time.time()-started,'vectors':str(output)}
        save(root/'comparison.json',result);del requests,model,vectors;torch.cuda.empty_cache()
    comparisons={}
    for cohort in cohorts:
        for size,scenario in [('old','old_catalog'),('expanded','expanded_fixed_history'),('expanded','expanded_full_history')]:
            key=cohort+'/'+scenario
            a=result['models']['online_v4']['evaluations'][size][key];b=result['models']['candidate_v6']['evaluations'][size][key]
            comparisons[key]={'candidate_minus_online':paired_interval(a['ranks'],b['ranks']),'mrr_delta':b['metrics']['mrr']-a['metrics']['mrr'],'ndcg_delta':b['metrics']['ndcg@100']-a['metrics']['ndcg@100']}
    result.update(state='COMPLETE',comparisons=comparisons,peak_cuda_gib=torch.cuda.max_memory_allocated()/2**30)
    save(root/'comparison.json',result)
    print(json.dumps({'state':'COMPLETE','comparisons':comparisons},ensure_ascii=False),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);main(p.parse_args())
