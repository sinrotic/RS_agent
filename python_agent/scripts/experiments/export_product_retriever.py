"""导出商品残差召回候选包；验证离线前向一致性，不授权替换在线路由。"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import numpy as np
import torch
import torch.nn.functional as F
from three_tower_residual import ResidualTowers, history_tensor


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(4*1024*1024),b''):h.update(chunk)
    return h.hexdigest()


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--data',type=Path,required=True)
    parser.add_argument('--checkpoint',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    if os.environ.get('CUDA_VISIBLE_DEVICES')!='2':raise ValueError('GPU 2 only')
    torch.set_num_threads(4);torch.cuda.set_per_process_memory_fraction(.5)
    state=torch.load(args.checkpoint,map_location='cpu',weights_only=True)
    config=state['config']
    if config['id_dim']!=0 or config['history_half_life_days']!=0:
        raise ValueError('this export supports uniform-history no-ID product residual model only')
    source=np.load(args.data/'item_features.npy',mmap_mode='r')
    model=ResidualTowers(source.shape[1],config['hidden'],len(source),0).cuda().eval()
    model.load_state_dict(state['model'])
    args.output.mkdir(parents=True,exist_ok=False)
    vectors=np.lib.format.open_memmap(args.output/'item_vectors.npy',mode='w+',dtype='float32',shape=source.shape)
    with torch.inference_mode():
        for start in range(0,len(source),1024):
            features=F.normalize(torch.tensor(source[start:start+1024],device='cuda'),dim=-1)
            vectors[start:start+len(features)]=model.encode_items(features).cpu().numpy()
    vectors.flush()
    with (args.output/'item_ids.jsonl').open('w',encoding='utf-8') as output:
        for line in (args.data/'items.jsonl').open(encoding='utf-8'):
            item=json.loads(line)
            output.write(json.dumps({'index':item['index'],'item_id':item['item_id']})+'\n')
    # 用同一有序历史比较训练前向和导出向量聚合；导出向量不可再次过Item塔。
    validation=[json.loads(line) for line in (args.data/'rec_valid.jsonl').open()][:128]
    ids,mask=history_tensor(validation,'cuda',0.)
    unique,inverse=torch.unique(ids,return_inverse=True)
    with torch.inference_mode():
        encoded=model.encode_items(F.normalize(torch.tensor(source[unique.cpu().numpy()],device='cuda'),dim=-1))
        expected=model.encode_user(encoded[inverse],mask)
        exported=model.encode_user(torch.tensor(vectors[ids.cpu().numpy()],device='cuda'),mask)
        error=float((expected-exported).abs().max())
        scores_a=expected@torch.tensor(vectors[:2048],device='cuda').T
        scores_b=exported@torch.tensor(vectors[:2048],device='cuda').T
        score_error=float((scores_a-scores_b).abs().max())
    if error>2e-6 or score_error>2e-6:raise ValueError('export forward mismatch')
    for start in range(0,len(vectors),4096):
        batch=vectors[start:start+4096]
        assert np.isfinite(batch).all() and np.allclose(np.linalg.norm(batch,axis=1),1,atol=.0001)
    shutil.copy2(args.checkpoint,args.output/'model.pt')
    shutil.copy2(Path(__file__).with_name('three_tower_residual.py'),args.output/'model_definition.py')
    manifest={'status':'OFFLINE_EXPORT_VERIFIED_NOT_DEPLOYED','model_type':'product_residual_no_id_v4',
        'training_mode':config['mode'],'dimension':source.shape[1],'candidate_count':len(source),
        'checkpoint_step':state['step'],'seed':config['seed'],
        'user_forward':'normalize(mean(exported item vectors of ordered last <=50 positive items) + user_adapter(mean))',
        'history_weighting':'uniform; no queryv2 time decay','unknown_history':'skip unknown IDs; empty known history requires existing fallback',
        'item_forward':'normalize(normalized BGE vector + item_adapter(normalized BGE vector))',
        'query_forward':'normalize(normalized BGE query + query_adapter(normalized BGE query))',
        'query_task_trained':config['mode']=='joint','bge':'local BAAI/bge-m3; max_seq_length=256; fp16 encoding, normalized float32 cache',
        'similarity':'inner product of unit vectors',
        'route_limitations':['203887-candidate experimental library, not full catalog',
            '1024 dimensions require separate index from old 64-dimensional queryv2 route',
            'must not apply item adapter twice to exported history vectors',
            'development-selected candidate requires independent test and serving replay before main-route promotion'],
        'verification':{'users':len(validation),'max_user_vector_error':error,'max_score_error':score_error},
        'input_hashes':{'checkpoint':digest(args.checkpoint),'bge_features':digest(args.data/'item_features.npy')},
        'output_hashes':{name:digest(args.output/name) for name in ['item_vectors.npy','item_ids.jsonl','model.pt','model_definition.py']}}
    (args.output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(manifest,ensure_ascii=False),flush=True)


if __name__=='__main__':main()
