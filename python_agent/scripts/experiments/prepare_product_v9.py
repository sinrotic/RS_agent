"""全量训练期正序列转紧凑数组；保留未参与旧模型训练的用户用于开发/封存验收。"""
import array,bisect,hashlib,heapq,json,time
from pathlib import Path
import numpy as np
ROOT=Path('/mnt/data/luo/remote_runs/product_v9_training')
V7=Path('/mnt/data/luo/remote_runs/product_v7_expansion')
OLD=Path('/mnt/data/luo/remote_runs/three_tower_dataset_v4/data')
SOURCE=Path('/home/luo/RS_agent_remote/data/processed/amazon_2023_recall_recent_2y_1m_3m')

def stream(path):
    with path.open() as f:
        for line in f:yield json.loads(line)

def main():
    ROOT.mkdir(exist_ok=True);out=ROOT/'data';out.mkdir(exist_ok=False);started=time.time()
    excluded={r['index'] for r in json.loads((V7/'data/text_audit.json').read_text())['ineligible']}
    mapping={r['item_id']:r['index'] for r in stream(V7/'data/items.jsonl') if r['index'] not in excluded}
    previous={r['user_hash'] for r in stream(OLD/'rec_train.jsonl')}
    for p in [OLD/'rec_valid.jsonl',V7/'data/rec_dev.jsonl',V7/'data/rec_confirm.jsonl',OLD.parent/'final_test/confirmation_rows.jsonl']:
        previous.update(r['user_hash'] for r in stream(p))
    cutoff=json.loads((SOURCE/'manifest.json').read_text())['window_policy']['splits']['train']['end_ms']
    values=array.array('i');offsets=array.array('q',[0]);examples=array.array('i');hashes=[];holdout=[]
    for line,r in enumerate(stream(SOURCE/'user_sequences.train.jsonl')):
        ids=r['recent_positive_item_sequence'];ts=r['recent_positive_timestamp_sequence'];assert len(ids)==len(ts)
        if len(ids)<3:continue
        assert all(t<cutoff for t in ts)
        ordered=sorted((t,iid) for iid,t in zip(ids,ts) if iid in mapping)
        if len(ordered)<3:continue
        times=[t for t,_ in ordered];sequence=[mapping[iid] for _,iid in ordered]
        assert len(set(sequence))==len(sequence)
        positions=[(j,bisect.bisect_left(times,times[j])) for j in range(1,len(sequence)) if times[j]>times[0]]
        if not positions:continue
        uid=hashlib.sha256(r['user_id'].encode()).hexdigest();user_index=len(hashes);hashes.append(uid)
        values.extend(sequence);offsets.append(len(values))
        for j,end in positions[-20:]:examples.extend([user_index,j,end])
        if uid not in previous:
            key=int(hashlib.sha256(('v9-unseen-user:'+uid).encode()).hexdigest()[:16],16)
            j,end=positions[-1];history=sequence[max(0,end-50):end];target=sequence[j]
            row={'user_hash':uid,'history_old':[i for i in history if i<203887],'history_full':history,
                'old_target':target if target<203887 else -1,'target':target,'target_ts':times[j]}
            entry=(-key,user_index,row)
            if len(holdout)<3000:heapq.heappush(holdout,entry)
            elif entry[:2]>holdout[0][:2]:heapq.heapreplace(holdout,entry)
        if len(hashes)%100000==0:print('USERS',len(hashes),'EXAMPLES',len(examples)//3,flush=True)
    assert len(holdout)==3000
    holdout.sort(key=lambda r:r[0]);held={v[1] for v in holdout}
    examples=np.asarray(examples,dtype='int32').reshape(-1,3)
    examples=examples[~np.isin(examples[:,0],list(held))]
    np.save(out/'sequence_items.npy',np.asarray(values,dtype='int32'))
    np.save(out/'sequence_offsets.npy',np.asarray(offsets,dtype='int64'))
    np.save(out/'train_examples.npy',examples)
    for name,part in [('fresh_dev',holdout[::2]),('sealed_users',holdout[1::2])]:
        with (out/(name+'.jsonl')).open('w') as f:
            for _,_,row in part:f.write(json.dumps(row)+'\n')
    manifest={'state':'COMPLETE','users':len(hashes),'train_users':len(hashes)-len(held),'train_examples':len(examples),
        'fresh_dev_users':1500,'sealed_users':1500,'train_cutoff':cutoff,'source':str(SOURCE),
        'policy':'仅训练期序列；新开发/封存用户与此前10万训练用户及所有既有开发/确认用户不重合；整用户从v9训练排除；最后一个严格后于历史的正事件作目标',
        'limitations':'训练期的未见用户下一正事件评测，非全新未来月份；商品元数据和固定训练期候选库仍为共享的传导式特征，未用用户目标梯度训练模型',
        'seconds':time.time()-started,'sealed_sha256':hashlib.sha256((out/'sealed_users.jsonl').read_bytes()).hexdigest()}
    (out/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2));print(json.dumps(manifest,ensure_ascii=False),flush=True)

if __name__=='__main__':main()
