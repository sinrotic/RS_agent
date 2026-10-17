import sys,unittest
from pathlib import Path
import numpy as np
import torch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/experiments'))
from product_v14_guard import merge_rank,legacy_heads,exact_guarded_ranks

class GuardTest(unittest.TestCase):
    def test_target_in_protected_head_keeps_conservative_old_rank(self):
        self.assertEqual(merge_rank(5,[4,5,6],[.9,.8,.8],99,[.1,.2,.3],.4),3)
        self.assertEqual(merge_rank(8,[4,5,-1],[.9,.8,-np.inf],4,[.6,.3,-np.inf],.4),5)

    def test_actual_blocked_search_matches_explicit_deduplicated_merge(self):
        torch.manual_seed(12);v=torch.nn.functional.normalize(torch.randn(30,5),dim=-1).numpy()
        q=torch.nn.functional.normalize(torch.randn(2,5),dim=-1)
        oldq=torch.nn.functional.normalize(torch.randn(2,5),dim=-1)
        hist=[[0,1],[2,3]];targets=[8,12]
        heads,oldscore=legacy_heads(oldq,v[:20],hist,k=3,block=7)
        ranks,proof=exact_guarded_ranks(q,v,targets,hist,heads,oldscore,block=7)
        raw=q@torch.tensor(v).T
        for i in range(2):
            candidates=[j for j in torch.argsort(raw[i],descending=True).tolist() if j not in hist[i]]
            merged=heads[i].tolist()+[j for j in candidates if j not in heads[i]]
            self.assertEqual(ranks[i],merged.index(targets[i])+1)
        self.assertEqual(proof['target_score_replay_error'],0.)

if __name__=='__main__':unittest.main()
