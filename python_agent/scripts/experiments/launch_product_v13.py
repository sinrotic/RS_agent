"""GPU2训练排队；只等待本轮v12，明确失败，不静默挂起。"""
import json,os,subprocess,time
from pathlib import Path
ROOT=Path('/mnt/data/luo/remote_runs/product_v13_training')

def main():
    began=time.time();prior=ROOT.parent/'product_v12_training'
    while True:
        if (prior/'failure.json').exists():raise RuntimeError('v12失败，请先处理')
        if (prior/'results.json').exists() and json.loads((prior/'results.json').read_text())['state']=='COMPLETE':break
        if time.time()-began>7200:raise TimeoutError('等待v12超过2小时')
        (ROOT/'queue.json').write_text(json.dumps({'state':'WAITING_GPU2','dependency':'v12训练完成','timestamp':time.time()}))
        time.sleep(5)
    assert (ROOT/'data/manifest.json').exists()
    subprocess.run(['/home/luo/RS_agent_remote/.venv/bin/python',str(ROOT/'scripts/train_product_v13.py')],check=True,
                   env={**os.environ,'CUDA_VISIBLE_DEVICES':'2','OMP_NUM_THREADS':'1','OPENBLAS_NUM_THREADS':'1'})
    (ROOT/'queue.json').write_text(json.dumps({'state':'COMPLETE','timestamp':time.time()}))

if __name__=='__main__':main()
