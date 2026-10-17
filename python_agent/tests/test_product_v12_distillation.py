import sys,unittest
from pathlib import Path
import torch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/experiments'))
from product_v12_distillation import ranking_distillation,teacher_candidates

class DistillationTest(unittest.TestCase):
    def test_teacher_is_frozen_and_unknown_history_does_not_drive_gradient(self):
        student=torch.tensor([[.3,.5],[.8,.1]],requires_grad=True)
        teacher=torch.tensor([[.7,.2],[.4,.6]],requires_grad=True)
        vectors=torch.eye(2).repeat(2,1,1)
        scores=torch.einsum('bd,bnd->bn',teacher,vectors)
        loss=ranking_distillation(student,teacher,vectors,scores,torch.tensor([True,False]))
        loss.backward()
        self.assertTrue(torch.isfinite(loss));self.assertIsNone(teacher.grad)
        self.assertGreater(float(student.grad[0].abs().sum()),0)
        self.assertEqual(float(student.grad[1].abs().sum()),0)

    def test_teacher_candidates_mask_seen_items(self):
        ids=torch.arange(5);v=torch.tensor([[1.,0.],[.9,.1],[.8,.2],[.7,.3],[.6,.4]])
        q=torch.tensor([[1.,0.],[0.,1.]])
        found,scores=teacher_candidates(q,ids,v,[{'history':[0,1]},{'history':[]}],torch.tensor([True,False]),2)
        self.assertEqual(found[0].tolist(),[2,3]);self.assertTrue(torch.equal(scores[1],torch.zeros(2)))
        x=q.clone().requires_grad_();loss=ranking_distillation(x,q,v[found],scores,torch.tensor([False,False]))
        loss.backward();self.assertEqual(float(x.grad.abs().sum()),0)

if __name__=='__main__':unittest.main()
