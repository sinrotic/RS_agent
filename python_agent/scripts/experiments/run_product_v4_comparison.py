"""推荐先行，语义全量就绪且质量检查通过后执行同预算三塔对照。"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time

ROOT=Path('/mnt/data/luo/remote_runs/three_tower_dataset_v4')
DATA=ROOT/'data'
SCRIPT=ROOT/'scripts/three_tower_residual.py'
ENV={**os.environ,'CUDA_VISIBLE_DEVICES':'2'}
SEEDS=[42,43,44]


def save(path,value):
    path.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def status(state,**values):
    save(ROOT/'comparison_status.json',{'state':state,'updated_unix':time.time(),**values})


def read(path):
    return [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines()]


def completed(name):
    path=ROOT/name/'results.json'
    return path.exists() and 'seconds' in json.loads(path.read_text())


def launch(name,mode,seed):
    if completed(name):return
    if (ROOT/name).exists():raise RuntimeError('incomplete run needs inspection: '+name)
    status('TRAINING',run=name,mode=mode,seed=seed)
    cmd=[sys.executable,str(SCRIPT),'--data',str(DATA),'--output',str(ROOT/name),
         '--mode',mode,'--seed',str(seed),'--steps','400' if mode=='semantic' else '6000',
         '--eval-every','100' if mode=='semantic' else '500','--lr','2e-5',
         '--query-lr','2e-6','--semantic-weight','0.1','--semantic-every','15']
    if mode=='joint':cmd+=['--semantic-eval']
    with (ROOT/(name+'.log')).open('w') as log:
        subprocess.run(cmd,env=ENV,stdout=log,stderr=subprocess.STDOUT,check=True)


def audit_semantics():
    ready=json.loads((DATA/'dataset_readiness.json').read_text())
    assert ready['status']=='READY_FOR_BOUNDED_EXPERIMENT_NOT_PRODUCTION'
    inputs={r['item_id']:r for r in read(ROOT/'generation_inputs.jsonl')}
    records=read(ROOT/'generation_records.jsonl')
    assert len(records)==1000 and len({r['item_id'] for r in records})==1000
    assert sum(r['status']=='complete' for r in records)>=900
    sem=read(DATA/'semantic_clean.jsonl');test=read(DATA/'semantic_test.jsonl')
    from build_semantic_dataset import local_checks, SLOTS, normalized
    groups={s:{r['group'] for r in sem+test if r['split']==s} for s in ['train','valid','test']}
    texts={s:{normalized(r['query']) for r in sem+test if r['split']==s} for s in groups}
    for a,b in [('train','valid'),('train','test'),('valid','test')]:
        assert not groups[a]&groups[b] and not texts[a]&texts[b]
    for r in sem+test:
        assert not local_checks(r,inputs[r['item_id']],next(s for s in SLOTS if s[0]==r['slot']))
        assert r['reasons']==[] and r['review_status']=='same_model_machine_review_not_human'
    assert len(sem+test)>=2400
    for name in ['semantic_clean.jsonl','semantic_test.jsonl']:
        assert hashlib.sha256((DATA/name).read_bytes()).hexdigest()==ready['hashes'][name]
    report={'status':'PASS_FOR_EXPLORATORY_TRAINING','products_attempted':len(records),
        'accepted_queries':len(sem+test),'train_queries':sum(r['split']=='train' for r in sem),
        'valid_queries':sum(r['split']=='valid' for r in sem),'test_queries':len(test),
        'checks':['generation complete','>=90% products complete','>=60% queries retained',
                  'cross-split group/query disjoint','all retained citations rechecked','input hashes match'],
        'human_gold':False,'limitations':['same-model review may share generator errors',
            'sampled agent inspection is not a complete human audit','source-item recovery is not exhaustive relevance']}
    save(ROOT/'semantic_quality_audit.json',report)


def semantic_probe(run,step):
    if os.environ.get('CUDA_VISIBLE_DEVICES')!='2':
        raise ValueError('semantic probe must reserve physical GPU 2')
    import numpy as np
    import torch
    import torch.nn.functional as F
    from three_tower_residual import ResidualTowers, metrics
    torch.set_num_threads(4);torch.cuda.set_per_process_memory_fraction(.6)
    f=F.normalize(torch.tensor(np.load(DATA/'item_features.npy'),device='cuda'),dim=-1)
    q=F.normalize(torch.tensor(np.load(DATA/'query_features.npy'),device='cuda'),dim=-1)
    sem=read(DATA/'semantic_clean.jsonl');indexes=[i for i,r in enumerate(sem) if r['split']=='valid']
    checkpoint=torch.load(ROOT/run/f'step_{step}.pt',map_location='cpu',weights_only=True)
    model=ResidualTowers(1024,256,len(f),0).cuda().eval();model.load_state_dict(checkpoint['model'])
    with torch.inference_mode():
        item_v=torch.cat([model.encode_items(f[i:i+1024]) for i in range(0,len(f),1024)])
        result={}
        for key,use_model in [('bge',False),('checkpoint',True)]:
            ranks=[]
            for i in range(0,len(indexes),64):
                ids=indexes[i:i+64];v=model.encode_query(q[ids]) if use_model else q[ids]
                scores=v@(item_v if use_model else f).T
                for j,k in enumerate(ids):
                    target=sem[k]['item_index'];ranks.append(int((scores[j]>=scores[j,target]).sum()))
            result[key]={'metrics':metrics(ranks),'ranks':ranks}
    save(ROOT/run/f'semantic_probe_step_{step}.json',result)
    del model,f,q,item_v,scores
    torch.cuda.empty_cache()
    return result


def summarize():
    import numpy as np
    result={'seeds':SEEDS,'comparison_step':6000,'selection':'fixed final step, not best checkpoint',
        'rec_steps':6000,'joint_semantic_updates':400,'semantic_only_steps':400,
        'evaluation_scope':'same 1000-user development cohort and synthetic semantic development set; not independent final test'}
    outputs={}
    for mode in ['rec','semantic','joint']:
        outputs[mode]=[json.loads((ROOT/f'{mode}_seed{s}'/'results.json').read_text()) for s in SEEDS]
        result[mode]=[{'seed':s,'metrics':r['checkpoints'][-1]['evaluation']} for s,r in zip(SEEDS,outputs[mode])]
    delta=[]
    for rec,joint in zip(outputs['rec'],outputs['joint']):
        a=np.array(rec['checkpoints'][-1]['evaluation']['rec_ranks'])
        b=np.array(joint['checkpoints'][-1]['evaluation']['rec_ranks'])
        delta.append(((b>0)&(b<=100)).astype(float)-((a>0)&(a<=100)).astype(float))
    delta=np.mean(delta,axis=0);rng=np.random.default_rng(20261011)
    bootstrap=np.array([rng.choice(delta,len(delta),replace=True).mean() for _ in range(2000)])
    result['joint_minus_rec_hit100']={'delta':float(delta.mean()),'paired_user_95pct':np.quantile(bootstrap,[.025,.975]).tolist(),
        'note':'three fixed seeds averaged per user; not seed-population uncertainty or independent test'}
    save(ROOT/'comparison_results.json',result)


def main():
    deadline=time.monotonic()+3*3600
    status('WAITING_FIRST_REC_RUN')
    while not completed('rec_seed42'):
        if 'Traceback (most recent call last)' in (ROOT/'rec_seed42.log').read_text():raise RuntimeError('first recommendation run failed')
        if time.monotonic()>deadline:raise TimeoutError('first rec run timeout')
        time.sleep(10)
    for seed in [43,44]:launch(f'rec_seed{seed}','rec',seed)
    recs=[json.loads((ROOT/f'rec_seed{s}'/'results.json').read_text()) for s in SEEDS]
    gain=sum(r['checkpoints'][-1]['evaluation']['rec']['hit@100']-r['baseline']['rec']['hit@100'] for r in recs)/3
    save(ROOT/'recommendation_gate.json',{'fixed_step':6000,'seeds':SEEDS,'mean_hit100_gain':gain,
        'passed':gain>0,'scope':'development improvement only; not production promotion'})
    if gain<=0:
        status('NEEDS_REC_ADJUSTMENT',mean_hit100_gain=gain);return
    status('WAITING_SEMANTIC_DATA',rec_mean_hit100_gain=gain)
    while not (DATA/'dataset_readiness.json').exists():
        pipeline=json.loads((ROOT/'pipeline_status.json').read_text())
        if pipeline['state']=='FAILED':raise RuntimeError('semantic dataset pipeline failed')
        if time.monotonic()>deadline:raise TimeoutError('semantic dataset timeout')
        time.sleep(15)
    audit_semantics()
    status('PROBING_REC_SEMANTIC_RETENTION')
    for seed in SEEDS:semantic_probe(f'rec_seed{seed}',6000)
    for seed in SEEDS:
        launch(f'semantic_seed{seed}','semantic',seed)
        launch(f'joint_seed{seed}','joint',seed)
    summarize();status('COMPLETE',results=str(ROOT/'comparison_results.json'))


if __name__=='__main__':
    os.environ['CUDA_VISIBLE_DEVICES']='2'
    try:main()
    except Exception as exc:
        status('FAILED',error=type(exc).__name__+': '+str(exc));raise
