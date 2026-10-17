"""构建从未评估用户的下一时间窗验收；历史只来自目标窗口之前。"""
import hashlib,json,time
from pathlib import Path
from evaluate_product_v7_catalog import save

BASE=Path('/mnt/data/luo/remote_runs');ROOT=BASE/'product_v12_training'
SOURCE=Path('/home/luo/RS_agent_remote/data/processed/amazon_2023_recall_recent_2y_1m_3m')

def stream(p):
    with p.open() as f:
        for line in f:yield json.loads(line)

def main():
    data=ROOT/'data';data.mkdir(exist_ok=True);assert not any(data.iterdir())
    excluded={r['index'] for r in json.loads((BASE/'product_v7_expansion/data/text_audit.json').read_text())['ineligible']}
    mapping={r['item_id']:r['index'] for r in stream(BASE/'product_v7_expansion/data/items.jsonl') if r['index'] not in excluded}
    previous=set()
    for name in ['three_tower_dataset_v4/data/rec_valid.jsonl','three_tower_dataset_v4/final_test/confirmation_rows.jsonl',
                 'product_v7_expansion/data/rec_dev.jsonl','product_v7_expansion/data/rec_confirm.jsonl',
                 'product_v9_training/data/fresh_dev.jsonl','product_v9_training/data/sealed_users.jsonl',
                 'product_v10_training/data/future_dev.jsonl','product_v10_training/data/sealed_future.jsonl',
                 'product_v11_training/data/sealed_future.jsonl']:
        previous.update(r['user_hash'] for r in stream(BASE/name))
    window=json.loads((SOURCE/'manifest.json').read_text())['window_policy']['splits']['test']
    cutoff=window['start_ms'];targets={};histories={}
    for r in stream(SOURCE/'canonical_interactions.test.jsonl'):
        if r['label_binary']!=1:continue
        uid=hashlib.sha256(r['user_id'].encode()).hexdigest()
        if uid in previous:continue
        value=(r['timestamp'],r['parent_asin'])
        assert cutoff<=value[0]<window['end_ms']
        if uid not in targets or value<targets[uid]:targets[uid]=value
    for r in stream(SOURCE/'user_sequences.train.jsonl'):
        uid=hashlib.sha256(r['user_id'].encode()).hexdigest()
        if uid not in targets:continue
        ids=r['recent_positive_item_sequence'];ts=r['recent_positive_timestamp_sequence'];assert len(ids)==len(ts)
        histories[uid]=[(t,mapping[i]) for i,t in zip(ids,ts) if i in mapping]
    for r in stream(SOURCE/'canonical_interactions.valid.jsonl'):
        if r['label_binary']!=1 or r['parent_asin'] not in mapping:continue
        uid=hashlib.sha256(r['user_id'].encode()).hexdigest()
        if uid in targets:histories.setdefault(uid,[]).append((r['timestamp'],mapping[r['parent_asin']]))
    kept=[];lengths={};seen_target=0
    for uid,seq in histories.items():
        # 与HTTP运行时相同：最近优先去重后最多50项，再转成训练时间升序。
        ordered=[];seen=set()
        for t,i in sorted(seq,reverse=True):
            assert t<cutoff
            if i not in seen:ordered.append(i);seen.add(i)
            if len(ordered)==50:break
        history=ordered[::-1]
        if len(history)<2:continue
        ts,iid=targets[uid];target=mapping.get(iid,-1)
        if target in history:seen_target+=1;continue
        lengths[len(history)]=lengths.get(len(history),0)+1
        kept.append({'user_hash':uid,'history_full':history,'history_old':[i for i in history if i<203887],
                     'target':target,'old_target':target if 0<=target<203887 else -1,'target_ts':ts})
    kept.sort(key=lambda r:hashlib.sha256(('v12-future:'+r['user_hash']).encode()).digest())
    audit={'eligible':len(kept),'history_lengths':lengths,'previous_users':len(previous),'excluded_repeated_target':seen_target,
           'window':window,'policy':'首次test正事件；截至test开始的train+valid历史。用户不在任何此前评测群体。test标签不用于梯度；不能据目标覆盖率筛选。'}
    save(ROOT/'cohort_audit.json',audit);print('FUTURE_COHORT_AUDIT',json.dumps(audit),flush=True)
    assert len(kept)>=2000,'至少需要1000开发和1000独立封存用户'
    dev=kept[:1000];sealed=kept[1000:min(len(kept),4000)]
    for name,part in [('future_dev',dev),('sealed_future',sealed)]:
        with (data/(name+'.jsonl')).open('w') as f:
            for r in part:f.write(json.dumps(r)+'\n')
    sha=hashlib.sha256((data/'sealed_future.jsonl').read_bytes()).hexdigest()
    save(data/'manifest.json',{'state':'COMPLETE',**audit,'future_dev':len(dev),'sealed_count':len(sealed),'sealed_sha256':sha,
                             'limitations':'评论评分正序列；仅训练期候选商品。valid事件仅作为test之前可用的历史，没有作为训练目标。已有模型可能学过用户train前缀，故是已知用户未来目标检验。'})
    save(data/'sealed_snapshot_ready.json',{'state':'READY','timestamp':time.time(),'sha256':sha,'count':len(sealed)})

if __name__=='__main__':main()
