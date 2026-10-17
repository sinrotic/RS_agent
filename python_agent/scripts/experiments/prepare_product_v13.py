"""全新用户的滚动未来目标；先有两项已知历史，再预测下一正事件。"""
import hashlib,json,time
from pathlib import Path
from prepare_product_v12 import BASE,SOURCE,stream
from evaluate_product_v7_catalog import save
ROOT=BASE/'product_v13_training'

def main(extra_previous=()):
    data=ROOT/'data';data.mkdir(exist_ok=True);assert not any(data.iterdir())
    excluded={r['index'] for r in json.loads((BASE/'product_v7_expansion/data/text_audit.json').read_text())['ineligible']}
    mapping={r['item_id']:r['index'] for r in stream(BASE/'product_v7_expansion/data/items.jsonl') if r['index'] not in excluded}
    previous=set()
    for name in ['three_tower_dataset_v4/data/rec_valid.jsonl','three_tower_dataset_v4/final_test/confirmation_rows.jsonl',
                 'product_v7_expansion/data/rec_dev.jsonl','product_v7_expansion/data/rec_confirm.jsonl',
                 'product_v9_training/data/fresh_dev.jsonl','product_v9_training/data/sealed_users.jsonl',
                 'product_v10_training/data/future_dev.jsonl','product_v10_training/data/sealed_future.jsonl',
                 'product_v11_training/data/sealed_future.jsonl','product_v12_training/data/future_dev.jsonl',
                 'product_v12_training/data/sealed_future.jsonl',*extra_previous]:
        previous.update(r['user_hash'] for r in stream(BASE/name))
    events={};histories={}
    window=json.loads((SOURCE/'manifest.json').read_text())['window_policy']['splits']['test']
    for r in stream(SOURCE/'canonical_interactions.test.jsonl'):
        if r['label_binary']!=1:continue
        uid=hashlib.sha256(r['user_id'].encode()).hexdigest()
        if uid not in previous:events.setdefault(uid,[]).append((r['timestamp'],r['parent_asin']))
    events={u:sorted(v) for u,v in events.items() if len(v)>=2}
    for r in stream(SOURCE/'user_sequences.train.jsonl'):
        uid=hashlib.sha256(r['user_id'].encode()).hexdigest()
        if uid not in events:continue
        ids=r['recent_positive_item_sequence'];ts=r['recent_positive_timestamp_sequence'];assert len(ids)==len(ts)
        histories[uid]=[(t,mapping[i]) for i,t in zip(ids,ts) if i in mapping]
    for r in stream(SOURCE/'canonical_interactions.valid.jsonl'):
        if r['label_binary']!=1 or r['parent_asin'] not in mapping:continue
        uid=hashlib.sha256(r['user_id'].encode()).hexdigest()
        if uid in events:histories.setdefault(uid,[]).append((r['timestamp'],mapping[r['parent_asin']]))
    kept=[]
    for uid,ev in events.items():
        prior=histories.get(uid,[])
        for timestamp,iid in ev:
            usable=sorted((t,i) for t,i in prior if t<timestamp)
            reverse=[];seen=set()
            for t,i in reversed(usable):
                if i not in seen:reverse.append((t,i));seen.add(i)
                if len(reverse)==50:break
            history=[i for _,i in reversed(reverse)];target=mapping.get(iid,-1)
            if len(history)>=2 and target not in history:
                assert all(t<timestamp for t,_ in reverse)
                kept.append({'user_hash':uid,'history_full':history,'history_old':[i for i in history if i<203887],
                             'target':target,'old_target':target if 0<=target<203887 else -1,'target_ts':timestamp,
                             'latest_history_ts':max(t for t,_ in reverse)})
                break
            if iid in mapping:prior.append((timestamp,mapping[iid]))
    kept.sort(key=lambda r:hashlib.sha256(('v13-rolling:'+r['user_hash']).encode()).digest())
    audit={'eligible':len(kept),'previous_users':len(previous),'window':window,
           'policy':'用户排除所有此前评测；仅在严格早于目标的已知正历史>=2后取首个下一正事件。可使用此前test事件作为当时已经发生的历史，绝不加入梯度。不是固定窗口快照，与v12分开报告。'}
    save(ROOT/'cohort_audit.json',audit);print('ROLLING_COHORT',audit,flush=True)
    assert len(kept)>=1500,'滚动未来至少500开发+1000独立封存'
    dev=kept[:500];sealed=kept[500:min(len(kept),3500)]
    for name,part in [('future_dev',dev),('sealed_future',sealed)]:
        with (data/(name+'.jsonl')).open('w') as f:
            for r in part:f.write(json.dumps(r)+'\n')
    sha=hashlib.sha256((data/'sealed_future.jsonl').read_bytes()).hexdigest()
    save(data/'manifest.json',{'state':'COMPLETE',**audit,'future_dev':len(dev),'sealed_count':len(sealed),'sealed_sha256':sha,
                             'limitations':'评论评分正序列；train候选与共享元数据；用户train前缀可能参与已有模型训练；验收是未见未来事件，不是未见用户。'})
    save(data/'sealed_snapshot_ready.json',{'state':'READY','timestamp':time.time(),'sha256':sha,'count':len(sealed)})

if __name__=='__main__':main()
