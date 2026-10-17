"""等待有界生成完成后自动组装及校验；不启动训练或修改线上服务。"""
import json
import os
from pathlib import Path
import subprocess
import sys
import time

root=Path('/mnt/data/luo/remote_runs/three_tower_dataset_v4')
data=root/'data'
status=root/'pipeline_status.json'


def save(state, **kwargs):
    status.write_text(json.dumps({'state':state,'updated_unix':time.time(),**kwargs},ensure_ascii=False,indent=2),encoding='utf-8')


def main():
    deadline=time.monotonic()+3*3600
    while True:
        records=root/'generation_records.jsonl'
        count=sum(1 for _ in records.open()) if records.exists() else 0
        if count==1000:
            break
        log=root/'generation_full.log'
        if log.exists() and 'Traceback (most recent call last)' in log.read_text():
            raise RuntimeError('generation stopped; inspect log; no training-ready dataset declared')
        if time.monotonic()>deadline:raise TimeoutError('generation did not finish within 3 hours')
        save('GENERATING',completed_products=count,expected_products=1000)
        time.sleep(15)
    save('ASSEMBLING',completed_products=count)
    subprocess.run([sys.executable,str(root/'scripts/build_semantic_dataset.py'),'assemble',
        '--root',str(root),'--data',str(data)],check=True)
    while not (data/'encoding_metrics.json').exists():
        if time.monotonic()>deadline:raise TimeoutError('item encoding incomplete')
        save('WAITING_ITEM_ENCODING');time.sleep(15)
    save('ENCODING_QUERIES_AND_VALIDATING')
    subprocess.run([sys.executable,str(root/'scripts/finalize_semantic_dataset.py'),
        '--data',str(data)],env={**os.environ,'CUDA_VISIBLE_DEVICES':'2'},check=True)
    save('READY',readiness=str(data/'dataset_readiness.json'),training_started=False)


if __name__=='__main__':
    try:main()
    except Exception as exc:
        save('FAILED',error=type(exc).__name__+': '+str(exc),training_started=False)
        raise
