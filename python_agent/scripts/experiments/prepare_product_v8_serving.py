"""等待训练完成后执行冻结验收和隔离服务检查；不在后台直接切换现网。"""
import json,os,subprocess,time
from pathlib import Path
ROOT=Path('/mnt/data/luo/remote_runs/product_v8_training')
PYTHON='/home/luo/RS_agent_remote/.venv/bin/python'

def run(script,*args,gpu=False):
    p=ROOT/'serving_preparation.json';p.write_text(json.dumps({'state':'RUNNING','stage':script,'args':args,'time':time.time()}))
    subprocess.run([PYTHON,str(ROOT/'scripts'/script),*args],check=True,env={**os.environ,'CUDA_VISIBLE_DEVICES':'2' if gpu else '','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1'})

def main():
    start=time.time()
    while True:
        if (ROOT/'failure.json').exists():raise RuntimeError('training failed')
        if (ROOT/'results.json').exists() and json.loads((ROOT/'results.json').read_text())['state']=='COMPLETE':break
        if time.time()-start>1800:raise TimeoutError('training wait timed out')
        time.sleep(10)
    run('validate_product_v8.py',gpu=True)
    run('serve_product_v8.py','package')
    while not (ROOT/'index_manifest.json').exists():
        if time.time()-start>2400:raise TimeoutError('index wait timed out')
        time.sleep(10)
    run('serve_product_v8.py','candidate')
    run('check_product_v8_ann.py',gpu=True)
    run('replay_product_v8.py','--port','18233','--output','candidate_replay.json')
    (ROOT/'serving_preparation.json').write_text(json.dumps({'state':'ISOLATED_CHECKS_COMPLETE','time':time.time()}))

if __name__=='__main__':
    try:main()
    except Exception as e:
        (ROOT/'serving_preparation.json').write_text(json.dumps({'state':'FAILED','error':repr(e),'time':time.time()}));raise
