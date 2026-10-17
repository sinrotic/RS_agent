"""按时间升序接收历史，位置衰减聚合；商品/查询塔保持原空间。"""
import torch
import torch.nn.functional as F
from three_tower_residual import ResidualTowers

class SequenceResidualTowers(ResidualTowers):
    def __init__(self,*args,pooling='mean',**kwargs):
        super().__init__(*args,**kwargs)
        if pooling not in ['mean','decay08','blend_recent','cohesion']:raise ValueError('unsupported pooling')
        self.pooling=pooling

    def encode_user(self,history_vectors,mask):
        if self.pooling=='cohesion':
            lengths=mask.sum(1,keepdim=True)
            pair=history_vectors@history_vectors.transpose(1,2)
            support=((pair*mask[:,None,:]).sum(2)-1)/(lengths-1).clamp_min(1)
            weights=(support/.15).masked_fill(mask==0,-torch.inf).softmax(1)
            # 两项历史没有足够证据辨别离群项，严格保持原均值前向。
            return super().encode_user(history_vectors,torch.where(lengths<=2,mask,weights))
        if self.pooling=='blend_recent':
            lengths=(mask>0).sum(1,keepdim=True)
            positions=torch.arange(mask.shape[1],device=mask.device)[None,:]
            recent=mask*(positions>=lengths-3)
            weights=.75*mask/mask.sum(1,keepdim=True)+.25*recent/recent.sum(1,keepdim=True)
            return super().encode_user(history_vectors,weights)
        if self.pooling=='decay08':
            lengths=(mask>0).sum(1,keepdim=True)
            positions=torch.arange(mask.shape[1],device=mask.device)[None,:]
            mask=mask*.8**(lengths-1-positions).clamp_min(0)
        return super().encode_user(history_vectors,mask)

def sample_hard_ids(batch,request,vectors,rng,excluded,fingerprints,random_ids,pool_size=4096,hard_count=31):
    """从共享随机池挖用户近邻；不以低于正例分数为资格，过滤已知正例与近重复。"""
    import numpy as np
    pool=np.asarray(rng.sample(range(len(vectors)),pool_size),dtype=np.int64)
    pool_tensor=torch.tensor(pool,device=request.device)
    with torch.no_grad():
        scored=request.detach()@vectors[pool_tensor].T
        targets=torch.tensor([r['target'] for r in batch],device=request.device)
        similarity=vectors[targets]@vectors[pool_tensor].T
        allowed=np.ones((len(batch),len(pool)),dtype=bool)
        for i,r in enumerate(batch):
            blocked=set(r['known_train_positives'])|excluded|set(map(int,random_ids[i]))
            allowed[i]=~np.isin(pool,list(blocked)) & (fingerprints[pool]!=fingerprints[r['target']])
        allowed=torch.tensor(allowed,device=request.device)&(similarity<.97)
        mined=scored.masked_fill(~allowed,-torch.inf).topk(hard_count,dim=1)
        if not bool(torch.isfinite(mined.values).all()):raise RuntimeError('insufficient eligible hard negatives')
        selected=pool_tensor[mined.indices].cpu().numpy()
    return np.concatenate([random_ids[:,:97],selected],axis=1)

def head_loss(request,candidate_vectors,extra_head=False,hard_weight=1.):
    scores=torch.einsum('bd,bnd->bn',request,candidate_vectors)
    logits=scores/.07
    if hard_weight!=1.:
        if not 0<hard_weight<=1.:raise ValueError('invalid hard weight')
        import math
        logits=torch.cat([logits[:,:97],logits[:,97:]+math.log(hard_weight)],1)
    loss=F.cross_entropy(logits,torch.zeros(len(request),device=request.device,dtype=torch.long))
    if extra_head:
        hardest=scores[:,1:].topk(16,dim=1).values
        loss=loss+.1*F.softplus((hardest-scores[:,:1]+.02)/.05).mean()
    return loss,scores.detach()
