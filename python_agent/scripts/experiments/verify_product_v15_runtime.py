"""直接调用现有CPU运行时类验证候选，不启动端口、不修改在线进程。"""
import argparse,hashlib,json,sys,time
from pathlib import Path
import numpy as np
import torch
import torch.nn.functional as F
from three_tower_residual import history_tensor,rows
from product_v10_model import SequenceResidualTowers as ResidualTowers


def main(args):
    torch.set_num_threads(2)
    sys.path.insert(0,str(args.runtime_directory))
    from product_residual_runtime import Runtime
    runtime=Runtime(args.export)
    checkpoint=torch.load(args.export/'model.pt',map_location='cpu',weights_only=True)
    model=ResidualTowers(1024,256,len(runtime.index),0,pooling=checkpoint['config'].get('pooling','mean')).eval();model.load_state_dict(checkpoint['model'],strict=True)
    all_ids=[r['item_id'] for r in rows(args.export/'item_ids.jsonl')]
    valid=[r for r in rows(args.evaluation) if r['history']][:128]
    ids,mask=history_tensor(valid,'cpu')
    with torch.inference_mode():expected=model.encode_user(torch.tensor(runtime.vectors[ids.numpy()]),mask).numpy()
    timings=[];actual=[]
    for row in valid:
        history=[all_ids[i] for i in reversed(row['history'])]
        started=time.perf_counter();result=runtime.infer(history);timings.append((time.perf_counter()-started)*1000)
        assert result['matched_history_count']==len(row['history'])
        actual.append(result['embedding'])
    user_error=float(np.max(np.abs(expected-np.array(actual))))
    query=F.normalize(torch.tensor(np.load(args.data/'query_features.npy')[:128]),dim=-1)
    with torch.inference_mode():expected_query=model.encode_query(query).numpy()
    actual_query=np.array([runtime.project_query(q.numpy()) for q in query])
    query_error=float(np.max(np.abs(expected_query-actual_query)))
    assert max(user_error,query_error)<3e-6
    assert runtime.infer(['__v6_unknown_item__'])['embedding']==[]
    rejected=False
    try:runtime.project_query(np.zeros(1024))
    except ValueError:rejected=True
    assert rejected
    result={'status':'PASS_OFFLINE_RUNTIME_REPLAY','users':len(valid),'queries':len(query),'user_max_error':user_error,'query_max_error':query_error,
        'local_cpu_infer_median_ms':float(np.median(timings)),'local_cpu_infer_p95_ms':float(np.quantile(timings,.95)),
        'unknown_history_fallback':True,'zero_query_rejected':True,'runtime_source_sha256':hashlib.sha256((args.runtime_directory/'product_residual_runtime.py').read_bytes()).hexdigest(),
        'limitations':'仅直接调用CPU运行时；未启动HTTP服务、未写Milvus、不是线上端到端尾延迟或业务收益验收','online_modified':False}
    (args.export/'runtime_replay.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps(result,ensure_ascii=False),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser()
    for name in ['export','data','evaluation','runtime-directory']:p.add_argument('--'+name,type=Path,required=True)
    main(p.parse_args())
