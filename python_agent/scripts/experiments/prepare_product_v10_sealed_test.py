"""在冻结前预留未使用的测试期用户；不以可召回性选样，不计算封存指标。"""
import hashlib,json,time
from pathlib import Path
from evaluate_product_v7_catalog import save
ROOT=Path('/mnt/data/luo/remote_runs/product_v10_training');V7=ROOT.parent/'product_v7_expansion';V9=ROOT.parent/'product_v9_training';V4=ROOT.parent/'three_tower_dataset_v4'
SOURCE=Path('/home/luo/RS_agent_remote/data/processed/amazon_2023_recall_recent_2y_1m_3m')
def stream(p):
    with p.open() as f:
        for line in f:yield json.loads(line)
def main():
    assert not (ROOT/'selection.json').exists(),'cannot replace sealed data after selection'
    began=time.time();out=ROOT/'data'
    excluded={r['index'] for r in json.loads((V7/'data/text_audit.json').read_text())['ineligible']}
    mapping={r['item_id']:r['index'] for r in stream(V7/'data/items.jsonl') if r['index'] not in excluded}
    previous=set()
    for p in [V4/'data/rec_valid.jsonl',V7/'data/rec_dev.jsonl',V7/'data/rec_confirm.jsonl',V9/'data/fresh_dev.jsonl',V9/'data/sealed_users.jsonl',V4/'final_test/confirmation_rows.jsonl',out/'future_dev.jsonl',out/'sealed_future.jsonl']:
        previous.update(r['user_hash'] for r in stream(p))
    policy=json.loads((SOURCE/'manifest.json').read_text())['window_policy']['splits'];targets={}
    for r in stream(SOURCE/'canonical_interactions.test.jsonl'):
        if r['label_binary']!=1:continue
        uid=hashlib.sha256(r['user_id'].encode()).hexdigest()
        if uid in previous:continue
        v=(r['timestamp'],r['parent_asin']);assert policy['test']['start_ms']<=v[0]<policy['test']['end_ms']
        if uid not in targets or v<targets[uid]:targets[uid]=v
    retained=[]
    for r in stream(SOURCE/'user_sequences.train.jsonl'):
        uid=hashlib.sha256(r['user_id'].encode()).hexdigest()
        if uid not in targets:continue
        ids=r['recent_positive_item_sequence'];ts=r['recent_positive_timestamp_sequence'];assert len(ids)==len(ts)
        seq=sorted((t,mapping[i]) for i,t in zip(ids,ts) if i in mapping)
        if len(seq)<3:continue
        assert all(t<policy['train']['end_ms'] for t,_ in seq)
        history=[i for _,i in seq][-50:];t,iid=targets[uid];target=mapping.get(iid,-1)
        if target in history:continue
        retained.append({'user_hash':uid,'history_old':[i for i in history if i<203887],'history_full':history,
            'old_target':target if 0<=target<203887 else -1,'target':target,'target_ts':t})
    retained.sort(key=lambda r:hashlib.sha256(('v10-sealed-test:'+r['user_hash']).encode()).digest())
    print('UNUSED_TEST_ELIGIBLE',len(retained),flush=True);assert len(retained)>=2000
    assert not (ROOT/'selection.json').exists()
    # 保留原短历史封存文件，不在本轮使用或评估它。
    (out/'sealed_future.jsonl').rename(out/'sealed_future_valid_short_history.jsonl')
    with (out/'sealed_future.jsonl').open('w') as f:
        for r in retained[:2000]:f.write(json.dumps(r)+'\n')
    manifest=json.loads((out/'manifest.json').read_text());manifest.update(sealed_source_window=policy['test'],sealed_sha256=hashlib.sha256((out/'sealed_future.jsonl').read_bytes()).hexdigest(),
        sealed_min_history=3,sealed_policy='未被此前开发/确认/封存或历史测试使用的2000用户；后续测试期首个正目标；训练期历史至少3条；不按目标覆盖或可召回性过滤。选型前只构建和校验边界，不评估指标。',
        original_short_history_sealed_preserved='sealed_future_valid_short_history.jsonl')
    save(out/'manifest.json',manifest);save(out/'sealed_test_ready.json',{'state':'READY','count':2000,'seconds':time.time()-began,'sha256':manifest['sealed_sha256']})
if __name__=='__main__':main()
