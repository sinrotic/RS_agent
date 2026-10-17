import sys,unittest
from pathlib import Path
import torch
import torch.nn.functional as F
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/experiments'))
from product_v10_model import SequenceResidualTowers
from product_v15_joint import joint_loss

class JointTest(unittest.TestCase):
    def test_both_tasks_share_item_but_update_only_their_request_tower(self):
        torch.manual_seed(42);m=SequenceResidualTowers(4,8,20,0,pooling='cohesion')
        teacher=SequenceResidualTowers(4,8,20,0,pooling='cohesion');teacher.load_state_dict(m.state_dict());teacher.requires_grad_(False)
        features=F.normalize(torch.randn(20,4),dim=-1);candidates=torch.tensor([[5,6,7],[8,9,10]])
        history=torch.tensor([[0,1,2],[2,3,4]]);mask=torch.ones(2,3)
        rec,stats=joint_loss(m,teacher,features,candidates,'rec',history,mask)
        rec.backward()
        self.assertTrue(any(p.grad is not None and p.grad.abs().sum()>0 for p in m.item.parameters()))
        self.assertTrue(any(p.grad is not None and p.grad.abs().sum()>0 for p in m.user.parameters()))
        self.assertTrue(all(p.grad is None for p in m.query.parameters()))
        self.assertLess(abs(float(stats['kl'])),1e-6)
        m.zero_grad(set_to_none=True)
        semantic,_=joint_loss(m,teacher,features,candidates,'semantic',query_features=features[:2])
        semantic.backward()
        self.assertTrue(any(p.grad is not None and p.grad.abs().sum()>0 for p in m.item.parameters()))
        self.assertTrue(any(p.grad is not None and p.grad.abs().sum()>0 for p in m.query.parameters()))
        self.assertTrue(all(p.grad is None for p in m.user.parameters()))
        self.assertTrue(all(p.grad is None for p in teacher.parameters()))

if __name__=='__main__':unittest.main()
