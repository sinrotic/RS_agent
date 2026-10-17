"""零初始化复现最佳聚合，池化梯度隔离，短历史不随注意力变化。"""
import sys,unittest
from pathlib import Path
import torch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/experiments'))
from product_v10_model import SequenceResidualTowers,head_loss
from product_v11_model import AttentionResidualTowers
class AttentionTest(unittest.TestCase):
    def test_initial_forward_and_short_history(self):
        torch.manual_seed(42);base=SequenceResidualTowers(8,4,0,0,pooling='cohesion');new=AttentionResidualTowers(8,4,0,0)
        new.load_state_dict(base.state_dict(),strict=False)
        h=torch.nn.functional.normalize(torch.randn(2,4,8),dim=-1);mask=torch.tensor([[1.,1.,1.,1.],[1.,1.,0.,0.]])
        torch.testing.assert_close(base.encode_user(h,mask),new.encode_user(h,mask),atol=1e-7,rtol=1e-6)
        before=new.encode_user(h[1:,],mask[1:,])
        with torch.no_grad():new.user.pool_score.weight.fill_(2.);new.user.pool_recency.fill_(3.)
        self.assertTrue(torch.equal(before,new.encode_user(h[1:],mask[1:])))
    def test_only_pool_receives_gradient(self):
        m=AttentionResidualTowers(8,4,0,0);m.requires_grad_(False)
        for n,p in m.user.named_parameters():p.requires_grad_(n.startswith('pool_'))
        h=torch.nn.functional.normalize(torch.randn(2,4,8),dim=-1);q=m.encode_user(h,torch.ones(2,4))
        loss,_=head_loss(q,torch.nn.functional.normalize(torch.randn(2,128,8),dim=-1));loss.backward()
        self.assertTrue(any(p.grad is not None and bool((p.grad!=0).any()) for n,p in m.named_parameters() if n.startswith('user.pool_')))
        self.assertTrue(all(p.grad is None for n,p in m.named_parameters() if not n.startswith('user.pool_')))
if __name__=='__main__':unittest.main()
