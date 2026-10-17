"""导出三塔离线候选并验证商品/用户/查询前向；不创建在线索引。"""
import argparse,hashlib,json,os,shutil,time
from pathlib import Path
import numpy as np
import torch
import torch.nn.functional as F
from three_tower_residual import ResidualTowers,history_tensor,rows


def sha(path):
    digest=hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda:stream.read(4*1024*1024),b''):digest.update(chunk)
    return digest.hexdigest()


def export(args):
    if os.environ.get('CUDA_VISIBLE_DEVICES')!='2':raise RuntimeError('GPU2 only')
    torch.set_num_threads(2);torch.set_num_interop_threads(1);torch.cuda.set_per_process_memory_fraction(.20)
    state=torch.load(args.checkpoint,map_location='cpu',weights_only=True)
    source=np.load(args.data/'item_features.npy',mmap_mode='r')
    model=ResidualTowers(source.shape[1],256,len(source),0).cuda().eval();model.load_state_dict(state['model'],strict=True)
    args.output.mkdir(parents=True,exist_ok=False)
    vectors=np.lib.format.open_memmap(args.output/'item_vectors.npy',mode='w+',dtype='float32',shape=source.shape)
    with torch.inference_mode():
        for s in range(0,len(source),512):
            f=F.normalize(torch.tensor(source[s:s+512],device='cuda'),dim=-1)
            vectors[s:s+len(f)]=model.encode_items(f).cpu().numpy()
    vectors.flush()
    with (args.output/'item_ids.jsonl').open('w',encoding='utf-8') as out:
        for r in rows(args.data/'items.jsonl'):out.write(json.dumps({'index':r['index'],'item_id':r['item_id']})+'\n')
    cpu_model=ResidualTowers(source.shape[1],256,len(source),0).eval();cpu_model.load_state_dict(state['model'],strict=True)
    validation=[r for r in rows(args.evaluation) if r['history']][:128]
    cpu_ids,cpu_mask=history_tensor(validation,'cpu');gpu_ids,gpu_mask=cpu_ids.cuda(),cpu_mask.cuda()
    q=F.normalize(torch.tensor(np.load(args.data/'query_features.npy')[:128]),dim=-1)
    with torch.inference_mode():
        unique,inverse=torch.unique(gpu_ids,return_inverse=True)
        h=model.encode_items(F.normalize(torch.tensor(source[unique.cpu().numpy()],device='cuda'),dim=-1))
        expected=model.encode_user(h[inverse],gpu_mask).cpu()
        actual=cpu_model.encode_user(torch.tensor(vectors[cpu_ids.numpy()]),cpu_mask)
        user_error=float((expected-actual).abs().max())
        query_error=float((model.encode_query(q.cuda()).cpu()-cpu_model.encode_query(q)).abs().max())
        score_error=float(((expected-actual)@torch.tensor(vectors[:2048]).T).abs().max())
        query_norm_error=float((cpu_model.encode_query(q).norm(dim=-1)-1).abs().max())
    assert max(user_error,query_error,score_error)<3e-6
    for s in range(0,len(vectors),4096):
        b=vectors[s:s+4096];assert np.isfinite(b).all() and np.allclose(np.linalg.norm(b,axis=1),1,atol=1e-4)
    serving_config={**state['config'],'id_dim':0,'hidden':256,'history_half_life_days':0.}
    torch.save({'model':state['model'],'config':serving_config,'step':state.get('step',state.get('steps')),
                'source_checkpoint_sha256':sha(args.checkpoint)},args.output/'model.pt')
    shutil.copy2(Path(__file__).with_name('three_tower_residual.py'),args.output/'model_definition.py')
    manifest={'status':'OFFLINE_CANDIDATE_VERIFIED_NOT_DEPLOYED','model_type':'product_residual_no_id','dimension':source.shape[1],'candidate_count':len(source),
        'source_checkpoint':str(args.checkpoint),'source_config':state['config'],'source_step':state.get('step',state.get('steps')),
        'forward':{'item':'normalize(normalized BGE + item_adapter(normalized BGE))','user':'normalize(mean(exported item vectors for last <=50 known history items) + user_adapter(mean))','query':'normalize(normalized BGE query + query_adapter(normalized BGE query))'},
        'serving_contract':['历史中的商品向量已过item塔，不得二次变换','未知历史商品跳过，空历史走既有fallback','商品/查询需相同BGE版本、max_seq_length256与归一化策略','1024维，独立版本索引，发布前仍需服务回放和收益验收'],
        'checks':{'users':len(validation),'queries':len(q),'gpu_vs_cpu_user_error':user_error,'gpu_vs_cpu_query_error':query_error,'score_error':score_error,'query_norm_error':query_norm_error},
        'query_task_trained':bool(torch.count_nonzero(state['model']['query.layers.2.weight'])),
        'output_hashes':{name:sha(args.output/name) for name in ['item_vectors.npy','item_ids.jsonl','model.pt','model_definition.py']},
        'created_unix':time.time(),'online_modified':False}
    (args.output/'manifest.json').write_text(json.dumps(manifest,ensure_ascii=False,indent=2),encoding='utf-8');print(json.dumps(manifest,ensure_ascii=False),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ['data','evaluation','checkpoint','output']:p.add_argument('--'+name,type=Path,required=True)
    export(p.parse_args())
