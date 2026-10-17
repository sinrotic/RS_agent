#!/usr/bin/env python3
"""对照原推理函数和原始训练事件验证运行时特征与分数。"""
import argparse
import ast
from collections import Counter,defaultdict
import json
from pathlib import Path
import sqlite3
import urllib.request


def main():
    parser=argparse.ArgumentParser();parser.add_argument('--directory',required=True)
    parser.add_argument('--reference',required=True);parser.add_argument('--output',required=True)
    args=parser.parse_args();root=Path(args.directory);reference=Path(args.reference)
    manifest=json.loads((root/'serving-manifest.json').read_text())
    scope={}
    definitions=[]
    for name,functions in [('ltr.py',{'score_ltr'}),('cold_deepfm.py',{'score_deepfm_model','_vector','_scale_feature_value','_deepfm_forward'})]:
        tree=ast.parse((reference/name).read_text(encoding='utf-8-sig'))
        definitions.extend(ast.unparse(node) for node in tree.body if isinstance(node,ast.FunctionDef) and node.name in functions)
    exec('from __future__ import annotations\nimport math\n'+'\n'.join(definitions),scope)
    cold=json.loads((root/'cold_model.json').read_text());deep=json.loads((root/'deepfm_model.json').read_text())
    db=sqlite3.connect(f'file:{root}/features.sqlite?mode=ro&immutable=1',uri=True)
    users=[r[0] for r in db.execute('SELECT id FROM user_stats LIMIT 5')]
    items=[r[0] for r in db.execute('SELECT id FROM item_stats ORDER BY n DESC LIMIT 5')]
    items += [r[0] for r in db.execute('SELECT id FROM item_stats LIMIT 15')]
    item_counts=Counter();user_counts=Counter();item_users=defaultdict(set);user_items=defaultdict(set)
    with Path(manifest['train_file']).open() as handle:
        for line in handle:
            row=json.loads(line)
            if not row['label_binary']:continue
            user,item=row['user_id'],row['parent_asin']
            if user in users:user_counts[user]+=1;user_items[user].add(item)
            if item in items:item_counts[item]+=1;item_users[item].add(user)
    for user in users:assert db.execute('SELECT n,distinct_n FROM user_stats WHERE id=?',(user,)).fetchone()==(user_counts[user],len(user_items[user]))
    for item in items:assert db.execute('SELECT n,distinct_n FROM item_stats WHERE id=?',(item,)).fetchone()==(item_counts[item],len(item_users[item]))
    db.close()
    report={'feature_count_samples':len(users)+len(items),'pairs':0,'max_cold_error':0.,'max_deepfm_error':0.,'checks':[]}
    for user in users+['unseen-ranking-user']:
        request={'profile_user_id':user,'candidate_item_ids':items+['unseen-ranking-item'],'stage':'fine','fine_limit':500,'include_features':True}
        req=urllib.request.Request('http://172.21.0.1:18119/internal/ranking/cold-deepfm',data=json.dumps(request).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=5) as response:result=json.load(response)
        for row in result['items']:
            values=row['features'];item=row['item_id']
            import math
            assert values['score_item_train_positive_count_log1p']==round(math.log1p(item_counts[item]),10)
            assert values['score_user_train_positive_count_log1p']==round(math.log1p(user_counts[user]),10)
            expected_cold=scope['score_ltr'](values,cold['weights'],cold['bias'])
            expected_deep=scope['score_deepfm_model'](values,deep)
            report['max_cold_error']=max(report['max_cold_error'],abs(row['cold_score']-expected_cold))
            report['max_deepfm_error']=max(report['max_deepfm_error'],abs(row['deepfm_logit']-expected_deep))
            report['pairs']+=1
    assert report['max_cold_error']<1e-10 and report['max_deepfm_error']<1e-10
    report.update(status='PASS',checks=['特征计数与原始 train 正向事件独立扫描一致','原 COLD/DeepFM 函数与运行时分数一致，包含冷用户/冷商品/高频特征缩放'])
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n');print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
