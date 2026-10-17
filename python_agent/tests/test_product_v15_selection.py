import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'scripts/experiments'))
from train_product_v15 import select_full_epoch

class SelectionBoundaryTest(unittest.TestCase):
    def test_exactly_two_lost_queries_remains_eligible_and_sealed_cannot_choose(self):
        def epoch(number,hits,mrr):
            return {'epoch':number,'semantic':{'metrics':{'count':347,'hit@10':hits/347}},
                    'evaluation':{'future_dev':{'metrics':{'mrr':mrr,'hit@100':.1}}}}
        result={'baseline_semantic':{'metrics':{'count':347,'hit@10':88/347}},
                'baseline':{'future_dev':{'metrics':{'mrr':.01}}},
                'epochs':[epoch(1,86,.012),epoch(2,85,.02),epoch(3,87,.011)],
                'sealed':{'must_never_choose':'epoch3'}}
        self.assertEqual(select_full_epoch(result)['epoch'],1)
        result['sealed']={'arbitrary_metrics':[float('nan')]}
        self.assertEqual(select_full_epoch(result)['epoch'],1)
        result['epochs']=[epoch(2,85,.02)]
        with self.assertRaises(RuntimeError):select_full_epoch(result)

if __name__=='__main__':unittest.main()
