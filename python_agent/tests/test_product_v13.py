import sys,unittest
from pathlib import Path
import torch
import torch.nn.functional as F
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/experiments'))
from product_v13_model import CollaborativeTowers
from product_v10_model import SequenceResidualTowers

class CollaborativeTest(unittest.TestCase):
    def test_query_order_is_preserved_and_user_scores_are_weighted_sum(self):
        torch.manual_seed(42);m=CollaborativeTowers(4,8,20,collab_dim=3,alpha=.2)
        text=F.normalize(torch.randn(20,4),dim=-1);ids=torch.arange(20)
        item=m.encode_export_items(text,ids);features=F.normalize(torch.randn(2,4),dim=-1)
        q=m.encode_query(features);old=SequenceResidualTowers.encode_query(m,features)
        torch.testing.assert_close(q@item.T,(old@text.T)*(.8**.5))
        h=torch.tensor([[0,1],[2,3]]);mask=torch.ones(2,2)
        u=m.encode_user_with_ids(text[h],h,mask)
        expected=.8*(SequenceResidualTowers.encode_user(m,text[h],mask)@text.T)+.2*(m.collab_request(text[h],h,mask)@m.collab_items(ids).T)
        torch.testing.assert_close(u@item.T,expected)
        torch.testing.assert_close(item.norm(dim=1),torch.ones(20))

    def test_collaborative_loss_keeps_text_towers_frozen(self):
        m=CollaborativeTowers(4,8,20,collab_dim=3);m.requires_grad_(False)
        m.collab_item.requires_grad_(True);m.collab_user.requires_grad_(True)
        h=torch.tensor([[0,1],[2,3]]);text=F.normalize(torch.randn(20,4),dim=-1)
        q=m.collab_request(text[h],h,torch.ones(2,2));scores=q@m.collab_items(torch.arange(20)).T
        F.cross_entropy(scores,torch.tensor([5,6])).backward()
        self.assertTrue(all(p.grad is None for k,p in m.named_parameters() if not k.startswith('collab_')))
        self.assertGreater(float(m.collab_item.weight.grad.abs().sum()),0)

if __name__=='__main__':unittest.main()
