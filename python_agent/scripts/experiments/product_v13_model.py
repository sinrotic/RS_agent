"""语义三塔与协同残差共用商品向量；查询不使用协同分量，语义排序保持一致。"""
import math
import torch
from torch import nn
import torch.nn.functional as F
from product_v10_model import SequenceResidualTowers
from three_tower_residual import Adapter

class CollaborativeTowers(SequenceResidualTowers):
    def __init__(self,dimension=1024,hidden=256,item_count=0,id_dim=0,collab_dim=32,alpha=.2,**kwargs):
        super().__init__(dimension,hidden,item_count,id_dim,pooling='cohesion',**kwargs)
        if not 0<=alpha<1:raise ValueError('invalid collaborative weight')
        self.alpha=alpha;self.collab_dim=collab_dim
        self.collab_item=nn.Embedding(item_count,collab_dim)
        nn.init.normal_(self.collab_item.weight,std=.03)
        self.collab_user=Adapter(collab_dim,64)

    def collab_items(self,ids):return F.normalize(self.collab_item(ids),dim=-1)

    def collab_request(self,history_vectors,history_ids,mask):
        lengths=mask.sum(1,keepdim=True)
        pair=history_vectors@history_vectors.transpose(1,2)
        support=((pair*mask[:,None,:]).sum(2)-1)/(lengths-1).clamp_min(1)
        weights=(support/.15).masked_fill(mask==0,-torch.inf).softmax(1)
        weights=torch.where(lengths<=2,mask,weights)
        c=self.collab_items(history_ids)
        mean=(c*weights[:,:,None]).sum(1)/weights.sum(1,keepdim=True)
        return F.normalize(mean+self.collab_user(mean),dim=-1)

    def combine(self,text,collab):
        return F.normalize(torch.cat([math.sqrt(1-self.alpha)*text,math.sqrt(self.alpha)*collab],dim=-1),dim=-1)

    def encode_user_with_ids(self,history_vectors,history_ids,mask):
        text=super().encode_user(history_vectors,mask)
        cf=self.collab_request(history_vectors,history_ids,mask)
        return self.combine(text,cf)

    def encode_query(self,features):
        q=super().encode_query(features)
        return torch.cat([q,torch.zeros((*q.shape[:-1],self.collab_dim),device=q.device,dtype=q.dtype)],dim=-1)

    def encode_export_items(self,text,ids):return self.combine(text,self.collab_items(ids))
