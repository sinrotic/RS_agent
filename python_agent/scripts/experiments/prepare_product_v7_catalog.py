"""仅按训练期正反馈扩充商品库；旧索引不变，验证用户固定。"""
import argparse,hashlib,json,time
from pathlib import Path


def rows(path):
    with path.open(encoding='utf-8') as stream:
        for line in stream:yield json.loads(line)


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
    return h.hexdigest()


def main(args):
    args.output.mkdir(parents=True,exist_ok=False);started=time.time()
    source_manifest=json.loads((args.data/'data_manifest.json').read_text());source=Path(source_manifest['source'])
    cutoff=source_manifest['train_cutoff'];end=source_manifest['valid_end']
    cohorts={n:list(rows(args.evaluation/(n+'.jsonl'))) for n in ['rec_dev','rec_confirm']}
    selected={r['user_hash'] for v in cohorts.values() for r in v};histories={};positive=set();count=0
    for r in rows(source/'user_sequences.train.jsonl'):
        ids=r['recent_positive_item_sequence'];ts=r['recent_positive_timestamp_sequence']
        assert len(ids)==len(ts) and all(t<cutoff for t in ts)
        positive.update(ids);count+=1
        uid_hash=hashlib.sha256(r['user_id'].encode()).hexdigest()
        if uid_hash in selected:histories[uid_hash]=sorted(zip(ids,ts),key=lambda v:(v[1],v[0]))[-50:]
    assert histories.keys()==selected
    mapping={}
    with (args.output/'items.jsonl').open('w',encoding='utf-8') as out:
        for r in rows(args.data/'items.jsonl'):
            assert r['index']==len(mapping) and r['item_id'] not in mapping
            mapping[r['item_id']]=r['index'];out.write(json.dumps(r,ensure_ascii=False)+'\n')
        old_count=len(mapping);needed=positive-mapping.keys();expected=len(needed)
        for r in rows(source/'canonical_items.jsonl'):
            iid=r['parent_asin']
            if iid not in needed:continue
            facts=[{'field':'title_clean','text':r.get('title_clean','').strip()[:400]}]
            for field in ['features_text','description_text']:
                if r.get(field,'').strip():facts.append({'field':field,'text':r[field].strip()[:700]})
            item={'index':len(mapping),'item_id':iid,'text':'\n'.join(f['text'] for f in facts),'category':r.get('category',''),'facts':facts}
            mapping[iid]=item['index'];needed.remove(iid);out.write(json.dumps(item,ensure_ascii=False)+'\n')
    assert not needed, 'training positives missing catalog metadata'
    # 到此候选库已固定；之后才读取valid目标，绝不按目标补充词表。
    catalog_sha=digest(args.output/'items.jsonl');targets={}
    for r in rows(source/'canonical_interactions.valid.jsonl'):
        if r['label_binary']!=1:continue
        assert cutoff<=r['timestamp']<end
        uid_hash=hashlib.sha256(r['user_id'].encode()).hexdigest()
        if uid_hash not in selected:continue
        value=(r['timestamp'],r['parent_asin'])
        if uid_hash not in targets or value<targets[uid_hash]:targets[uid_hash]=value
    summaries={}
    for name,batch in cohorts.items():
        output=[]
        for r in batch:
            ts,iid=targets[r['user_hash']];history=histories[r['user_hash']]
            assert ts==r['target_ts'] and iid not in {i for i,_ in history}
            h=[mapping[i] for i,_ in history];old_h=[i for i in h if i<old_count]
            assert old_h==r['history']
            target=mapping.get(iid,-1);assert (target if 0<=target<old_count else -1)==r['target']
            output.append({**r,'old_target':r['target'],'target':target,'history_old':old_h,'history_full':h})
        path=args.output/(name+'.jsonl')
        with path.open('w',encoding='utf-8') as out:
            for r in output:out.write(json.dumps(r)+'\n')
        summaries[name]={'users':len(output),'old_covered':sum(r['old_target']>=0 for r in output),'expanded_covered':sum(r['target']>=0 for r in output),
            'old_empty_history':sum(not r['history_old'] for r in output),'expanded_empty_history':sum(not r['history_full'] for r in output),'sha256':digest(path)}
    result={'state':'READY','old_count':old_count,'new_count':expected,'total_count':len(mapping),'source_train_sequences':count,
        'candidate_policy':'旧词表并集所有保留的训练期正反馈商品；读取valid目标前固定候选文件哈希；旧索引不变',
        'cohorts':summaries,'catalog_sha256':catalog_sha,'seconds':time.time()-started,'source_manifest':source_manifest,
        'limitations':['训练历史最多保留50项','商品元数据继承回溯快照','v6确认用户已被用过，本轮属于固定模型的配对复评，不再称全新确认集','官方最终test未读取']}
    (args.output/'manifest.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for n in ['data','evaluation','output']:p.add_argument('--'+n,type=Path,required=True)
    main(p.parse_args())
