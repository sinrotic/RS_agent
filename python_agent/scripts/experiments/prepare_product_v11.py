"""构建剩余未见未来目标，并初始化与v10最佳聚合严格一致的注意力模型。"""
import hashlib,json,sys,os,time
from pathlib import Path
import torch
from product_v11_model import AttentionResidualTowers
ROOT=Path('/mnt/data/luo/remote_runs/product_v11_training');V10=ROOT.parent/'product_v10_training';V7=ROOT.parent/'product_v7_expansion';V9=ROOT.parent/'product_v9_training';V4=ROOT.parent/'three_tower_dataset_v4'
sys.path.insert(0,str(V10/'scripts'))
from prepare_product_v10_eval import stream,SOURCE
from evaluate_product_v7_catalog import save
def main():
    ROOT.mkdir(exist_ok=True);out=ROOT/'data';out.mkdir(exist_ok=False)
    os.link(V10/'data/future_dev.jsonl',out/'future_dev.jsonl')
    excluded={r['index'] for r in json.loads((V7/'data/text_audit.json').read_text())['ineligible']}
    mapping={r['item_id']:r['index'] for r in stream(V7/'data/items.jsonl') if r['index'] not in excluded}
    previous=set()
    for p in [V4/'data/rec_valid.jsonl',V7/'data/rec_dev.jsonl',V7/'data/rec_confirm.jsonl',V9/'data/fresh_dev.jsonl',V9/'data/sealed_users.jsonl',V4/'final_test/confirmation_rows.jsonl',V10/'data/future_dev.jsonl',V10/'data/sealed_future.jsonl']:
        previous.update(r['user_hash'] for r in stream(p))
    targets={};window=json.loads((SOURCE/'manifest.json').read_text())['window_policy']['splits']['valid']
    for r in stream(SOURCE/'canonical_interactions.valid.jsonl'):
        if r['label_binary']!=1:continue
        uid=hashlib.sha256(r['user_id'].encode()).hexdigest()
        if uid in previous:continue
        value=(r['timestamp'],r['parent_asin'])
        assert window['start_ms']<=value[0]<window['end_ms']
        if uid not in targets or value<targets[uid]:targets[uid]=value
    kept=[];cutoff=window['start_ms']
    for r in stream(SOURCE/'user_sequences.train.jsonl'):
        uid=hashlib.sha256(r['user_id'].encode()).hexdigest()
        if uid not in targets:continue
        ids=r['recent_positive_item_sequence'];ts=r['recent_positive_timestamp_sequence'];assert len(ids)==len(ts)
        seq=sorted((t,mapping[i]) for i,t in zip(ids,ts) if i in mapping)
        if len(seq)<2:continue
        assert all(t<cutoff for t,_ in seq)
        history=[i for _,i in seq][-50:];t,iid=targets[uid];target=mapping.get(iid,-1)
        if target in history:continue
        kept.append({'user_hash':uid,'history_old':[i for i in history if i<203887],'history_full':history,'old_target':target if 0<=target<203887 else -1,'target':target,'target_ts':t})
    kept.sort(key=lambda r:hashlib.sha256(('v11-sealed:'+r['user_hash']).encode()).digest());assert len(kept)>=1000
    with (out/'sealed_future.jsonl').open('w') as f:
        for r in kept[:1000]:f.write(json.dumps(r)+'\n')
    sha=hashlib.sha256((out/'sealed_future.jsonl').read_bytes()).hexdigest()
    save(out/'manifest.json',{'state':'COMPLETE','sealed_count':1000,'eligible_remaining':len(kept),'source_window':window,'sealed_min_history':2,'sealed_sha256':sha,
        'limitations':'剩余未见未来用户均短历史；长历史只有已见回归。训练BGE/商品共享特征，目标从未用于梯度或之前评估。'})
    save(out/'sealed_snapshot_ready.json',{'state':'READY','count':1000,'sha256':sha,'timestamp':time.time()})
    base=torch.load(V10/'initial_cohesion.pt',map_location='cpu',weights_only=True)
    torch.manual_seed(42);model=AttentionResidualTowers(1024,256,763086,0)
    missing,unexpected=model.load_state_dict(base['model'],strict=False)
    assert not unexpected and all(x.startswith('user.pool_') for x in missing)
    torch.save({'model':model.state_dict(),'config':{**base['config'],'pooling':'attention_cohesion','pool_hidden':64}},ROOT/'initial.pt')
    print('UNSEEN_SEALED_READY',len(kept),'INITIAL_ATTENTION_ZERO',flush=True)
if __name__=='__main__':main()
