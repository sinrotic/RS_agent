"""选型冻结后复评既有官方test用户和未用于本轮调参的合成test查询；禁止据此重新选型。"""
import hashlib,json,os,time
from pathlib import Path
import numpy as np
import torch
import torch.nn.functional as F
from three_tower_residual import ResidualTowers,rows,paired_interval
from evaluate_product_v7_catalog import build_requests,exact_ranks,summarize,save
ROOT=Path('/mnt/data/luo/remote_runs/product_v8_training')
V7=Path('/mnt/data/luo/remote_runs/product_v7_expansion')
V4=Path('/mnt/data/luo/remote_runs/three_tower_dataset_v4')
SOURCE=Path('/home/luo/RS_agent_remote/data/processed/amazon_2023_recall_recent_2y_1m_3m')

def main():
    assert os.environ.get('CUDA_VISIBLE_DEVICES')=='2'
    selection=json.loads((ROOT/'selection.json').read_text());assert selection['state']=='FROZEN'
    torch.set_num_threads(2);torch.set_num_interop_threads(1);torch.cuda.set_per_process_memory_fraction(.20)
    torch.backends.cuda.matmul.allow_tf32=False
    assert not (ROOT/'final_validation.json').exists(),'final gate is not a tuning loop'
    policy={'rec_test_gate':'扩库候选推荐Hit100不低于现网实际旧库，MRR不低于95%；同扩库条件推荐Hit100和合成语义Hit10不低于现网权重',
        'selection_frozen':selection['checkpoint'],'selection_timestamp':selection['timestamp'],
        'limitations':'1632名官方test用户在历史v4报告已使用，不是全新独立test；344条合成test查询不是人工相关性判断；仅作上线回归门槛，不据此调参'}
    save(ROOT/'final_validation_policy.json',policy)
    ids=[]
    with (V7/'data/items.jsonl').open() as f:
        for line in f:ids.append(json.loads(line)['item_id'])
    mapping={v:i for i,v in enumerate(ids)}
    old_count=203887
    original_ids=ids[:old_count]+json.loads((V4/'final_test/extra_history_ids.json').read_text())
    original=rows(V4/'final_test/confirmation_rows.jsonl');users={r['user_hash'] for r in original};targets={}
    window=json.loads((SOURCE/'manifest.json').read_text())['window_policy']['splits']['test']
    with (SOURCE/'canonical_interactions.test.jsonl').open() as f:
        for line in f:
            r=json.loads(line)
            if r['label_binary']!=1:continue
            uid=hashlib.sha256(r['user_id'].encode()).hexdigest()
            if uid not in users:continue
            assert window['start_ms']<=r['timestamp']<window['end_ms']
            v=(r['timestamp'],r['parent_asin'])
            if uid not in targets or v<targets[uid]:targets[uid]=v
    cohort=[]
    for r in original:
        ts,iid=targets[r['user_hash']];assert ts==r['target_ts']
        cohort.append({'user_hash':r['user_hash'],'old_target':r['target'],'target':mapping.get(iid,-1),
            'history_old':[i for i in r['history'] if i<old_count],
            'history_full':[mapping[original_ids[i]] for i in r['history']]})
    sem=rows(V4/'data/semantic_test.jsonl');assert len(sem)==344 and all(r['split']=='test' for r in sem)
    development=rows(V4/'data/semantic_clean.jsonl')
    assert not {r['group'] for r in sem}&{r['group'] for r in development}
    assert not {r['query'].strip().lower() for r in sem}&{r['query'].strip().lower() for r in development}
    from sentence_transformers import SentenceTransformer
    encoder=SentenceTransformer('/home/luo/RS_agent_java/data/models/BAAI/bge-m3',device='cuda',local_files_only=True)
    encoder.half();encoder.max_seq_length=256
    q=encoder.encode([r['query'] for r in sem],batch_size=32,normalize_embeddings=True,convert_to_numpy=True).astype('float32')
    del encoder;torch.cuda.empty_cache();q=F.normalize(torch.tensor(q),dim=-1).numpy()
    np.save(ROOT/'semantic_test_query_features.npy',q)
    # 复用评估器的valid选择字段，不改变test归属或训练输入。
    sem=[{**r,'split':'valid'} for r in sem]
    excluded={r['index'] for r in json.loads((V7/'data/text_audit.json').read_text())['ineligible']}
    output={'policy':policy,'models':{}}
    for name,checkpoint,path,expanded in [
        ('online_actual',V4/'export_joint_full_seed42/model.pt',V4/'export_joint_full_seed42/item_vectors.npy',False),
        ('online_expanded',V4/'export_joint_full_seed42/model.pt',V7/'online_v4_item_vectors.npy',True),
        ('candidate',Path(selection['checkpoint']),V7/'candidate_v6_item_vectors.npy',True)]:
        vectors=np.load(path,mmap_mode='r');model=ResidualTowers(1024,256,len(vectors),0).cuda().eval()
        model.load_state_dict(torch.load(checkpoint,map_location='cpu',weights_only=True)['model'])
        with torch.inference_mode():
            requests,t,h,positions,results=build_requests(model,vectors,{'test':cohort},sem,q,expanded,excluded)
            ranks,error=exact_ranks(requests,vectors,t,h,excluded=excluded)
            for (k,i),rank in zip(positions,ranks):results[k]['ranks'][i]=rank
        output['models'][name]=summarize(results);del vectors,model,requests;torch.cuda.empty_cache()
        print(name,{k:r['metrics'] for k,r in output['models'][name].items()},flush=True)
    a=output['models']['online_actual']['test/old_catalog'];b=output['models']['online_expanded']['test/expanded_full_history'];c=output['models']['candidate']['test/expanded_full_history']
    output['gate_checks']={'rec_vs_actual':c['metrics']['hit@100']>=a['metrics']['hit@100'],
        'mrr_vs_actual':c['metrics']['mrr']>=.95*a['metrics']['mrr'],
        'rec_vs_same_catalog':c['metrics']['hit@100']>=b['metrics']['hit@100'],
        'semantic_vs_same_catalog':output['models']['candidate']['semantic']['metrics']['hit@10']>=output['models']['online_expanded']['semantic']['metrics']['hit@10']}
    output['paired_vs_actual']=paired_interval(a['ranks'],c['ranks'])
    output['state']='PASS' if all(output['gate_checks'].values()) else 'FAIL'
    save(ROOT/'final_validation.json',output)

if __name__=='__main__':main()
