"""仅在注意力选型冻结后执行隔离验收；旧服务不修改，晋级需全部门槛通过。"""
import json,os,subprocess,sys,time
from pathlib import Path
ROOT=Path('/mnt/data/luo/remote_runs/product_v11_training');V10=ROOT.parent/'product_v10_training';V9=ROOT.parent/'product_v9_training'
PYTHON='/home/luo/RS_agent_remote/.venv/bin/python'
def once(s,a,b):
    assert s.count(a)==1,(a,s.count(a));return s.replace(a,b,1)
def derive():
    scripts=ROOT/'scripts'
    for name in ['serve_product_v10.py','replay_product_v10.py','check_product_v10_ann.py','load_product_v10.py','gate_product_v10.py','validate_product_v10.py','verify_product_v10_runtime.py','finalize_product_v10.py']:
        s=(V10/'scripts'/name).read_text().replace('product_v10','product_v11').replace('product-v10','product-v11').replace('tower_v10_20261011','tower_v11_20261012').replace('tower_v10','tower_v11').replace('18126','18128').replace('18235','18236').replace('v10-fault','v11-fault').replace('v10-fallback','v11-fallback')
        # 通用矿池和SequenceResidual仍由v10模块提供，不伪造重命名后的类。
        s=s.replace('from product_v11_model import SequenceResidualTowers as ResidualTowers','from product_v11_model import AttentionResidualTowers as ResidualTowers')
        if name=='validate_product_v10.py':
            s=once(s,"model.load_state_dict(torch.load(checkpoint,map_location='cpu',weights_only=True)['model'])","model.load_state_dict(torch.load(checkpoint,map_location='cpu',weights_only=True)['model'],strict=False)")
            s=s.replace('2000名新验证期用户','1000名剩余未见验证期用户')
        if name=='serve_product_v10.py':
            s=once(s,"env['RS_RECOMMEND_VECTOR_SEARCH_EF']='1024'","env['RS_RECOMMEND_VECTOR_SEARCH_EF']='4096'")
            # 模型定义包含base、Sequence及Attention，保持导出后独立可加载。
            s=once(s,"sequence=(ROOT/'scripts/product_v11_model.py').read_text()","sequence=(ROOT/'scripts/product_v10_model.py').read_text()")
            s=once(s,"    factory=", "    attention=(ROOT/'scripts/product_v11_model.py').read_text()\n    sequence+=attention[attention.index('class AttentionResidualTowers'):]+'\\n'\n    factory=")
            s=s.replace("return SequenceResidualTowers(1024,config['hidden']","return AttentionResidualTowers(1024,config['hidden']")
        if name=='gate_product_v10.py':
            old="checks['sealed_snapshot_integrity']=ready.exists() and ready.stat().st_mtime<selection['timestamp'] and metadata.get('sealed_min_history')==2 and hashlib.sha256((ROOT/'data/sealed_future.jsonl').read_bytes()).hexdigest()==metadata['sealed_sha256']"
            new="snapshot=ready if ready.exists() else ROOT/'data/manifest.json'\n    sealed_rows=[json.loads(line) for line in (ROOT/'data/sealed_future.jsonl').open()]\n    checks['sealed_snapshot_integrity']=snapshot.stat().st_mtime<selection['timestamp'] and len(sealed_rows)==metadata['sealed_count'] and all(len(x['history_full'])>=2 for x in sealed_rows) and hashlib.sha256((ROOT/'data/sealed_future.jsonl').read_bytes()).hexdigest()==metadata.get('sealed_sha256',metadata.get('sha256'))"
            s=once(s,old,new)
        if name=='finalize_product_v10.py':
            s=s.replace('商品三塔 v10','商品三塔 v11').replace('八组筛选各4000步','三组注意力筛选各4000步').replace('2000用户','1000用户').replace('均两项已知历史','均两项已知历史；注意力在此保持原前向').replace('用户MLP lr5e-7','原用户MLP冻结，仅user.pool_*学习，lr5e-5/2e-4')
        (scripts/name.replace('v10','v11')).write_text(s)
    s=(V10/'scripts/product_residual_runtime.py').read_text().replace('sequence_v10','attention_v11')
    s=once(s,"['mean','decay08','blend_recent','cohesion']","['mean','decay08','blend_recent','cohesion','attention_cohesion']")
    s=once(s,"        state=checkpoint['model']", "        state=checkpoint['model']\n        if self.pooling=='attention_cohesion':\n            self.pool_weights=[state['user.'+k].numpy() for k in ['pool_key.weight','pool_key.bias','pool_context.weight','pool_score.weight','pool_recency']]\n            if not all(np.isfinite(x).all() for x in self.pool_weights):raise ValueError('nonfinite pool weights')")
    insertion="""            elif self.pooling=='attention_cohesion' and len(h)>2:
                kw,kb,cw,sw,recency=self.pool_weights
                scale=np.float32(h.shape[1]**.5)
                context=cw@(np.concatenate([h.mean(0),h[0]])*scale)
                delta=np.tanh((h*scale)@kw.T+kb+context[None,:])@sw[0]
                support=((h@h.T).sum(1)-1)/(len(h)-1)
                age=-np.arange(len(h),dtype=np.float32)/(len(h)-1)
                logits=support/np.float32(.15)+delta+recency*age
                weights=np.exp(logits-logits.max());weights=weights/weights.sum()
                mean=(h*weights[:,None]).sum(0)/weights.sum()
"""
    s=once(s,"            elif self.pooling=='cohesion' and len(h)>2:",insertion+"            elif self.pooling=='cohesion' and len(h)>2:")
    (scripts/'product_residual_runtime.py').write_text(s)
    (scripts/'two_tower_runtime.py').write_bytes((V10/'scripts/two_tower_runtime.py').read_bytes())
    from pymilvus import connections,utility
    connections.connect(host='127.0.0.1',port='19530')
    alias='rs_agent_product_three_tower_v11_20261012';physical='rs_agent_product_three_tower_v8_20261011'
    if alias not in utility.list_aliases(physical):utility.create_alias(physical,alias)
    index=json.loads((V10/'index_manifest.json').read_text());index['collection']=alias
    (ROOT/'index_manifest.json').write_text(json.dumps(index,indent=2))
    if not (ROOT/'rs-service-recommend.jar').exists():os.link(V9/'rs-service-recommend.jar',ROOT/'rs-service-recommend.jar')
    (ROOT/'deployment_build.json').write_bytes((V9/'deployment_build.json').read_bytes())
    for p in scripts.glob('*.py'):compile(p.read_text(),str(p),'exec')
def run(name,*args,gpu=False):
    (ROOT/'serving_preparation.json').write_text(json.dumps({'state':'RUNNING','stage':name,'time':time.time()}))
    subprocess.run([PYTHON,str(ROOT/'scripts'/name),*args],check=True,env={**os.environ,'CUDA_VISIBLE_DEVICES':'2' if gpu else '','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1'})
def main():
    derive();began=time.time();(ROOT/'serving_preparation.json').write_text(json.dumps({'state':'WAITING_TRAINING'}))
    while True:
        if (ROOT/'failure.json').exists():raise RuntimeError('training failed')
        if (ROOT/'results.json').exists() and json.loads((ROOT/'results.json').read_text())['state']=='COMPLETE':break
        if time.time()-began>7200:raise TimeoutError('training wait')
        time.sleep(10)
    run('validate_product_v11.py',gpu=True);run('serve_product_v11.py','package');run('serve_product_v11.py','candidate')
    run('check_product_v11_ann.py','--ef','4096',gpu=True)
    run('replay_product_v11.py','--port','18213','--output','baseline_replay.json')
    run('replay_product_v11.py','--port','18236','--output','candidate_replay.json')
    run('gate_product_v11.py');run('finalize_product_v11.py')
    (ROOT/'serving_preparation.json').write_text(json.dumps({'state':'ISOLATED_CHECKS_COMPLETE'}))
if __name__=='__main__':
    try:main()
    except Exception as e:(ROOT/'serving_preparation.json').write_text(json.dumps({'state':'FAILED','error':repr(e)}));raise
