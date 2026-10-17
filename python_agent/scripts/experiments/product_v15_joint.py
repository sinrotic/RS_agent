"""两任务共同训练商品残差，用户/查询各自更新；轻量约束来自起始纯三塔。"""
import torch
import torch.nn.functional as F

def joint_loss(model,teacher,features,candidates,task,history_ids=None,mask=None,query_features=None):
    if task not in ['rec','semantic']:raise ValueError('unknown task')
    combined=torch.cat([candidates.flatten(),history_ids.flatten()]) if task=='rec' else candidates.flatten()
    unique,inverse=torch.unique(combined,return_inverse=True)
    item=model.encode_items(features[unique])
    with torch.no_grad():original=teacher.encode_items(features[unique])
    number=candidates.numel()
    candidate=item[inverse[:number]].reshape(*candidates.shape,-1)
    original_candidate=original[inverse[:number]].reshape(*candidates.shape,-1)
    if task=='rec':
        history=item[inverse[number:]].reshape(*history_ids.shape,-1)
        original_history=original[inverse[number:]].reshape(*history_ids.shape,-1)
        request=model.encode_user(history,mask)
        with torch.no_grad():original_request=teacher.encode_user(original_history,mask)
    else:
        request=model.encode_query(query_features)
        with torch.no_grad():original_request=teacher.encode_query(query_features)
    logits=torch.einsum('bd,bnd->bn',request,candidate)/.07
    original_logits=torch.einsum('bd,bnd->bn',original_request,original_candidate)/.07
    ce=F.cross_entropy(logits,torch.zeros(len(request),device=request.device,dtype=torch.long))
    kl=F.kl_div(F.log_softmax(logits,dim=1),F.softmax(original_logits,dim=1),reduction='batchmean')
    anchor=(item-original).square().sum(1).mean()+(request-original_request).square().sum(1).mean()
    loss=ce+.3*kl+.1*anchor
    return loss,{'ce':ce.detach(),'kl':kl.detach(),'representation_anchor':anchor.detach()}
