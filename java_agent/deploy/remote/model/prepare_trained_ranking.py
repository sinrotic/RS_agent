#!/usr/bin/env python3
"""从训练集可见正向事件构建排序特征快照，复用已训练参数，不重新训练。"""
import argparse
import hashlib
import json
import shutil
import sqlite3
from pathlib import Path


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--train',required=True)
    parser.add_argument('--models',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    output=Path(args.output);output.mkdir(parents=True,exist_ok=False)
    source=Path(args.train);models=Path(args.models)
    report={'version':'cold_deepfm_20260914','feature_version':'cold_deepfm_training_features_v2',
            'feature_policy':'train_only_snapshot_at_end_of_train','scope':'用户授权的 Java 首页及对话排序接入',
            'ranking_effect_conclusion_allowed':False,'models':{}}
    for name in ['cold_model.json','deepfm_model.json']:
        data=json.loads((models/name).read_text())
        assert data['training']['status']=='trained' and data['training']['rows']==45655785
        shutil.copy2(models/name,output/name)
        report['models'][name]={'sha256':hashlib.sha256((models/name).read_bytes()).hexdigest(),'source':str(models/name)}
    db=sqlite3.connect(output/'features.sqlite')
    db.executescript('PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF; PRAGMA cache_size=-131072;'
                     'CREATE TABLE events(user TEXT,item TEXT);')
    digest=hashlib.sha256();count=0;read=0;max_time=0;batch=[]
    with source.open('rb') as handle:
        for line in handle:
            digest.update(line);row=json.loads(line);read+=1
            assert row['split']=='train'
            max_time=max(max_time,int(row['timestamp']))
            if row['label_binary']:
                batch.append((row['user_id'],row['parent_asin']));count+=1
            if len(batch)>=10000:
                db.executemany('INSERT INTO events VALUES (?,?)',batch);db.commit();batch.clear()
            if read%1000000==0: print('read',read,'positive',count,flush=True)
    if batch:db.executemany('INSERT INTO events VALUES (?,?)',batch);db.commit()
    assert count==9131157,(count,'training positive count mismatch')
    print('aggregate train history',flush=True)
    db.executescript('CREATE INDEX events_user ON events(user,item); CREATE INDEX events_item ON events(item,user);'
        'CREATE TABLE user_stats(id TEXT PRIMARY KEY,n INTEGER,distinct_n INTEGER) WITHOUT ROWID;'
        'INSERT INTO user_stats SELECT user,COUNT(*),COUNT(DISTINCT item) FROM events GROUP BY user;'
        'CREATE TABLE item_stats(id TEXT PRIMARY KEY,n INTEGER,distinct_n INTEGER) WITHOUT ROWID;'
        'INSERT INTO item_stats SELECT item,COUNT(*),COUNT(DISTINCT user) FROM events GROUP BY item;')
    report.update(train_file=str(source),train_sha256=digest.hexdigest(),train_rows=read,positive_events=count,
                  feature_cutoff_epoch_ms=max_time+1,
                  users=db.execute('SELECT COUNT(*) FROM user_stats').fetchone()[0],
                  items=db.execute('SELECT COUNT(*) FROM item_stats').fetchone()[0])
    assert report['users']==5375378
    db.execute('DROP TABLE events');db.commit();db.execute('VACUUM')
    assert db.execute('PRAGMA quick_check').fetchone()[0]=='ok';db.close()
    report['status']='PASS'
    (output/'serving-manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
