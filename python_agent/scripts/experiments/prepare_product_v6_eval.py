"""从官方valid构造额外开发/确认用户；候选词表和训练数据保持固定。"""
import argparse, hashlib, heapq, json, time
from pathlib import Path


def rows(path):
    with path.open(encoding='utf-8') as stream:
        for line in stream:
            yield json.loads(line)


def main(args):
    args.output.mkdir(parents=True, exist_ok=False)
    started=time.time()
    manifest=json.loads((args.data/'data_manifest.json').read_text())
    source=Path(manifest['source']); cutoff=manifest['train_cutoff']; end=manifest['valid_end']
    mapping={r['item_id']:r['index'] for r in rows(args.data/'items.jsonl')}
    previous={r['user_hash'] for r in rows(args.data/'rec_valid.jsonl')}
    targets={}
    for r in rows(source/'canonical_interactions.valid.jsonl'):
        if r['label_binary']!=1:continue
        assert cutoff<=r['timestamp']<end
        value=(r['timestamp'],r['parent_asin'])
        uid=r['user_id']
        if uid not in targets or value<targets[uid]:targets[uid]=value
    heap=[]; eligible=0
    for row in rows(source/'user_sequences.train.jsonl'):
        uid=row['user_id']
        if uid not in targets:continue
        ids=row['recent_positive_item_sequence'];ts=row['recent_positive_timestamp_sequence']
        if len(ids)<3:continue
        assert len(ids)==len(ts) and all(t<cutoff for t in ts)
        digest=hashlib.sha256(uid.encode()).hexdigest()
        if digest in previous:continue
        eligible+=1
        priority=int(hashlib.sha256(('product-v6-evaluation:'+uid).encode()).hexdigest(),16)
        entry=(-priority,digest,sorted(zip(ids,ts),key=lambda x:(x[1],x[0])),targets[uid])
        if len(heap)<2*args.users:heapq.heappush(heap,entry)
        elif entry[:2]>heap[0][:2]:heapq.heapreplace(heap,entry)
    print('ELIGIBLE',eligible,'SELECTED',len(heap),flush=True)
    assert len(heap)>=400, 'too few additional users for development/confirmation'
    cohort_size=len(heap)//2
    records=[]
    for _,digest,hist,(timestamp,item) in sorted(heap,reverse=True):
        assert item not in {i for i,_ in hist}
        hist=hist[-50:];known=[(mapping[i],t) for i,t in hist if i in mapping]
        records.append({'user_hash':digest,'history':[i for i,_ in known],'history_ts':[t for _,t in known],
            'original_history_length':len(hist),'target':mapping.get(item,-1),'target_ts':timestamp,
            'known_train_positives':[i for i,_ in known],'explicit_negatives':[]})
    summaries={}
    for name,batch in [('rec_dev',records[:cohort_size]),('rec_confirm',records[cohort_size:])]:
        path=args.output/(name+'.jsonl')
        with path.open('w',encoding='utf-8') as stream:
            for row in batch:stream.write(json.dumps(row)+'\n')
        summaries[name]={'users':len(batch),'covered_targets':sum(r['target']>=0 for r in batch),
            'empty_known_history':sum(not r['history'] for r in batch),
            'history_items_known':sum(len(r['history']) for r in batch),
            'history_items_total':sum(r['original_history_length'] for r in batch),
            'sha256':hashlib.sha256(path.read_bytes()).hexdigest()}
    report={'state':'READY','seconds':time.time()-started,'eligible_users':eligible,'cohorts':summaries,
        'selection':'新增用户排除旧1000人；按固定哈希选取，不按目标是否在候选库过滤；训练期历史映射到固定词表',
        'confirmation_policy':'rec_confirm在方案冻结后仅用于确认，不参与模型和超参数选择；仍来自官方valid时间窗，不是独立官方test',
        'limitations':['词表外目标计未命中','无已知历史用户计未命中，实际线上会走fallback','未扩展候选库','语义开发集仍为合成来源商品恢复代理指标']}
    (args.output/'manifest.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--data',type=Path,required=True);p.add_argument('--output',type=Path,required=True);p.add_argument('--users',type=int,default=5000)
    main(p.parse_args())
