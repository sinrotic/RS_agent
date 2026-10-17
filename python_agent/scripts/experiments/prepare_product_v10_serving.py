"""隔离验收复用v9已验证契约，明确增加位置衰减前向与新的封存门槛。"""
import json,os,subprocess,time
from pathlib import Path
ROOT=Path('/mnt/data/luo/remote_runs/product_v10_training');V9=ROOT.parent/'product_v9_training';V7=ROOT.parent/'product_v7_expansion'
PYTHON='/home/luo/RS_agent_remote/.venv/bin/python'
def replace_once(text,old,new):
    assert text.count(old)==1,(old,text.count(old));return text.replace(old,new,1)
def derive():
    scripts=ROOT/'scripts'
    for name in ['serve_product_v9.py','replay_product_v9.py','check_product_v9_ann.py','load_product_v9.py','gate_product_v9.py','validate_product_v9.py']:
        text=(V9/'scripts'/name).read_text().replace('product_v9_training','product_v10_training').replace('product_v9','product_v10').replace('product-v9','product-v10').replace('tower_v9','tower_v10').replace('18124','18126').replace('18234','18235').replace('v9-fault','v10-fault').replace('v9-fallback','v10-fallback')
        if name=='serve_product_v9.py':
            text=replace_once(text,"str(V7/'scripts/verify_product_v6_runtime.py')","str(ROOT/'scripts/verify_product_v10_runtime.py')")
            text=replace_once(text,"for name in ['item_vectors.npy','item_ids.jsonl','model_definition.py']:","for name in ['item_vectors.npy','item_ids.jsonl']:")
            text=replace_once(text,"    manifest={'status':'EXPORTED_AWAITING_SERVING_VERIFICATION'", "    base_source=(ROOT/'scripts/three_tower_residual.py').read_text()\n    definitions=base_source[base_source.index('class Adapter'):base_source.index('def history_tensor')]\n    sequence=(ROOT/'scripts/product_v10_model.py').read_text()\n    sequence=sequence[sequence.index('class SequenceResidualTowers'):sequence.index('def sample_hard_ids')]\n    factory=\"\\ndef create_model(config,item_count):\\n    return SequenceResidualTowers(1024,config['hidden'],item_count,config['id_dim'],pooling=config.get('pooling','mean'))\\n\"\n    (output/'model_definition.py').write_text('import torch\\nfrom torch import nn\\nimport torch.nn.functional as F\\n\\n'+definitions+sequence+factory)\n    manifest={'pooling':state['config'].get('pooling','mean'),'input_history_order':'recent_first_http / chronological_training','status':'EXPORTED_AWAITING_SERVING_VERIFICATION'")
        if name=='validate_product_v9.py':
            text=replace_once(text,'from three_tower_residual import ResidualTowers,rows,paired_interval','from three_tower_residual import rows,paired_interval\nfrom product_v10_model import SequenceResidualTowers as ResidualTowers')
            text=replace_once(text,'model=ResidualTowers(1024,256,len(vectors),0).cuda().eval()',"model=ResidualTowers(1024,256,len(vectors),0,pooling=torch.load(checkpoint,map_location='cpu',weights_only=True)['config'].get('pooling','mean')).cuda().eval()")
            text=text.replace('本轮另有1500名完整封存的新用户作为未见用户验收','本轮另有2000名新验证期用户的未来目标封存验收；其训练期历史可用于训练，非未见用户')
            text=replace_once(text,"'mrr_vs_actual':c['metrics']['mrr']>=.95*a['metrics']['mrr'],","'mrr_vs_actual':c['metrics']['mrr']>=.95*a['metrics']['mrr'],\n        'head_hit10_vs_actual':c['metrics']['hit@10']>=a['metrics']['hit@10'],")
        if name=='gate_product_v9.py':
            text=text.replace("['sealed/expanded_full_history']","['sealed_future']")
            text=replace_once(text,"    sealed=json.loads((ROOT/'results.json').read_text())['sealed']", "    import hashlib\n    metadata=json.loads((ROOT/'data/manifest.json').read_text())\n    ready=ROOT/'data/sealed_snapshot_ready.json'\n    selection=json.loads((ROOT/'selection.json').read_text())\n    checks['sealed_snapshot_integrity']=ready.exists() and ready.stat().st_mtime<selection['timestamp'] and metadata.get('sealed_min_history')==2 and hashlib.sha256((ROOT/'data/sealed_future.jsonl').read_bytes()).hexdigest()==metadata['sealed_sha256']\n    sealed=json.loads((ROOT/'results.json').read_text())['sealed']")
            text=replace_once(text,"checks['sealed_hit100']=current['hit@100']>=reference['hit@100']", "actual=sealed['online_actual']['sealed_future']['metrics']\n    checks['sealed_hit100']=current['hit@100']>=max(reference['hit@100'],actual['hit@100'])\n    checks['sealed_hit10']=current['hit@10']>=actual['hit@10']")
            text=replace_once(text,"checks['sealed_mrr']=current['mrr']>=reference['mrr'] and current['mrr']>=.95*initial['mrr']", "checks['sealed_mrr']=current['mrr']>=max(reference['mrr'],actual['mrr'],.95*initial['mrr'])")
        (scripts/name.replace('v9','v10')).write_text(text)
    text=(V9/'scripts/product_residual_runtime.py').read_text()
    text=replace_once(text,"config=checkpoint['config']", "config=checkpoint['config']\n        self.pooling=config.get('pooling','mean')\n        if self.pooling not in ['mean','decay08','blend_recent','cohesion']:raise ValueError('unsupported pooling')")
    text=replace_once(text,"mean=np.asarray(self.vectors[matched],dtype=np.float32).mean(axis=0)","h=np.asarray(self.vectors[matched],dtype=np.float32)\n            if self.pooling=='decay08':\n                weights=np.power(np.float32(.8),np.arange(len(matched),dtype=np.float32))\n                mean=(h*weights[:,None]).sum(0)/weights.sum()\n            elif self.pooling=='blend_recent':mean=.75*h.mean(0)+.25*h[:3].mean(0)\n            elif self.pooling=='cohesion' and len(h)>2:\n                support=((h@h.T).sum(1)-1)/(len(h)-1)\n                logits=support/np.float32(.15);weights=np.exp(logits-logits.max());weights=weights/weights.sum()\n                mean=(h*weights[:,None]).sum(0)\n            else:mean=h.mean(axis=0)")
    text=text.replace('product_residual_uniform_history_v9',"product_residual_sequence_v10").replace('均匀聚合，没有旧queryv2的时间衰减和均值预归一化。','最近优先；decay08按位置衰减，与训练的时间升序历史严格对应。')
    (scripts/'product_residual_runtime.py').write_text(text)
    (scripts/'two_tower_runtime.py').write_bytes((V9/'scripts/two_tower_runtime.py').read_bytes())
    text=(V7/'scripts/verify_product_v6_runtime.py').read_text()
    text=replace_once(text,'from three_tower_residual import ResidualTowers,history_tensor,rows','from three_tower_residual import history_tensor,rows\nfrom product_v10_model import SequenceResidualTowers as ResidualTowers')
    text=replace_once(text,'model=ResidualTowers(1024,256,len(runtime.index),0).eval();',"model=ResidualTowers(1024,256,len(runtime.index),0,pooling=checkpoint['config'].get('pooling','mean')).eval();")
    (scripts/'verify_product_v10_runtime.py').write_text(text)
    # 同一固定商品塔，仅建立新别名；现网旧集合与jar均不修改。
    from pymilvus import connections,utility
    connections.connect(host='127.0.0.1',port='19530')
    alias='rs_agent_product_three_tower_v10_20261011';physical='rs_agent_product_three_tower_v8_20261011'
    if alias not in utility.list_aliases(physical):utility.create_alias(physical,alias)
    index=json.loads((V9/'index_manifest.json').read_text());index['collection']=alias
    (ROOT/'index_manifest.json').write_text(json.dumps(index,indent=2))
    if not (ROOT/'rs-service-recommend.jar').exists():os.link(V9/'rs-service-recommend.jar',ROOT/'rs-service-recommend.jar')
    (ROOT/'deployment_build.json').write_bytes((V9/'deployment_build.json').read_bytes())
    for p in scripts.glob('*v10*.py'):compile(p.read_text(),str(p),'exec')
    compile((scripts/'product_residual_runtime.py').read_text(),'runtime','exec')

def run(script,*args,gpu=False):
    (ROOT/'serving_preparation.json').write_text(json.dumps({'state':'RUNNING','stage':script,'args':args,'time':time.time()}))
    subprocess.run([PYTHON,str(ROOT/'scripts'/script),*args],check=True,env={**os.environ,'CUDA_VISIBLE_DEVICES':'2' if gpu else '','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1'})
def main():
    derive();start=time.time()
    (ROOT/'serving_preparation.json').write_text(json.dumps({'state':'WAITING_TRAINING','online_modified':False}))
    while True:
        if (ROOT/'failure.json').exists():raise RuntimeError('training failed')
        if (ROOT/'results.json').exists() and json.loads((ROOT/'results.json').read_text())['state']=='COMPLETE':break
        if time.time()-start>7200:raise TimeoutError('training wait timeout')
        time.sleep(10)
    run('validate_product_v10.py',gpu=True)
    run('serve_product_v10.py','package')
    run('serve_product_v10.py','candidate')
    run('check_product_v10_ann.py',gpu=True)
    run('replay_product_v10.py','--port','18213','--output','baseline_replay.json')
    run('replay_product_v10.py','--port','18235','--output','candidate_replay.json')
    run('gate_product_v10.py')
    (ROOT/'serving_preparation.json').write_text(json.dumps({'state':'ISOLATED_CHECKS_COMPLETE','time':time.time()}))
if __name__=='__main__':
    try:main()
    except Exception as e:(ROOT/'serving_preparation.json').write_text(json.dumps({'state':'FAILED','error':repr(e)}));raise
