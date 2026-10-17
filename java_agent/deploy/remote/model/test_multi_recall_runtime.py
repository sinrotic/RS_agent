import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from multi_recall_runtime import Runtime, SOURCES


class RecallTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        root = Path(self.temp.name)
        (root/'serving-manifest.json').write_text(json.dumps({'status':'PASS','version':'test','sources':dict.fromkeys(SOURCES,{})}))
        db = sqlite3.connect(root/'candidates.sqlite')
        db.executescript('CREATE TABLE candidates(source,bucket,item,score,rank); CREATE INDEX lookup ON candidates(source,bucket,rank,item); CREATE TABLE user_lists(source,user,payload);')
        db.executemany('INSERT INTO candidates VALUES (?,?,?,?,?)',[
            ('itemcf_weak','seed1','seen',2.,1),('itemcf_weak','seed1','shared',.8,2),
            ('itemcf_weak','seed2','shared',1.,1),('itemcf_weak','seed2','other',.5,2),
            ('popular','global','hot',10.,1),('category','bucket','cat',5.,1)])
        db.executemany('INSERT INTO user_lists VALUES (?,?,?)',[
            ('usercf_recall','user',json.dumps([['cf',4.],['seen',3.]])),('category_profile','user',json.dumps(['bucket']))])
        db.commit();db.close()
        self.runtime=Runtime(root)
    def tearDown(self): self.temp.cleanup()

    def test_real_lookup_decay_dedup_and_seen_filter(self):
        result=self.runtime.recall({'profile_user_id':'user','history_item_ids':['seed1','seed2','seen']})['sources']
        self.assertEqual([r['item_id'] for r in result['itemcf_weak']],['shared','other'])
        self.assertAlmostEqual(result['itemcf_weak'][0]['score'],.85)
        self.assertEqual(result['usercf_recall'],[{'item_id':'cf','score':4.}])
        self.assertEqual(result['category'][0]['item_id'],'cat')
    def test_cold_user_does_not_receive_collaborative_candidates(self):
        result=self.runtime.recall({'profile_user_id':'unknown','history_item_ids':[]})['sources']
        self.assertEqual(result['itemcf_weak'],[])
        self.assertEqual(result['usercf_recall'],[])
        self.assertEqual(result['popular'][0]['item_id'],'hot')
    def test_unknown_source_rejected(self):
        with self.assertRaises(ValueError): self.runtime.recall({'sources':['invented']})


if __name__=='__main__': unittest.main()
