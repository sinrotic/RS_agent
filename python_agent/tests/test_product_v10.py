"""用户序列方向/填充，以及困难负样本真实竞争项和假负例过滤。"""
import sys,unittest,random
from pathlib import Path
import numpy as np
import torch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/experiments'))
from product_v10_model import SequenceResidualTowers,sample_hard_ids,head_loss

class ProductV10Test(unittest.TestCase):
    def test_recency_and_padding(self):
        m=SequenceResidualTowers(2,4,0,0,pooling='decay08')
        h=torch.tensor([[[1.,0.],[0.,1.],[99.,99.]]]);mask=torch.tensor([[1.,1.,0.]])
        actual=m.encode_user(h,mask)
        expected=torch.nn.functional.normalize(torch.tensor([[.8,1.]]),dim=-1)
        torch.testing.assert_close(actual,expected)
        torch.testing.assert_close(actual,m.encode_user(h[:,:2],mask[:,:2]))

    def test_competing_negatives_and_exclusions(self):
        n=300;v=torch.zeros(n,2);v[0]=torch.tensor([1.,0.]);v[1:]=torch.tensor([0.,1.]);v[299]=v[0]
        fp=np.arange(n,dtype=np.uint64);fp[298]=fp[0]
        batch=[{'target':0,'known_train_positives':[0,297]}]
        uniform=np.arange(128,dtype=np.int64)[None,:]
        ids=sample_hard_ids(batch,torch.tensor([[0.,1.]]),v,random.Random(42),{296},fp,uniform,pool_size=n)
        chosen=ids[0,97:].tolist()
        self.assertEqual(len(ids[0]),128);self.assertEqual(len(set(ids[0])),128)
        self.assertFalse(set(chosen)&{0,296,297,298,299})
        self.assertTrue(bool(((v[chosen]@torch.tensor([0.,1.]))>(v[0]@torch.tensor([0.,1.]))).all()))

    def test_only_user_gradient_and_finite_head_loss(self):
        m=SequenceResidualTowers(2,4,0,0,pooling='decay08');m.requires_grad_(False);m.user.requires_grad_(True)
        q=m.encode_user(torch.tensor([[[1.,0.],[0.,1.]]]),torch.ones(1,2))
        loss,_=head_loss(q,torch.nn.functional.normalize(torch.randn(1,128,2),dim=-1),True);loss.backward()
        self.assertTrue(bool(torch.isfinite(loss)))
        self.assertTrue(any(p.grad is not None for p in m.user.parameters()))
        self.assertTrue(all(p.grad is None for p in m.item.parameters()))
        self.assertTrue(all(p.grad is None for p in m.query.parameters()))

    def test_hard_weight_reduces_uncertain_negative_pressure(self):
        q=torch.tensor([[1.,0.]])
        candidates=torch.zeros(1,128,2);candidates[:,0]=torch.tensor([.5,.5]);candidates[:,97:]=torch.tensor([1.,0.])
        full,_=head_loss(q,candidates,False,1.)
        soft,_=head_loss(q,candidates,False,.1)
        self.assertLess(float(soft),float(full))

    def test_cohesion_reduces_outlier_and_preserves_short_history(self):
        m=SequenceResidualTowers(2,4,0,0,pooling='cohesion')
        h=torch.tensor([[[1.,0.],[1.,0.],[0.,1.]]]);q=m.encode_user(h,torch.ones(1,3))
        self.assertLess(float(q[0,1].detach()),.1)
        m.pooling='mean';before=m.encode_user(h[:,:2],torch.ones(1,2))
        m.pooling='cohesion';after=m.encode_user(h[:,:2],torch.ones(1,2))
        self.assertTrue(torch.equal(before,after))
if __name__=='__main__':unittest.main()
