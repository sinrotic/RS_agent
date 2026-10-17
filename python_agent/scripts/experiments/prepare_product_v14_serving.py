"""冻结保护路线的版本化导出与隔离验收；主模型与兼容教师的版本明确分开。"""
import json,os,subprocess
from pathlib import Path
ROOT=Path('/mnt/data/luo/remote_runs/product_v14_training');BASE=ROOT.parent;V10=BASE/'product_v10_training';V11=BASE/'product_v11_training'
PYTHON='/home/luo/RS_agent_remote/.venv/bin/python'

def once(s,a,b):
    assert s.count(a)==1,(a,s.count(a));return s.replace(a,b,1)

def derive():
    sdir=ROOT/'scripts'
    for name in ['serve_product_v10.py','replay_product_v10.py','check_product_v10_ann.py','load_product_v10.py','verify_product_v10_runtime.py']:
        s=(V10/'scripts'/name).read_text().replace('product_v10','product_v14').replace('product-v10','product-v14').replace('tower_v10','tower_v14').replace('tower_v14_20261011','tower_v14_20261012').replace('18126','18132').replace('18235','18238')
        s=s.replace('from product_v14_model import SequenceResidualTowers','from product_v10_model import SequenceResidualTowers')
        s=s.replace("scripts/product_v14_model.py","scripts/product_v10_model.py").replace("'scripts/product_v14_model.py'","'scripts/product_v10_model.py'")
        # 原源使用ROOT/'scripts/...',上述替换保持该相对路径。
        if name=='serve_product_v10.py':
            s=once(s,"env['RS_RECOMMEND_VECTOR_SEARCH_EF']='1024'","env['RS_RECOMMEND_VECTOR_SEARCH_EF']='4096'\n    env.update(RS_RECOMMEND_TWO_TOWER_PROTECTED_HEAD_COUNT='10',\n        RS_RECOMMEND_TWO_TOWER_PROTECTED_BASE_URL='http://172.21.0.1:18120',\n        RS_RECOMMEND_TWO_TOWER_PROTECTED_MODEL_KEY='product_three_tower_v4_seed42_step6000',\n        RS_RECOMMEND_TWO_TOWER_PROTECTED_COLLECTION='rs_agent_product_three_tower_v4_20261011',\n        RS_RECOMMEND_TWO_TOWER_PROTECTED_DIMENSION='1024')")
            s=once(s,"manifest={'pooling':", "manifest={'protected_head_count':10,'protected_model_key':'product_three_tower_v4_seed42_step6000','protected_collection':'rs_agent_product_three_tower_v4_20261011','pooling':")
            s=once(s,"'candidate_count':763080,'primary_share':.65", "'candidate_count':763080,'protected_head_count':10,'protected_model_key':'product_three_tower_v4_seed42_step6000','primary_share':.65")
            # 发布前核对候选jar与已验收jar一致，避免模型门槛被换包绕过。
            s=once(s,"assert gates['state']=='PASS'", "assert gates['state']=='PASS'\n    assert gates['jar_sha256']==digest(ROOT/'rs-service-recommend.jar')")
        compile(s,str(sdir/name.replace('v10','v14')),'exec');(sdir/name.replace('v10','v14')).write_text(s)
    s=(V11/'scripts/gate_product_v11.py').read_text().replace('product_v11','product_v14').replace('product-v11','product-v14').replace('18128','18132').replace('18236','18238')
    s=once(s,'def main():',"def main():\n    live=json.loads(subprocess.check_output(['docker','inspect','rs-e2e-857e8b14-recommend-fast']))[0]\n    original=json.loads((ROOT/'deployment/original.private.json').read_text())\n    if live['Id']!=original['Id']:raise RuntimeError('线上容器已切换；禁止对活跃运行时执行隔离故障注入')")
    # v14封存门槛在评测前写入experiment_policy；原始新三塔不是本保护路线的部署基线。
    s=once(s,"max(reference['mrr'],actual['mrr'],.95*initial['mrr'])","max(reference['mrr'],actual['mrr'])")
    s=once(s,"'model_sha256':json.loads", "'jar_sha256':hashlib.sha256((ROOT/'rs-service-recommend.jar').read_bytes()).hexdigest(),'guarded_route_ann':json.loads((ROOT/'guard_ann_verification.json').read_text())['state'],'model_sha256':json.loads")
    s=once(s,"checks={k:bool(v)","checks['guard_ann']=json.loads((ROOT/'guard_ann_verification.json').read_text())['state']=='PASS'\n    checks={k:bool(v)")
    compile(s,'gate_product_v14.py','exec');(sdir/'gate_product_v14.py').write_text(s)
    for name in ['product_residual_runtime.py','two_tower_runtime.py']:(sdir/name).write_bytes((V10/'scripts'/name).read_bytes())
    from pymilvus import connections,utility
    connections.connect(host='127.0.0.1',port='19530')
    physical='rs_agent_product_three_tower_v8_20261011';alias='rs_agent_product_three_tower_v14_20261012'
    if alias not in utility.list_aliases(physical):utility.create_alias(physical,alias)
    index=json.loads((V10/'index_manifest.json').read_text());index['collection']=alias
    (ROOT/'index_manifest.json').write_text(json.dumps(index,indent=2))

def run(name,*args,gpu=False):
    (ROOT/'serving_preparation.json').write_text(json.dumps({'state':'RUNNING','stage':name,'online_modified':False}))
    subprocess.run([PYTHON,str(ROOT/'scripts'/name),*args],check=True,
                   env={**os.environ,'CUDA_VISIBLE_DEVICES':'2' if gpu else '','OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1'})

def main():
    assert json.loads((ROOT/'results.json').read_text())['sealed_state']=='PASS'
    derive()
    if not (ROOT/'final_validation.json').exists():run('validate_product_v14.py',gpu=True)
    assert json.loads((ROOT/'final_validation.json').read_text())['state']=='PASS'
    run('serve_product_v14.py','package');run('serve_product_v14.py','candidate')
    run('check_product_v14_ann.py','--ef','4096',gpu=True)
    run('check_guard_product_v14.py',gpu=True)
    run('replay_product_v14.py','--port','18213','--output','baseline_replay.json')
    run('replay_product_v14.py','--port','18238','--output','candidate_replay.json')
    run('gate_product_v14.py')
    (ROOT/'serving_preparation.json').write_text(json.dumps({'state':'ISOLATED_CHECKS_COMPLETE','online_modified':False}))

if __name__=='__main__':
    try:main()
    except Exception as e:(ROOT/'serving_preparation.json').write_text(json.dumps({'state':'FAILED','error':repr(e)}));raise
