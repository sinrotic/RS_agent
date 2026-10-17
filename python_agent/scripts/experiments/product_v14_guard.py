"""固定10个旧头部位置，其余由扩库三塔召回；精确计算去重后的保守排名。"""
import numpy as np
import torch

def merge_rank(target,head_ids,head_scores,main_rank,main_head_scores,threshold):
    ids=np.asarray(head_ids);valid=ids>=0;ids=ids[valid]
    old=np.asarray(head_scores)[valid];new=np.asarray(main_head_scores)[valid]
    match=np.flatnonzero(ids==target)
    if len(match):return int((old>=old[match[0]]).sum())
    return int(len(ids)+main_rank-(new>=threshold).sum())

@torch.inference_mode()
def legacy_heads(requests,vectors,histories,k=10,block=2048):
    device=requests.device;n=len(requests);best=torch.full((n,k),-torch.inf,device=device)
    ids=torch.full((n,k),-1,device=device,dtype=torch.long);mask={}
    for i,h in enumerate(histories):
        for x in h:mask.setdefault(x//block,[]).append((i,x%block))
    for start in range(0,len(vectors),block):
        v=torch.tensor(np.asarray(vectors[start:start+block]),device=device);scores=requests@v.T
        if start//block in mask:
            p=torch.tensor(mask[start//block],device=device);scores[p[:,0],p[:,1]]=-torch.inf
        values,columns=scores.topk(min(k,scores.shape[1]),dim=1)
        candidate_scores=torch.cat([best,values],1);candidate_ids=torch.cat([ids,columns+start],1)
        best,choice=candidate_scores.topk(k,dim=1);ids=candidate_ids.gather(1,choice)
    ids=ids.masked_fill(~torch.isfinite(best),-1)
    return ids.cpu().numpy(),best.cpu().numpy()

@torch.inference_mode()
def exact_guarded_ranks(requests,vectors,targets,histories,head_ids,head_scores,excluded=(),block=2048):
    """目标、保护项和计数都取自相同形状GEMM，避免点积舍入改变去重计数。"""
    device=requests.device;targets=np.asarray(targets,dtype=np.int64);n=len(targets)
    assert all(0<=t<len(vectors) and t not in h for t,h in zip(targets,histories))
    masks={};target_blocks={};head_blocks={}
    for i,(t,h,heads) in enumerate(zip(targets,histories,head_ids)):
        target_blocks.setdefault(int(t//block),[]).append(i)
        for x in h:masks.setdefault(x//block,[]).append((i,x%block))
        for j,x in enumerate(heads):
            if x>=0:head_blocks.setdefault(int(x//block),[]).append((i,j,int(x%block)))
    thresholds=torch.empty(n,device=device);head_values=torch.full((n,head_ids.shape[1]),-torch.inf,device=device)
    for b in sorted(set(target_blocks)|set(head_blocks)):
        start=b*block;v=torch.tensor(np.asarray(vectors[start:start+block]),device=device);scores=requests@v.T
        if b in target_blocks:
            ii=target_blocks[b];ix=torch.tensor(ii,device=device);col=torch.tensor(targets[ii]-start,device=device)
            thresholds[ix]=scores[ix,col]
        if b in head_blocks:
            p=torch.tensor(head_blocks[b],device=device);head_values[p[:,0],p[:,1]]=scores[p[:,0],p[:,2]]
    counts=torch.zeros(n,dtype=torch.long,device=device);error=0.
    for start in range(0,len(vectors),block):
        b=start//block;v=torch.tensor(np.asarray(vectors[start:start+block]),device=device);scores=requests@v.T
        if b in target_blocks:
            ii=target_blocks[b];ix=torch.tensor(ii,device=device);col=torch.tensor(targets[ii]-start,device=device)
            error=max(error,float((scores[ix,col]-thresholds[ix]).abs().max()))
        if b in masks:
            p=torch.tensor(masks[b],device=device);scores[p[:,0],p[:,1]]=-torch.inf
        blocked=[i-start for i in excluded if start<=i<start+scores.shape[1]]
        if blocked:scores[:,blocked]=-torch.inf
        counts+=(scores>=thresholds[:,None]).sum(1)
    assert error==0. and bool((counts>=1).all())
    ranks=counts.cpu().numpy();thresholds=thresholds.cpu().numpy();head_values=head_values.cpu().numpy()
    merged=[merge_rank(t,head_ids[i],head_scores[i],ranks[i],head_values[i],thresholds[i]) for i,t in enumerate(targets)]
    assert all(r>=1 for r in merged)
    return merged,{'target_score_replay_error':error,'main_ranks':ranks.tolist()}
