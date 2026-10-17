"""复测隔离候选ef4096；清单兼容修复不改变模型选型或效果门槛。"""
import json,os,subprocess
from pathlib import Path
ROOT=Path('/mnt/data/luo/remote_runs/product_v11_training');PYTHON='/home/luo/RS_agent_remote/.venv/bin/python'
def run(name,*args,gpu=False):
    (ROOT/'serving_preparation.json').write_text(json.dumps({'state':'RUNNING_ENGINEERING_RECHECK','stage':name}))
    subprocess.run([PYTHON,str(ROOT/'scripts'/name),*args],check=True,env={**os.environ,'CUDA_VISIBLE_DEVICES':'2' if gpu else '','OPENBLAS_NUM_THREADS':'1','OMP_NUM_THREADS':'1'})
if __name__=='__main__':
    run('check_product_v11_ann.py','--ef','4096',gpu=True)
    run('replay_product_v11.py','--port','18213','--output','baseline_replay.json')
    run('replay_product_v11.py','--port','18236','--output','candidate_replay.json')
    run('gate_product_v11.py');run('finalize_product_v11.py')
    (ROOT/'serving_preparation.json').write_text(json.dumps({'state':'ISOLATED_CHECKS_COMPLETE'}))
