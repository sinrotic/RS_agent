"""新的未来验证目标；目标不进入训练，封存标签仅冻结选型后读取。"""
import hashlib,heapq,json,time
from pathlib import Path
from evaluate_product_v7_catalog import save
ROOT=Path('/mnt/data/luo/remote_runs/product_v10_training')
V7=ROOT.parent/'product_v7_expansion';V9=ROOT.parent/'product_v9_training';V4=ROOT.parent/'three_tower_dataset_v4'
SOURCE=Path('/home/luo/RS_agent_remote/data/processed/amazon_2023_recall_recent_2y_1m_3m')
def stream(p):
    with p.open() as f:
        for line in f:yield json.loads(line)
def main():
    out=ROOT/'data';out.mkdir(exist_ok=True);assert not any(out.iterdir());began=time.time()
    excluded={x['index'] for x in json.loads((V7/'data/text_audit.json').read_text())['ineligible']}
    mapping={r['item_id']:r['index'] for r in stream(V7/'data/items.jsonl') if r['index'] not in excluded}
    previous=set()
    for p in [V4/'data/rec_valid.jsonl',V7/'data/rec_dev.jsonl',V7/'data/rec_confirm.jsonl',V9/'data/fresh_dev.jsonl',V9/'data/sealed_users.jsonl',V4/'final_test/confirmation_rows.jsonl']:
        previous.update(r['user_hash'] for r in stream(p))
    # 先选用户哈希，再取其首个正目标，不以目标商品是否易召回决定抽样。
    targets={}
    window=json.loads((SOURCE/'manifest.json').read_text())['window_policy']['splits']['valid']
    for r in stream(SOURCE/'canonical_interactions.valid.jsonl'):
        if r['label_binary']!=1:continue
        uid=hashlib.sha256(r['user_id'].encode()).hexdigest()
        if uid in previous:continue
        value=(r['timestamp'],r['parent_asin']);assert window['start_ms']<=value[0]<window['end_ms']
        if uid not in targets or value<targets[uid]:targets[uid]=value
    selected=set(targets)
    retained=[];cutoff=json.loads((SOURCE/'manifest.json').read_text())['window_policy']['splits']['train']['end_ms']
    for r in stream(SOURCE/'user_sequences.train.jsonl'):
        uid=hashlib.sha256(r['user_id'].encode()).hexdigest()
        if uid not in selected:continue
        ids=r['recent_positive_item_sequence'];ts=r['recent_positive_timestamp_sequence'];assert len(ids)==len(ts)
        seq=sorted((t,mapping[i]) for i,t in zip(ids,ts) if i in mapping)
        if len(seq)<2:continue
        assert all(t<cutoff for t,_ in seq)
        history=[i for _,i in seq][-50:];target_ts,target_id=targets[uid];target=mapping.get(target_id,-1)
        if target in history:continue
        retained.append({'user_hash':uid,'history_old':[i for i in history if i<203887],'history_full':history,
            'old_target':target if 0<=target<203887 else -1,'target':target,'target_ts':target_ts})
    retained.sort(key=lambda r:hashlib.sha256(('v10-future:'+r['user_hash']).encode()).digest())
    print('ELIGIBLE_FUTURE_USERS',len(retained),flush=True)
    assert len(retained)>=3000
    chosen=retained[:3000]
    for name,part in [('future_dev',chosen[:1000]),('sealed_future',chosen[1000:])]:
        with (out/(name+'.jsonl')).open('w') as f:
            for r in part:f.write(json.dumps(r)+'\n')
    save(out/'manifest.json',{'state':'COMPLETE','future_dev':1000,'sealed_future':2000,'source_window':window,
        'sealed_sha256':hashlib.sha256((out/'sealed_future.jsonl').read_bytes()).hexdigest(),
        'policy':'新验证期首个正目标；训练期历史；与此前开发/确认/封存及历史测试用户不重合。目标不在训练期用户序列；整用户可有训练期样本，属于已知用户未来事件评估。选型前不评估封存标签。',
        'limitations':'候选及元数据沿用既有固定训练期快照；此前模型可能使用这些用户的训练期历史，非未见用户检验；评分评论正序列非购买完成事件。',
        'seconds':time.time()-began})
    print('NEW_FUTURE_COHORTS_READY',len(chosen),flush=True)
if __name__=='__main__':main()
