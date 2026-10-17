#!/usr/bin/env python3
"""核验完整导入计数及原始产物到在线查询的分数一致性。"""
import argparse
import json
import sqlite3
import urllib.request
from pathlib import Path


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--directory',required=True)
    parser.add_argument('--output',required=True)
    args=parser.parse_args()
    root=Path(args.directory)
    serving=json.loads((root/'serving-manifest.json').read_text())
    db=sqlite3.connect(f'file:{root}/candidates.sqlite?mode=ro&immutable=1',uri=True)
    report={'sources':{},'checks':[]}
    for source,spec in serving['sources'].items():
        original=json.loads(Path(spec['manifest']).read_text())
        if source=='usercf_recall':
            count=db.execute('SELECT SUM(json_array_length(payload)) FROM user_lists WHERE source=?',(source,)).fetchone()[0]
            expected=original['candidate_total_count']
        else:
            count=db.execute('SELECT COUNT(*) FROM candidates WHERE source=?',(source,)).fetchone()[0]
            expected=original.get('edge_count',original.get('row_count'))
        assert count==spec['candidate_count'],(source,count,spec['candidate_count'])
        if expected is not None: assert count==expected,(source,count,expected)
        sample_file=Path(spec['files'][0]['file'])
        with sample_file.open() as handle:
            first=json.loads(handle.readline())
            request={'profile_user_id':'validation','history_item_ids':['unseen-1','unseen-2','unseen-3'],'sources':[source],'limit':80}
            if source in ('itemcf_weak','itemcf_strong','swing_recall'):
                seed=first['src_item']; raw=[first]
                for line in handle:
                    row=json.loads(line)
                    if row['src_item'] != seed:break
                    raw.append(row)
                request['history_item_ids']=[seed,'unseen-2']
                expected_rows=sorted(raw,key=lambda r:(r['rank'],r['dst_item']))[:40]
                expected_scores={r['dst_item']:float(r['score']) for r in expected_rows if r['dst_item']!=seed}
            elif source=='usercf_recall':
                request['profile_user_id']=first['user_id']
                expected_scores={r['item_id']:float(r['score']) for r in first['candidates'][:80]}
            elif source=='popular':
                raw=[first]+[json.loads(handle.readline()) for _ in range(79)]
                expected_scores={r['item_id']:float(r['score']) for r in raw}
            else:
                stored=dict(db.execute('SELECT item,score FROM candidates WHERE source=? AND bucket=?',(source,first['bucket'])))
                assert all(stored[r['parent_asin']]==float(r['score']) for r in first['top_items'])
                report['sources'][source]={'count':count,'sample_score_parity':'PASS'}
                continue
        req=urllib.request.Request('http://172.21.0.1:18118/internal/recall/multi',
             data=json.dumps(request).encode(),headers={'Content-Type':'application/json'})
        with urllib.request.urlopen(req,timeout=5) as response: actual=json.load(response)['sources'][source]
        actual_scores={r['item_id']:r['score'] for r in actual}
        assert actual_scores==expected_scores,(source,len(actual_scores),len(expected_scores))
        report['sources'][source]={'count':count,'sample_score_parity':'PASS'}
    db.close()
    report.update(status='PASS',checks=['完整导入数量与产物计数一致','原始产物样本 ID/分数与检索结果一致'])
    Path(args.output).write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':main()
