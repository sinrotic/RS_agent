"""在固定一致性聚合上学习轻量内容/近期注意力；<=2项历史严格保持均值。"""
import torch
from torch import nn
import torch.nn.functional as F
from product_v10_model import SequenceResidualTowers
class AttentionResidualTowers(SequenceResidualTowers):
    def __init__(self,*args,pooling='attention_cohesion',**kwargs):
        super().__init__(*args,pooling='cohesion' if pooling=='attention_cohesion' else pooling,**kwargs)
        self.pooling=pooling
        dimension=args[0] if args else kwargs.get('dimension',1024)
        self.user.pool_key=nn.Linear(dimension,64)
        self.user.pool_context=nn.Linear(2*dimension,64,bias=False)
        self.user.pool_score=nn.Linear(64,1,bias=False)
        self.user.pool_recency=nn.Parameter(torch.zeros(()))
        nn.init.zeros_(self.user.pool_score.weight)
    def encode_user(self,h,mask):
        if self.pooling!='attention_cohesion':return super().encode_user(h,mask)
        lengths=mask.sum(1,keepdim=True)
        pair=h@h.transpose(1,2)
        support=((pair*mask[:,None,:]).sum(2)-1)/(lengths-1).clamp_min(1)
        mean=(h*mask[:,:,None]).sum(1)/lengths
        last=h[torch.arange(len(h),device=h.device),(lengths[:,0].long()-1)]
        context=self.user.pool_context(torch.cat([mean,last],1)*h.shape[-1]**.5)
        delta=self.user.pool_score(torch.tanh(self.user.pool_key(h*h.shape[-1]**.5)+context[:,None,:])).squeeze(-1)
        age=(torch.arange(mask.shape[1],device=h.device)[None,:]-lengths+1)/(lengths-1).clamp_min(1)
        logits=support/.15+delta+self.user.pool_recency*age
        weights=logits.masked_fill(mask==0,-torch.inf).softmax(1)
        weights=torch.where(lengths<=2,mask,weights)
        pooled=(h*weights[:,:,None]).sum(1)/weights.sum(1,keepdim=True)
        return F.normalize(pooled+self.user(pooled),dim=-1)
