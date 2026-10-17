import torch
from torch import nn
import torch.nn.functional as F

class Adapter(nn.Module):
    def __init__(self, dimension=1024, hidden=256):
        super().__init__()
        self.layers = nn.Sequential(nn.Linear(dimension, hidden), nn.ReLU(), nn.Linear(hidden, dimension))
        nn.init.zeros_(self.layers[-1].weight)
        nn.init.zeros_(self.layers[-1].bias)

    def forward(self, x):
        return self.layers(x)


class ResidualTowers(nn.Module):
    def __init__(self, dimension=1024, hidden=256, item_count=0, id_dim=0):
        super().__init__()
        self.item = Adapter(dimension, hidden)
        self.user = Adapter(dimension, hidden)
        self.query = Adapter(dimension, hidden)
        self.id_embedding = nn.Embedding(item_count, id_dim) if id_dim else None
        self.id_projection = nn.Linear(id_dim, dimension, bias=False) if id_dim else None
        if id_dim:
            nn.init.normal_(self.id_embedding.weight, std=.01)
            nn.init.zeros_(self.id_projection.weight)

    def encode_items(self, features, ids=None):
        result = features + self.item(features)
        if self.id_embedding is not None:
            if ids is None:
                raise ValueError("ID branch requires IDs; use -1 for OOV")
            known = (ids >= 0) & (ids < self.id_embedding.num_embeddings)
            safe_ids = ids.clamp(0, self.id_embedding.num_embeddings - 1)
            result = result + self.id_projection(self.id_embedding(safe_ids)) * known.unsqueeze(-1)
        return F.normalize(result, dim=-1)

    def encode_user(self, history_vectors, mask):
        lengths = mask.sum(1, keepdim=True)
        if bool((lengths == 0).any()):
            raise ValueError("empty history must use cold-start fallback")
        mean = (history_vectors * mask.unsqueeze(-1)).sum(1) / lengths
        return F.normalize(mean + self.user(mean), dim=-1)

    def encode_query(self, features):
        return F.normalize(features + self.query(features), dim=-1)


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


def create_model(config,item_count):
    return SequenceResidualTowers(1024,config['hidden'],item_count,config['id_dim'],pooling=config.get('pooling','mean'))
