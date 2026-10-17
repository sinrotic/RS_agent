"""全库负例不能包含已知正例、空文本和同文本商品；困难采样保持有效梯度。"""
import random,sys
from pathlib import Path
import numpy as np
import torch
sys.path.insert(0,str(Path(__file__).parents[1]/'scripts/experiments'))
from train_product_v8 import negatives,sampled_loss
from three_tower_residual import ResidualTowers

def test_negative_exclusions_and_uniqueness():
    fp=np.arange(700,dtype='uint64');fp[11]=fp[4]
    batch=[{'target':4,'known_train_positives':[4,6,8]}]
    for seed in range(10):
        ids=negatives(batch,random.Random(seed),700,{2,3},fp,511)[0]
        assert ids[0]==4 and len(set(ids))==512
        assert not set(ids[1:])&{2,3,4,6,8,11}

def test_frozen_item_and_query_receive_no_user_training_gradient():
    torch.manual_seed(4);model=ResidualTowers(8,4,700,0)
    model.requires_grad_(False);model.user.requires_grad_(True)
    history=torch.nn.functional.normalize(torch.randn(2,3,8),dim=-1)
    user=model.encode_user(history,torch.ones(2,3))
    items=torch.nn.functional.normalize(torch.randn(2,512,8),dim=-1)
    loss=sampled_loss(user,items,True);loss.backward()
    assert torch.isfinite(loss) and any(p.grad is not None for p in model.user.parameters())
    assert all(p.grad is None for p in model.item.parameters())
    assert all(p.grad is None for p in model.query.parameters())

def test_semihard_with_no_safe_hard_negatives_still_finite():
    request=torch.tensor([[1.,0.]],requires_grad=True)
    items=torch.zeros(1,512,2);items[:,:,0]=1.;items[:,0,0]=-1.
    loss=sampled_loss(request,items,True);loss.backward()
    assert torch.isfinite(loss) and torch.isfinite(request.grad).all()

if __name__=='__main__':
    test_negative_exclusions_and_uniqueness()
    test_frozen_item_and_query_receive_no_user_training_gradient()
    test_semihard_with_no_safe_hard_negatives_still_finite()
    print('PASS: negative exclusions, frozen gradients, empty semihard pool')
