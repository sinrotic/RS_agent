"""保持旧词表头部相对分数；教师无梯度，缺少旧历史的样本不参与蒸馏。"""
import torch
import torch.nn.functional as F
import numpy as np

def ranking_distillation(student,teacher,candidates,teacher_scores,active,temperature=.07):
    logits=torch.einsum('bd,bnd->bn',student,candidates)/temperature
    target=F.softmax(teacher_scores.detach()/temperature,dim=1)
    per=F.kl_div(F.log_softmax(logits,dim=1),target,reduction='none').sum(1)
    weights=active.to(per.dtype)
    return (per*weights).sum()/weights.sum().clamp_min(1)

@torch.no_grad()
def teacher_candidates(teacher_request,pool_ids,pool_vectors,batch,active,count=64):
    scores=teacher_request@pool_vectors.T
    # 一次传递遮罩，避免每行把CUDA池回传CPU和启动单独kernel。
    pool=pool_ids.cpu().numpy()
    forbidden=np.stack([np.isin(pool,r['history']) for r in batch])
    scores.masked_fill_(torch.tensor(forbidden,device=scores.device),-torch.inf)
    selected=scores.topk(count,dim=1).indices
    ids=pool_ids[selected];values=scores.gather(1,selected)
    assert bool(torch.isfinite(values[active]).all())
    # inactive仍保持有限值，不能让0乘NaN污染总损失。
    values=torch.where(active[:,None],values,torch.zeros_like(values))
    return ids,values
