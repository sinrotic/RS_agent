"""把可用扩库向量、索引映射和冻结模型组成离线包；排除空文本，不发布。"""
import argparse,hashlib,json,os,shutil,subprocess,sys,time
from pathlib import Path
import numpy as np


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for b in iter(lambda:stream.read(4*1024*1024),b''):h.update(b)
    return h.hexdigest()


def main(args):
    root=args.root;result=json.loads((root/'comparison.json').read_text());assert result['state']=='COMPLETE'
    excluded={r['index'] for r in result['excluded_empty_text']}
    keep=np.array([i for i in range(result['catalog']['total_count']) if i not in excluded],dtype='int64')
    new_index=np.full(result['catalog']['total_count'],-1,dtype='int64');new_index[keep]=np.arange(len(keep))
    assert np.array_equal(new_index[:result['catalog']['old_count']],np.arange(result['catalog']['old_count']))
    assert len(keep)==result['eligible_candidate_count']
    mapping=root/'data/eligible_item_ids.jsonl'
    if not mapping.exists():
        with mapping.open('w',encoding='utf-8') as out,(root/'data/items.jsonl').open(encoding='utf-8') as stream:
            for index,line in enumerate(stream):
                r=json.loads(line);assert r['index']==index
                if index not in excluded:out.write(json.dumps({'index':int(new_index[index]),'item_id':r['item_id']})+'\n')
        assert index+1==result['catalog']['total_count']
    replay=root/'data/full_history_replay.jsonl'
    with replay.open('w',encoding='utf-8') as out,(root/'data/rec_dev.jsonl').open(encoding='utf-8') as stream:
        for line in stream:
            row=json.loads(line)
            # 仅供均匀聚合回放，不把旧的部分历史时间戳冒充补全后的时间戳。
            replay_row={'user_hash':row['user_hash'],'history':[int(new_index[i]) for i in row['history_full'] if i not in excluded],
                        'target':int(new_index[row['target']]) if row['target']>=0 else -1,'target_ts':row['target_ts']}
            out.write(json.dumps(replay_row)+'\n')
    sources={'online_v4':Path('/mnt/data/luo/remote_runs/three_tower_dataset_v4/export_joint_full_seed42'),
             'candidate_v6':Path('/mnt/data/luo/remote_runs/product_three_tower_v6_20261011/export_candidate')}
    manifests={}
    for name,source in sources.items():
        output=root/('export_'+name);output.mkdir(exist_ok=False)
        shutil.copy2(source/'model.pt',output/'model.pt');shutil.copy2(source/'model_definition.py',output/'model_definition.py')
        if excluded:
            source_vectors=np.load(root/(name+'_item_vectors.npy'),mmap_mode='r')
            destination=np.lib.format.open_memmap(output/'item_vectors.npy',mode='w+',dtype='float32',shape=(len(keep),1024))
            for s in range(0,len(keep),8192):destination[s:s+len(keep[s:s+8192])]=source_vectors[keep[s:s+8192]]
            destination.flush();del destination,source_vectors
        else:os.link(root/(name+'_item_vectors.npy'),output/'item_vectors.npy')
        os.link(mapping,output/'item_ids.jsonl')
        manifest={'status':'EXPANDED_CATALOG_OFFLINE_NOT_DEPLOYED','dimension':1024,'candidate_count':len(keep),'raw_candidate_count':result['catalog']['total_count'],
            'excluded_empty_text':result['excluded_empty_text'],'index_policy':'旧203887项索引不变；新增项仅在导出时跳过6项空文本，映射与向量同步压实',
            'model_weights_unchanged':True,'source_export':str(source),'source_checkpoint_sha256':result['models'][name]['checkpoint_sha256'],
            'catalog_sha256':result['catalog']['catalog_sha256'],'query_task_trained':True,
            'output_hashes':{n:digest(output/n) for n in ['model.pt','model_definition.py','item_vectors.npy','item_ids.jsonl']},
            'serving_contract':'现有残差运行时；最近<=50条已知商品历史均匀聚合，1024维；item向量不得二次过塔',
            'online_modified':False,'created_unix':time.time()}
        (output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
        command=[sys.executable,str(root/'scripts/verify_product_v6_runtime.py'),'--data','/mnt/data/luo/remote_runs/three_tower_dataset_v4/data',
            '--evaluation',str(replay),'--export',str(output),'--runtime-directory','/mnt/data/luo/remote_runs/three_tower_dataset_v4']
        with (root/(name+'_runtime_replay.log')).open('w') as log:
            subprocess.run(command,check=True,stdout=log,stderr=subprocess.STDOUT,env={**os.environ,'CUDA_VISIBLE_DEVICES':''},timeout=600)
        manifests[name]={'manifest':manifest,'runtime_replay':json.loads((output/'runtime_replay.json').read_text())}
    (root/'packages.json').write_text(json.dumps(manifests,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps({n:r['runtime_replay'] for n,r in manifests.items()},ensure_ascii=False),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--root',type=Path,required=True);main(p.parse_args())
