"""保存最新整千步断点，仅暂停GPU1指定Qwen进程，断点迁移训练并自动恢复服务。"""
import json,os,signal,subprocess,time
from pathlib import Path
import torch
ROOT=Path('/mnt/data/luo/remote_runs/product_v15_training')
PYTHON='/home/luo/RS_agent_remote/.venv/bin/python'

def identity(pid,starttime):
    p=Path('/proc')/str(pid)
    try:return p.joinpath('stat').read_text().split(') ',1)[1].split()[19]==starttime
    except FileNotFoundError:return False

def main():
    snapshot=json.loads((ROOT/'migration/qwen_service.private.json').read_text());pid=snapshot['pid']
    assert identity(pid,snapshot['starttime'])
    args=(Path('/proc')/str(pid)/'cmdline').read_bytes().decode().rstrip('\0').split('\0')
    assert args==snapshot['argv'] and args[args.index('--served-model-name')+1]=='qwen35-4b'
    progress=json.loads((ROOT/'progress.json').read_text());target=((progress['rec_steps']+999)//1000)*1000
    began=time.time()
    while True:
        if (ROOT/'failure.json').exists():raise RuntimeError('训练已失败，暂不暂停Qwen')
        if (ROOT/'last.pt').exists():
            saved=torch.load(ROOT/'last.pt',map_location='cpu',weights_only=True)
            if saved['rec_steps']>=target:break
        if time.time()-began>180:raise TimeoutError('等待新断点超过3分钟，未暂停Qwen')
        time.sleep(2)
    migration={'state':'CHECKPOINT_READY','checkpoint_rec_steps':saved['rec_steps'],'epoch':saved['epoch'],
               'from_gpu':2,'to_gpu':1,'paused_service':'qwen35-4b / port18082','bge_kept_running':True,'timestamp':time.time()}
    (ROOT/'gpu_migration.json').write_text(json.dumps(migration,indent=2));print('GPU_MIGRATION_CHECKPOINT',saved['rec_steps'],flush=True)
    subprocess.run(['systemctl','--user','stop','rs-product-v15-training'],check=True)
    assert identity(pid,snapshot['starttime']);os.kill(pid,signal.SIGTERM)
    for _ in range(30):
        if not identity(pid,snapshot['starttime']):break
        time.sleep(1)
    if identity(pid,snapshot['starttime']):raise RuntimeError('Qwen主进程未退出；训练尚未迁移，保留快照以恢复')
    migration['state']='QWEN_PAUSED';(ROOT/'gpu_migration.json').write_text(json.dumps(migration,indent=2))
    try:
        subprocess.run(['systemd-run','--user','--unit=rs-product-v15-training-gpu1','--property=MemoryMax=12G','--property=CPUQuota=200%',
            '--property=CPUWeight=10','--property=Nice=15','--property=TimeoutStopSec=120',
            '--property=ExecStopPost=/usr/bin/python3 '+str(ROOT/'scripts/restore_qwen_after_v15.py'),
            '--setenv=CUDA_VISIBLE_DEVICES=1','--setenv=OMP_NUM_THREADS=1','--setenv=OPENBLAS_NUM_THREADS=1',PYTHON,str(ROOT/'scripts/train_product_v15.py')],check=True)
        migration['state']='TRAINING_GPU1';(ROOT/'gpu_migration.json').write_text(json.dumps(migration,indent=2));print('TRAINING_MOVED_GPU1',flush=True)
    except Exception:
        subprocess.run(['/usr/bin/python3',str(ROOT/'scripts/restore_qwen_after_v15.py')],check=True);raise

if __name__=='__main__':main()
