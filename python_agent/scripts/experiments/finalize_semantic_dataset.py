"""检查时间/切分与向量对齐，生成可直接传给三塔训练器的数据目录。"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import time
import numpy as np


def rows(path):
    with path.open(encoding='utf-8') as f:
        for line in f:
            yield json.loads(line)


def save(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''):h.update(b)
    return h.hexdigest()


def main():
    ap=argparse.ArgumentParser();ap.add_argument('--data',type=Path,required=True)
    args=ap.parse_args();data=args.data
    if os.environ.get('CUDA_VISIBLE_DEVICES')!='2':raise ValueError('GPU 2 only')
    if not (data/'encoding_metrics.json').exists():raise ValueError('item encoding incomplete')
    manifest=json.loads((data/'data_manifest.json').read_text())
    semantics=list(rows(data/'semantic_clean.jsonl'))
    heldout=list(rows(data/'semantic_test.jsonl'))
    counts=Counter(r['split'] for r in semantics)
    if counts['train']<1800 or counts['valid']<200 or len(heldout)<200:
        raise ValueError('insufficient accepted semantics; review before training')
    if any(r['split'] not in ['train','valid'] for r in semantics):raise ValueError('test leak')
    groups={s:{r['group'] for r in semantics+heldout if r['split']==s} for s in ['train','valid','test']}
    assert not(groups['train']&groups['valid'] or groups['train']&groups['test'] or groups['valid']&groups['test'])
    items={r['item_id']:r['index'] for r in rows(data/'items.jsonl')}
    n=len(items)
    assert all(items[r['item_id']]==r['item_index'] for r in semantics+heldout)
    features=np.load(data/'item_features.npy',mmap_mode='r')
    assert features.shape==(n,1024)
    for start in range(0,n,4096):
        batch=features[start:start+4096]
        assert np.isfinite(batch).all()
        assert np.allclose(np.linalg.norm(batch,axis=1),1,atol=.003)
    rec_counts={}
    for name in ['rec_train.jsonl','rec_valid.jsonl']:
        count=0
        for r in rows(data/name):
            count+=1
            assert r['history'] and len(r['history'])==len(r['history_ts'])
            assert max(r['history_ts'])<r['target_ts']
            assert all(0<=i<n for i in r['history'])
            assert r['target'] not in r['history']
            if name=='rec_train.jsonl':assert 0<=r['target']<n and r['target_ts']<manifest['train_cutoff']
            else:assert -1<=r['target']<n and manifest['train_cutoff']<=r['target_ts']<manifest['valid_end']
        rec_counts[name]=count
    import torch
    from sentence_transformers import SentenceTransformer
    started=time.perf_counter();torch.cuda.set_per_process_memory_fraction(.5)
    model=SentenceTransformer('/home/luo/RS_agent_java/data/models/BAAI/bge-m3',device='cuda',local_files_only=True)
    model.half();model.max_seq_length=256
    vectors=model.encode([r['query'] for r in semantics],batch_size=32,normalize_embeddings=True,
                         show_progress_bar=False,convert_to_numpy=True).astype('float32')
    assert vectors.shape==(len(semantics),1024) and np.isfinite(vectors).all()
    np.save(data/'query_features.npy',vectors)
    # 嵌套学习曲线固定开发集，仅改变训练商品组数，并同步抽取向量行。
    learning_curves={}
    for size in [200,400,800]:
        groups_in={r['group'] for r in rows(data/f'semantic_train_groups_{size}.jsonl')}
        indexes=[i for i,r in enumerate(semantics) if r['split']=='valid' or r['group'] in groups_in]
        folder=data.parent/f'curve_{size}';folder.mkdir(exist_ok=True)
        for name in ['items.jsonl','item_features.npy','rec_train.jsonl','rec_valid.jsonl']:
            link=folder/name
            if not link.exists():link.symlink_to(data/name)
        (folder/'semantic_clean.jsonl').write_text(''.join(json.dumps(semantics[i],ensure_ascii=False)+'\n' for i in indexes),encoding='utf-8')
        np.save(folder/'query_features.npy',vectors[indexes])
        learning_curves[str(size)]={'train_groups':len(groups_in),'train_queries':sum(semantics[i]['split']=='train' for i in indexes),
            'valid_queries':counts['valid'],'data':str(folder)}
    report={'status':'READY_FOR_BOUNDED_EXPERIMENT_NOT_PRODUCTION','recommendation':rec_counts,
        'candidate_count':n,'semantic_train':counts['train'],'semantic_valid':counts['valid'],
        'synthetic_test_separate':len(heldout),'learning_curves':learning_curves,
        'checks':['item/vector alignment','finite normalized vectors','recommendation time order',
            'target absent from history','semantic group split disjoint','test excluded from training input'],
        'query_encoding_seconds':time.perf_counter()-started,'peak_cuda_gib':torch.cuda.max_memory_allocated()/2**30,
        'human_gold_available':False,'full_catalog_evaluation':False,'training_started':False,
        'hashes':{name:digest(data/name) for name in ['rec_train.jsonl','rec_valid.jsonl','items.jsonl',
            'item_features.npy','semantic_clean.jsonl','semantic_test.jsonl','query_features.npy']}}
    save(data/'dataset_readiness.json',report)
    print(json.dumps(report,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
